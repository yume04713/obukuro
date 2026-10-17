#!/usr/bin/env python3
"""Crawl public school-news pages and write a searchable JSON index.
Respect the source site's terms/robots guidance. This script does not download or mirror image files.
"""
import asyncio, json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://school.city.koshigaya.saitama.jp"
LISTING = BASE + "/obukuroh_e/notice/index/148/"
OUT = Path(__file__).resolve().parents[1] / "data" / "articles.json"
MAX_ARTICLES = 2000
MAX_PAGES = 250
ARTICLE_RE = re.compile(r"/(?:_view/)?obukuroh_e/notice/index/148/(\d+)/?$")

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def year_from(text, url):
    m = re.search(r"R\s*0?(\d+)年度", text or "")
    if m:
        return f"R{int(m.group(1)):02d}年度"
    m = re.search(r"/(\d{4})/", url or "")
    return m.group(1) if m else ""

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(locale="ja-JP")
        page.set_default_timeout(12000)
        print("一覧を開いています:", LISTING)
        await page.goto(LISTING, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeoutError:
            pass
        await page.wait_for_timeout(1500)

        article_urls = {}
        # The site loads entries in batches; keep clicking while the control exists.
        for page_no in range(MAX_PAGES):
            found = await page.locator("a[href]").evaluate_all("""els => els.map(a => ({href:a.href, text:(a.innerText||a.textContent||'').trim()}))""")
            for item in found:
                href = item.get("href", "")
                if ARTICLE_RE.search(urlparse(href).path):
                    article_urls[href.split("#")[0]] = item.get("text") or ""
            if len(article_urls) >= MAX_ARTICLES:
                print("上限に達したため終了")
                break
            button = page.get_by_text("次の10件を表示", exact=True)
            if await button.count() == 0:
                # Some variants use a button or a link with a slightly different label.
                button = page.get_by_text(re.compile(r"次の\s*10件を表示"))
            try:
                if await button.count() == 0 or not await button.first.is_visible():
                    break
                before = len(article_urls)
                await button.first.click()
                await page.wait_for_timeout(900)
                await page.wait_for_load_state("networkidle", timeout=5000)
                found = await page.locator("a[href]").evaluate_all("""els => els.map(a => ({href:a.href, text:(a.innerText||a.textContent||'').trim()}))""")
                for item in found:
                    href = item.get("href", "")
                    if ARTICLE_RE.search(urlparse(href).path):
                        article_urls[href.split("#")[0]] = item.get("text") or ""
                if len(article_urls) == before:
                    # Avoid clicking forever if the page did not change.
                    break
            except (PlaywrightTimeoutError, Exception) as exc:
                print("一覧の追加読み込み終了:", str(exc)[:120])
                break

        print(f"記事リンク候補: {len(article_urls)}件")
        articles = []
        for idx, (url, anchor_text) in enumerate(article_urls.items(), 1):
            try:
                await page.goto(url, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightTimeoutError:
                    pass
                await page.wait_for_timeout(250)
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                for el in soup(["script", "style", "noscript", "nav", "footer", "header"]):
                    el.decompose()
                title = ""
                for selector in ["main h1", "article h1", "h1", "main h2", "article h2", "h2", "title"]:
                    element = soup.select_one(selector)
                    if element and clean(element.get_text(" ", strip=True)):
                        title = clean(element.get_text(" ", strip=True))
                        break
                # Prefer content containers but fall back to body text if this site's markup changes.
                candidates = []
                for selector in ["main", "article", "[class*='notice-detail']", "[class*='notice_body']", "[class*='detail-body']", "#main"]:
                    candidates.extend(soup.select(selector))
                content = max(candidates, key=lambda e: len(e.get_text(" ", strip=True)), default=None)
                body = clean(content.get_text(" ", strip=True) if content else (soup.body.get_text(" ", strip=True) if soup.body else ""))
                if len(body) < 30:
                    body = anchor_text or body
                # Collect images from the article page; URLs remain hosted by the official source.
                images, seen = [], set()
                for img in (content or soup).find_all("img"):
                    src = img.get("src") or img.get("data-src") or img.get("data-original")
                    if not src:
                        continue
                    src = urljoin(url, src)
                    if urlparse(src).scheme not in ("http", "https") or src in seen:
                        continue
                    seen.add(src)
                    alt = clean(img.get("alt", ""))
                    images.append({"src": src, "alt": alt})
                category = "スクールライフ - R07年度の様子"
                # The current list route is R07; title/date may mention a different year.
                date = ""
                m = re.search(r"(20\d{2})[年/.-](\d{1,2})[月/.-](\d{1,2})", body)
                if m:
                    date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                else:
                    m = re.search(r"(20\d{2})[年/.-](\d{1,2})[月/.-](\d{1,2})", title)
                    if m:
                        date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                # Skip generic browser/cookie error pages rather than indexing them.
                if "Cookie" in title or "JavaScript設定を有効" in body[:300]:
                    print("取得できないページをスキップ:", url)
                    continue
                articles.append({
                    "id": url,
                    "title": title or anchor_text or url.rstrip("/").split("/")[-1],
                    "url": url,
                    "date": date,
                    "year": year_from(title + " " + body[:1000], url) or "R07年度",
                    "category": category,
                    "body": body,
                    "images": images
                })
                if idx % 25 == 0:
                    print(f"処理中: {idx}/{len(article_urls)}")
                await asyncio.sleep(0.4)
            except Exception as exc:
                print("記事取得エラー:", url, str(exc)[:100])

        # If the source is temporarily unavailable, do not overwrite a previously good index with empty data.
        if not articles and OUT.exists():
            raise RuntimeError("記事が0件でした。既存データを保持するため更新を中止します。")
        payload = {
            "updated_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z"),
            "source": LISTING,
            "articles": articles
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"保存しました: {len(articles)}件 -> {OUT}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
