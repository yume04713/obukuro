#!/usr/bin/env python3
"""Build a searchable JSON index of public school-news pages.

Please respect the source site's terms and robots guidance. Image files are not
 downloaded or mirrored; only their original URLs are recorded.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://school.city.koshigaya.saitama.jp"
LISTING = BASE + "/_view/obukuroh_e/notice/index/148/"
OUT = Path(__file__).resolve().parents[1] / "data" / "articles.json"
MAX_ARTICLES = 2000
MAX_PAGES = 250
REQUEST_DELAY_SECONDS = 0.4

# Matches a numeric article ID below the R07 school-news folder. Accepts paths
# both with and without the site's /_view/ prefix.
ARTICLE_RE = re.compile(
    r"/(?:_view/)?obukuroh_e/notice/index/148/(\d+)/?$"
)


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def year_from(text, url):
    match = re.search(r"R\s*0?(\d+)年度", text or "")
    if match:
        return f"R{int(match.group(1)):02d}年度"
    match = re.search(r"/(\d{4})/", url or "")
    return match.group(1) if match else ""


def article_url_from_href(href):
    """Return a canonical article URL if href looks like a target article."""
    if not href:
        return None
    absolute = urljoin(BASE, href.split("#", 1)[0])
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.netloc.lower() != urlparse(BASE).netloc.lower():
        return None
    if not ARTICLE_RE.search(parsed.path):
        return None
    return parsed._replace(query="", fragment="").geturl()


async def visible_links(page):
    return await page.locator("a[href]").evaluate_all(
        """els => els.map(a => ({
            href: a.href,
            text: (a.innerText || a.textContent || '').trim()
        }))"""
    )


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page(locale="ja-JP")
            page.set_default_timeout(12000)

            print("一覧を開いています:", LISTING)
            await page.goto(LISTING, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except PlaywrightTimeoutError:
                pass
            await page.wait_for_timeout(1500)

            # Diagnostic output helps identify changed source markup if no links
            # are found by the expected URL pattern.
            print("実際のURL:", page.url)
            print("ページタイトル:", await page.title())
            try:
                body_text = await page.locator("body").inner_text()
            except Exception:
                body_text = ""
            print("本文の先頭:", body_text[:1500])
            initial_links = await visible_links(page)
            print("リンク一覧:", initial_links[:30])

            article_urls = {}

            for page_no in range(MAX_PAGES):
                links = await visible_links(page)
                before = len(article_urls)
                for item in links:
                    url = article_url_from_href(item.get("href", ""))
                    if url:
                        article_urls[url] = clean(item.get("text", ""))
                        if len(article_urls) >= MAX_ARTICLES:
                            break

                if len(article_urls) >= MAX_ARTICLES:
                    print("記事数の上限に達したため終了")
                    break

                print(f"一覧読み込み {page_no + 1}/{MAX_PAGES}: {len(article_urls)}件")
                button = page.get_by_text("次の10件を表示", exact=True)
                if await button.count() == 0:
                    button = page.get_by_text(re.compile(r"次の\s*10件を表示"))

                try:
                    if await button.count() == 0 or not await button.first.is_visible():
                        break
                    await button.first.click()
                    await page.wait_for_timeout(1000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=4000)
                    except PlaywrightTimeoutError:
                        pass
                    updated_links = await visible_links(page)
                    for item in updated_links:
                        url = article_url_from_href(item.get("href", ""))
                        if url:
                            article_urls[url] = clean(item.get("text", ""))
                    if len(article_urls) == before:
                        print("追加読み込み後に新しい記事リンクがなかったため終了")
                        break
                except Exception as exc:
                    print("一覧の追加読み込み終了:", str(exc)[:160])
                    break

            print(f"記事リンク候補: {len(article_urls)}件")
            if not article_urls:
                print("想定した記事URLに一致するリンクが見つかりませんでした。上のURL・本文・リンク一覧を確認してください。")
                if OUT.exists():
                    raise RuntimeError("記事が0件でした。既存のJSONを保持するため更新を中止します。")
                raise RuntimeError("記事が0件でした。URL形式を確認する必要があります。")

            articles = []
            for index, (url, anchor_text) in enumerate(article_urls.items(), 1):
                try:
                    await page.goto(url, wait_until="domcontentloaded")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except PlaywrightTimeoutError:
                        pass
                    await page.wait_for_timeout(250)

                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    for element in soup(["script", "style", "noscript", "nav", "footer", "header"]):
                        element.decompose()

                    title = ""
                    for selector in (
                        "main h1", "article h1", "h1", "main h2", "article h2", "h2", "title"
                    ):
                        element = soup.select_one(selector)
                        if element:
                            candidate = clean(element.get_text(" ", strip=True))
                            if candidate:
                                title = candidate
                                break

                    content_candidates = []
                    for selector in (
                        "article", "main", "[class*='notice-detail']",
                        "[class*='notice_body']", "[class*='detail-body']", "#main"
                    ):
                        content_candidates.extend(soup.select(selector))
                    content = max(
                        content_candidates,
                        key=lambda element: len(element.get_text(" ", strip=True)),
                        default=None,
                    )
                    body = clean(
                        content.get_text(" ", strip=True)
                        if content
                        else (soup.body.get_text(" ", strip=True) if soup.body else "")
                    )
                    if len(body) < 30:
                        body = anchor_text or body

                    images = []
                    seen_images = set()
                    image_root = content or soup
                    for image_element in image_root.find_all("img"):
                        src = (
                            image_element.get("src")
                            or image_element.get("data-src")
                            or image_element.get("data-original")
                            or image_element.get("data-lazy-src")
                        )
                        if not src:
                            continue
                        src = urljoin(url, src)
                        if urlparse(src).scheme not in ("http", "https") or src in seen_images:
                            continue
                        seen_images.add(src)
                        images.append({"src": src, "alt": clean(image_element.get("alt", ""))})

                    date = ""
                    date_pattern = r"(20\d{2})[年/.-](\d{1,2})[月/.-](\d{1,2})"
                    match = re.search(date_pattern, body) or re.search(date_pattern, title)
                    if match:
                        date = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"

                    if "Cookie" in title or "JavaScript設定を有効" in body[:300]:
                        print("取得できないページをスキップ:", url)
                        continue

                    articles.append({
                        "id": url,
                        "title": title or anchor_text or url.rstrip("/").split("/")[-1],
                        "url": url,
                        "date": date,
                        "year": year_from(title + " " + body[:1000], url) or "R07年度",
                        "category": "スクールライフ - R07年度の様子",
                        "body": body,
                        "images": images,
                    })
                    if index % 25 == 0:
                        print(f"記事処理中: {index}/{len(article_urls)}")
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
                except Exception as exc:
                    print("記事取得エラー:", url, str(exc)[:160])

            if not articles:
                if OUT.exists():
                    raise RuntimeError("取得できた記事が0件でした。既存のJSONを保持するため更新を中止します。")
                raise RuntimeError("取得できた記事が0件でした。サイトのHTML構造を確認してください。")

            payload = {
                "updated_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z"),
                "source": LISTING,
                "articles": articles,
            }
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"保存しました: {len(articles)}件 -> {OUT}")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
