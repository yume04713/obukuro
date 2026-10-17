const $ = (s) => document.querySelector(s);
const state = { data: [], view: "articles" };
const safe = (value) => String(value ?? "");
const normalize = (value) => safe(value).normalize("NFKC").toLocaleLowerCase("ja");
const escapeText = (value) => safe(value);

async function start() {
  try {
    const response = await fetch("data/articles.json", { cache: "no-store" });
    if (!response.ok) throw new Error("data/articles.json を読み込めません");
    const payload = await response.json();
    state.data = Array.isArray(payload.articles) ? payload.articles : [];
    $("#updated").textContent = payload.updated_at || "未取得";
    fillFilters();
    render();
    $("#status").textContent = state.data.length
      ? `記事データ ${state.data.length.toLocaleString()}件を読み込みました`
      : "まだ記事データがありません。GitHub Actions の取得処理を実行してください。";
  } catch (error) {
    $("#status").textContent = "記事データを読み込めませんでした。data/articles.json が存在するか確認してください。";
    $("#articles").innerHTML = '<div class="empty">データを読み込めませんでした。</div>';
  }
}

function fillFilters() {
  const years = [...new Set(state.data.map(x => x.year).filter(Boolean))].sort().reverse();
  const categories = [...new Set(state.data.map(x => x.category).filter(Boolean))].sort();
  for (const [selector, values] of [["#year", years], ["#category", categories]]) {
    const select = $(selector);
    for (const value of values) {
      const option = document.createElement("option");
      option.value = value; option.textContent = value;
      select.append(option);
    }
  }
}

function filtered() {
  const q = normalize($("#query").value.trim());
  const year = $("#year").value, category = $("#category").value;
  return state.data.filter(item => {
    if (year && item.year !== year) return false;
    if (category && item.category !== category) return false;
    if (!q) return true;
    return normalize([item.title, item.body, item.category, item.date].join("\n")).includes(q);
  });
}

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function render() {
  const results = filtered();
  $("#articles").replaceChildren();
  $("#images").replaceChildren();
  $("#article-count").textContent = `${results.length.toLocaleString()}件`;
  const images = [];
  for (const item of results) {
    const article = node("article", "article");
    const h = node("h3");
    const link = node("a", "", item.title || "（タイトルなし）");
    link.href = item.url || "#"; link.target = "_blank"; link.rel = "noopener noreferrer";
    h.append(link); article.append(h);
    article.append(node("div", "meta", [item.date, item.category].filter(Boolean).join(" · ")));
    const excerpt = safe(item.body).trim();
    article.append(node("p", "excerpt", excerpt.length > 520 ? excerpt.slice(0, 520) + "…" : excerpt || "本文を取得できませんでした。"));
    const bottom = node("div", "card-bottom");
    bottom.append(node("span", "pill", item.year || "年度不明"));
    const open = node("a", "", "元記事を開く ↗");
    open.href = item.url || "#"; open.target = "_blank"; open.rel = "noopener noreferrer";
    bottom.append(open); article.append(bottom);
    $("#articles").append(article);
    for (const img of (item.images || [])) {
      if (img && img.src) images.push({ ...img, articleTitle: item.title, articleUrl: item.url, date: item.date });
    }
  }
  if (!results.length) $("#articles").append(node("div", "empty", "一致する記事がありません。別の言葉で検索してみてください。"));
  $("#image-count").textContent = `${images.length.toLocaleString()}枚`;
  for (const img of images) {
    const a = node("a", "image-card");
    a.href = img.articleUrl || img.src; a.target = "_blank"; a.rel = "noopener noreferrer";
    const image = document.createElement("img");
    image.src = img.src; image.alt = img.alt || img.articleTitle || "学校サイト掲載画像";
    image.loading = "lazy"; image.referrerPolicy = "strict-origin-when-cross-origin";
    image.addEventListener("error", () => a.remove(), { once: true });
    const caption = node("div", "caption");
    caption.append(node("strong", "", img.articleTitle || "記事画像"));
    caption.append(node("span", "", [img.date, img.alt].filter(Boolean).join(" · ")));
    a.append(image, caption); $("#images").append(a);
  }
  if (!images.length) $("#images").append(node("div", "empty", "検索条件に一致する画像がありません。"));
}

$("#query").addEventListener("input", render);
$("#year").addEventListener("change", render);
$("#category").addEventListener("change", render);
$("#clear").addEventListener("click", () => { $("#query").value = ""; $("#year").value = ""; $("#category").value = ""; render(); });
document.querySelectorAll(".tab").forEach(button => button.addEventListener("click", () => {
  state.view = button.dataset.view;
  document.querySelectorAll(".tab").forEach(tab => { const active = tab === button; tab.classList.toggle("active", active); tab.setAttribute("aria-selected", String(active)); });
  $("#articles-view").hidden = state.view !== "articles";
  $("#images-view").hidden = state.view !== "images";
}));
start();
