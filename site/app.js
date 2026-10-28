/* Tech Pulse: a small hash-routed reader. Data comes from data/*.json, refreshed by GitHub Actions. */
"use strict";

const CATS = {
  top:      { emoji: "⭐", blurb: "The stories the most sources are covering" },
  giants:   { emoji: "🏢", blurb: "Straight from Anthropic, OpenAI, Google, Apple, Microsoft, Thoughtworks and more" },
  models:   { emoji: "🧠", blurb: "New AI models, reasoning models and open weights" },
  ai:       { emoji: "🤖", blurb: "Agents, AI research and expert newsletters" },
  se:       { emoji: "🛠️", blurb: "Software engineering practice, tools and open source" },
  eng:      { emoji: "🏗️", blurb: "How Netflix, Meta, Stripe, Spotify and others build their systems" },
  green:    { emoji: "🌱", blurb: "IEA reports, clean energy and the energy cost of computing" },
  security: { emoji: "🔒", blurb: "Breaches, vulnerabilities and security analysis" },
  hardware: { emoji: "🖥️", blurb: "Chips, GPUs, servers and data-centre hardware" },
  tech:     { emoji: "📰", blurb: "Everything else from the big tech newsrooms" },
  videos:   { emoji: "▶️", blurb: "Latest videos from tech, AI and research channels" },
};
const FIELD_CLASS = { se: "se", ai: "ai", green: "green" };
const QUICK_TOPICS = [
  ["Agents", /\bagent(s|ic)?\b|multi-agent/i],
  ["LLMs", /\bLLMs?\b|large language model|language model/i],
  ["Energy & green", /energy|carbon|green|sustainab|power consumption/i],
  ["Uncertainty", /uncertain/i],
  ["Testing", /\btest(s|ing)?\b|fuzz/i],
  ["Code", /\bcode\b|program repair|code generation|coding/i],
  ["Security", /secur|vulnerab|attack|malware/i],
];
const PAGE_SIZE = 40;

/* ---------- storage (every access guarded: private mode can throw) ---------- */
const store = {
  get(k, d) { try { const v = localStorage.getItem("tp:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("tp:" + k, JSON.stringify(v)); } catch { /* ignore */ } },
};
const settings = Object.assign({ size: "m", theme: "auto", summaries: true, images: true, abstracts: false }, store.get("settings", {}));
let saved = store.get("saved", []);           // [{key, kind, item, savedAt}]
let visited = new Set(store.get("visited", []));
const lastSeen = store.get("lastSeen", {});    // category id -> ISO of newest item seen
const pendingSeen = {};

function applySettings() {
  const r = document.documentElement;
  r.dataset.size = settings.size;
  if (settings.theme === "auto") delete r.dataset.theme; else r.dataset.theme = settings.theme;
  store.set("settings", settings);
}
applySettings();

/* ---------- helpers ---------- */
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
const cache = new Map();
async function load(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(path, { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .catch((e) => { cache.delete(path); throw e; }));
  }
  return cache.get(path);
}
function ago(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
function dayLabel(iso) {
  const d = new Date(iso); const today = new Date(); const y = new Date(); y.setDate(today.getDate() - 1);
  const same = (a, b) => a.toDateString() === b.toDateString();
  if (same(d, today)) return "Today";
  if (same(d, y)) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}
const fmtDate = (d) => (d ? new Date(d + (d.length === 10 ? "T00:00:00" : "")).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "");
function markVisited(key) { visited.add(key); store.set("visited", [...visited].slice(-3000)); }
const isSaved = (key) => saved.some((s) => s.key === key);
function toggleSave(key, kind, item) {
  if (isSaved(key)) saved = saved.filter((s) => s.key !== key);
  else saved.unshift({ key, kind, item, savedAt: new Date().toISOString() });
  store.set("saved", saved);
  return isSaved(key);
}
function highlight(text, q) {
  const t = esc(text);
  if (!q) return t;
  const words = q.split(/\s+/).filter((w) => w.length > 1).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return words.length ? t.replace(new RegExp(`(${words.join("|")})`, "gi"), "<mark>$1</mark>") : t;
}
const matches = (q, ...fields) => !q || q.toLowerCase().split(/\s+/).every((w) => fields.join(" ").toLowerCase().includes(w));
const icon = {
  save: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4h10v17l-5-4-5 4z"/></svg>',
  chev: '<svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>',
  ext: '<svg viewBox="0 0 24 24" aria-hidden="true" style="width:16px;height:16px"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l13 8-13 8z"/></svg>',
};
const saveBtn = (key, label) => `<button class="save" data-save="${esc(key)}" aria-pressed="${isSaved(key)}" aria-label="${isSaved(key) ? "Remove from saved" : "Save for later"}: ${esc(label)}">${icon.save}</button>`;

/* ---------- page chrome ---------- */
const view = $("#view");
function setChrome(title, tab, showBack) {
  $("#page-title").textContent = title;
  document.title = title === "Tech Pulse" ? "Tech Pulse" : `${title} · Tech Pulse`;
  $("#back").hidden = !showBack;
  document.querySelectorAll(".tabbar a").forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
}
function setUpdated(iso, what = "News") { $("#updated").textContent = iso ? `${what} updated ${ago(iso)}` : ""; }
const skeleton = (n = 6) => Array.from({ length: n }, () => '<div class="skeleton"></div>').join("");
const errorBox = (msg) => `<div class="empty"><div class="big">📡</div><p>${esc(msg)}</p><p class="small">Check your connection and pull down to refresh.</p></div>`;
$("#back").addEventListener("click", () => (history.length > 1 ? history.back() : (location.hash = "#/")));

/* ---------- Today: the brief, top 3 per section, no story twice ---------- */
// Reading time: about 220 words a minute, plus a few seconds to take in each headline.
const storyMinutes = (s) => ((s.t + " " + (s.x || "")).split(/\s+/).length / 220) + 0.1;
async function renderHome() {
  setChrome("Today", "home", false);
  view.innerHTML = skeleton(5);
  let idx;
  try { idx = await load("data/news/index.json"); } catch { view.innerHTML = errorBox("Couldn't load the news."); return; }
  setUpdated(idx.updated);
  const sections = idx.brief.filter((b) => b.stories.length);
  const all = sections.flatMap((b) => b.stories);
  all.forEach((s) => itemByKey.set(s.u, { kind: "news", item: s }));
  const mins = Math.max(1, Math.round(all.reduce((t, s) => t + storyMinutes(s), 0)));
  const done = all.filter((s) => visited.has(s.u)).length;
  const count = Object.fromEntries(idx.categories.map((c) => [c.id, c.count]));
  const today = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  const maxTerm = Math.max(1, ...(idx.trending || []).map((t) => t[1]));

  const section = (b) => {
    const meta = CATS[b.id] || { emoji: "•", blurb: "" };
    const more = b.id === "top" ? "" : b.id === "models" ? `<a class="see-all" href="#/models">All model news and new models ${icon.chev}</a>`
      : `<a class="see-all" href="#/c/${b.id}">See all ${count[b.id] || ""} in ${esc(b.name)} ${icon.chev}</a>`;
    const models = b.id === "models" && idx.models?.new?.length ? `<div class="mini-models"><p class="mini-label">New models this month · ${idx.models.count}</p>
      ${idx.models.new.map((m) => `<a href="#/models/new" class="mini-model"><b>${esc(m.name)}</b><span>${esc(m.by)} · ${esc(fmtDate(m.d))}${m.reasoning ? " · reasoning" : ""}${m.open ? " · open weights" : ""}</span></a>`).join("")}</div>` : "";
    return `<section class="brief-sec" id="sec-${b.id}" aria-labelledby="bh-${b.id}">
      <h2 class="brief-h" id="bh-${b.id}"><span aria-hidden="true">${meta.emoji}</span> ${esc(b.name)}</h2>
      <p class="brief-blurb">${esc(meta.blurb)}</p>
      ${b.stories.map((s, n) => storyCard(s, n + 1)).join("")}${models}${more}</section>`;
  };
  view.innerHTML = `<div class="lead">
      <h2>${esc(today)}</h2>
      <p class="muted">${all.length} stories, picked from ${idx.itemCount} headlines. Each story appears once, with every source that covered it.</p>
    </div>
    <div class="meter" role="group" aria-label="Today's reading">
      <div class="meter-top"><span><b>About ${mins} min</b> to read the summaries</span><span id="meter-n">${done} of ${all.length} opened</span></div>
      <div class="bar" aria-hidden="true"><span id="meter-bar" style="width:${(100 * done) / all.length}%"></span></div>
    </div>
    <nav class="chips jump" aria-label="Jump to a section">
      ${sections.map((b) => `<a class="chip" href="#sec-${b.id}" data-jump="sec-${b.id}">${CATS[b.id]?.emoji || ""} ${esc(b.name)}</a>`).join("")}
    </nav>
    ${idx.trending?.length ? `<details class="trend"><summary>What's being talked about <span class="muted small">· last 2 days</span></summary>
      <p class="muted small">Words that appear in the most headlines, counting every source. Tap one to see those stories.</p>
      <ul class="trend-bars">${idx.trending.map(([w, n]) => `<li><a href="#/s/${encodeURIComponent(w)}"><span class="tw">${esc(w)}</span><span class="tb"><span style="width:${(100 * n) / maxTerm}%"></span></span><span class="tn">${n}</span></a></li>`).join("")}</ul></details>` : ""}
    ${sections.map(section).join("")}
    <p class="group-label">Go deeper</p>
    <div class="browse">${idx.categories.filter((c) => c.id !== "videos").map((c) => `<a class="venue" href="${c.id === "models" ? "#/models" : `#/c/${c.id}`}"><span class="cat-emoji" aria-hidden="true">${CATS[c.id]?.emoji || "•"}</span><span class="grow"><h3>${esc(c.name)}</h3><p>${esc(CATS[c.id]?.blurb || "")}</p></span><span class="count"><b>${c.count}</b>stories</span>${icon.chev}</a>`).join("")}</div>`;
  view.querySelectorAll("[data-jump]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault(); document.getElementById(a.dataset.jump)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  const updateMeter = () => {
    const n = all.filter((s) => visited.has(s.u)).length;
    const el = $("#meter-n"); if (!el) return;
    el.textContent = n === all.length ? "All done for today 🎉" : `${n} of ${all.length} opened`;
    $("#meter-bar").style.width = `${(100 * n) / all.length}%`;
  };
  view.addEventListener("click", (e) => { if (e.target.closest("[data-visit]")) setTimeout(updateMeter, 0); });
}

// One story in the brief: headline, the article's own opening lines, and the other sources that covered it.
function storyCard(s, rank) {
  const v = visited.has(s.u);
  const img = settings.images && s.img ? `<img class="thumb" src="${esc(safeUrl(s.img))}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : "";
  return `<article class="story${v ? " visited" : ""}">
    <div class="story-main">
      <span class="rank" aria-hidden="true">${rank}</span>
      <div class="body">
        <a class="link" href="${esc(safeUrl(s.u))}" target="_blank" rel="noopener" data-visit="${esc(s.u)}"><h3>${esc(s.t)}</h3></a>
        <div class="meta"><span class="src">${esc(s.s)}</span>${s.off ? '<span class="badge main">Official</span>' : ""}<span>· ${ago(s.d)}</span>${s.n > 1 ? `<span class="badge">${s.n} sources</span>` : ""}${s.min ? `<span>· ${s.min} min read</span>` : ""}</div>
        ${settings.summaries && s.x ? `<p class="sum full">${esc(s.x)}</p>` : ""}
      </div>
      <div class="side">${img}${saveBtn(s.u, s.t)}</div>
    </div>
    ${alsoList(s)}
  </article>`;
}
function alsoList(s) {
  if (!s.also?.length) return "";
  return `<details class="also"><summary>Also covered by ${esc(s.also.slice(0, 3).map((a) => a.s).join(", "))}${s.also.length > 3 ? ` +${s.also.length - 3}` : ""}</summary>
    <ul>${s.also.map((a) => `<li><a href="${esc(safeUrl(a.u))}" target="_blank" rel="noopener" data-visit="${esc(s.u)}"><b>${esc(a.s)}</b> ${esc(a.t)}</a></li>`).join("")}</ul></details>`;
}

/* ---------- search across every category ---------- */
async function renderSearch(q) {
  setChrome(`“${q}”`, "home", true);
  view.innerHTML = skeleton();
  let idx;
  try { idx = await load("data/news/index.json"); } catch { view.innerHTML = errorBox("Couldn't load the news."); return; }
  const ids = idx.categories.map((c) => c.id).filter((id) => id !== "videos");
  const files = await Promise.all(ids.map((id) => load(`data/news/${id}.json`).catch(() => ({ items: [] }))));
  const seen = new Set();
  const re = new RegExp(`\\b${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "i");
  const hits = files.flatMap((f) => f.items || f.news || []).filter((s) => !seen.has(s.u) && seen.add(s.u) && (re.test(s.t) || (s.also || []).some((a) => re.test(a.t))));
  hits.sort((a, b) => b.sc - a.sc || (b.d > a.d ? 1 : -1));
  setUpdated(idx.updated);
  view.innerHTML = `<div class="notice">${hits.length} stories mention <b>${esc(q)}</b>, most covered first.</div>`
    + (hits.length ? `<ul class="list">${hits.slice(0, 80).map((s) => newsRow(s, q, false)).join("")}</ul>` : `<div class="empty"><p>Nothing found.</p></div>`);
}

/* ---------- a news category ---------- */
async function renderCategory(id, opts = {}) {
  const isVideo = id === "videos";
  const meta = CATS[id] || {};
  setChrome("…", isVideo ? "videos" : "home", !isVideo);
  view.innerHTML = skeleton();
  let idx, data;
  try { [idx, data] = await Promise.all([load("data/news/index.json"), load(`data/news/${id}.json`)]); }
  catch { view.innerHTML = errorBox("Couldn't load this category."); return; }
  const cat = idx.categories.find((c) => c.id === id);
  setChrome(cat ? cat.name : id, isVideo ? "videos" : "home", !isVideo);
  setUpdated(idx.updated);
  const seenBefore = lastSeen[id];
  if (data.items[0]) pendingSeen[id] = data.items[0].d;

  const state = { q: "", src: opts.src || "", shown: PAGE_SIZE };
  // A story counts for a source if that source led it or also covered it.
  const srcOf = (i) => [i.s, ...(i.also || []).map((a) => a.s)];
  const tally = {};
  data.items.forEach((i) => new Set(srcOf(i)).forEach((n) => (tally[n] = (tally[n] || 0) + 1)));
  const sources = (cat?.sources || []).map((s) => ({ name: s.name, count: tally[s.name] || 0 })).filter((s) => s.count > 0);
  view.innerHTML = `${isVideo ? "" : `<p class="muted small" style="margin:2px 4px 8px">${esc(meta.blurb || "")}. The same story from several sources is shown once.</p>`}
    <div class="tools">
      <input class="search" type="search" placeholder="Search ${esc(cat?.name || "")}" aria-label="Search this category" enterkeyhint="search">
      <div class="chips" role="group" aria-label="Filter by source">
        <button class="chip" data-src="" aria-pressed="true">All<span class="n">${data.items.length}</span></button>
        ${sources.map((s) => `<button class="chip" data-src="${esc(s.name)}" aria-pressed="false">${esc(s.name)}<span class="n">${s.count}</span></button>`).join("")}
      </div>
    </div>
    <div id="results"></div>`;
  const results = $("#results");

  function draw() {
    const items = data.items.filter((i) => (!state.src || srcOf(i).includes(state.src)) && matches(state.q, i.t, i.x, ...srcOf(i)));
    if (!items.length) { results.innerHTML = `<div class="empty"><div class="big">🔍</div><p>Nothing matches.</p></div>`; return; }
    const page = items.slice(0, state.shown);
    let html = "";
    if (isVideo) {
      html = `<div class="vgrid">${page.map((i) => videoCard(i, state.q)).join("")}</div>`;
    } else {
      let day = "";
      html = `<ul class="list">` + page.map((i) => {
        const dl = dayLabel(i.d); let head = "";
        if (dl !== day) { day = dl; head = `<li class="day" role="presentation">${esc(dl)}</li>`; }
        return head + newsRow(i, state.q, seenBefore && i.d > seenBefore);
      }).join("") + `</ul>`;
    }
    if (items.length > state.shown) html += `<button class="more" id="more">Show more (${items.length - state.shown} left)</button>`;
    results.innerHTML = html;
    $("#more")?.addEventListener("click", () => { state.shown += PAGE_SIZE; draw(); });
  }
  let t;
  $(".search", view).addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); state.shown = PAGE_SIZE; draw(); }, 150); });
  view.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => {
    state.src = b.dataset.src; state.shown = PAGE_SIZE;
    view.querySelectorAll(".chip").forEach((x) => x.setAttribute("aria-pressed", x === b));
    draw();
  }));
  draw();
}

function newsRow(i, q, isNew) {
  const v = visited.has(i.u);
  const img = settings.images && i.img ? `<img class="thumb" src="${esc(safeUrl(i.img))}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : "";
  return `<li class="row${v ? " visited" : ""}">
    <div class="body">
      <a class="link" href="${esc(safeUrl(i.u))}" target="_blank" rel="noopener" data-visit="${esc(i.u)}">
        <h3>${highlight(i.t, q)}</h3>
        <div class="meta">${isNew && !v ? '<span class="dot-new" title="New since your last visit"></span><span class="sr-only">New.</span>' : ""}<span class="src">${esc(i.s)}</span>${i.off ? '<span class="badge main">Official</span>' : ""}<span>· ${ago(i.d)}</span>${i.n > 1 ? `<span class="badge">${i.n} sources</span>` : ""}${i.min ? `<span>· ${i.min} min read</span>` : ""}</div>
        ${settings.summaries && i.x ? `<p class="sum">${highlight(i.x, q)}</p>` : ""}
      </a>
      ${alsoList(i)}
    </div>
    <div class="side">${img}${saveBtn(i.u, i.t)}</div>
  </li>`;
}
function videoCard(i, q) {
  const v = visited.has(i.u);
  return `<article class="vcard${v ? " visited" : ""}">
    <a class="shot" href="${esc(safeUrl(i.u))}" target="_blank" rel="noopener" data-visit="${esc(i.u)}" aria-label="Play: ${esc(i.t)}">
      ${settings.images ? `<img src="${esc(safeUrl(i.img))}" alt="" loading="lazy">` : ""}
      <span class="play"><span>${icon.play}</span></span></a>
    <div class="vbody"><a class="link" href="${esc(safeUrl(i.u))}" target="_blank" rel="noopener" data-visit="${esc(i.u)}">
      <h3>${highlight(i.t, q)}</h3><div class="meta"><b>${esc(i.s)}</b> · ${ago(i.d)}</div></a>${saveBtn(i.u, i.t)}</div>
  </article>`;
}

/* ---------- Model Watch ---------- */
const fmtCtx = (n) => (!n ? "" : n >= 1e6 ? `${+(n / 1e6).toFixed(1)}M` : `${Math.round(n / 1e3)}K`);
const fmtPrice = (p) => (p === 0 ? "free" : p < 0.1 ? `$${p.toFixed(3)}` : `$${p.toFixed(2)}`);
const fmtNum = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n ?? ""));
async function renderModels(sub) {
  setChrome("Model Watch", "models", false);
  view.innerHTML = skeleton();
  let idx, data;
  try { [idx, data] = await Promise.all([load("data/news/index.json"), load("data/news/models.json")]); }
  catch { view.innerHTML = errorBox("Couldn't load Model Watch."); return; }
  setUpdated(idx.updated);
  const tabs = `<nav class="seg-tabs" aria-label="Model Watch">
    <a href="#/models/news" ${sub === "news" ? 'aria-current="page"' : ""}>Releases &amp; news</a>
    <a href="#/models/new" ${sub === "new" ? 'aria-current="page"' : ""}>New models</a>
    <a href="#/models/trending" ${sub === "trending" ? 'aria-current="page"' : ""}>Trending open</a></nav>`;
  if (sub === "new") {
    const FILTERS = [["", "All"], ["reasoning", "Reasoning"], ["open", "Open weights"], ["free", "Free to try"]];
    const state = { f: "" };
    view.innerHTML = `${tabs}<div class="notice">Every model added to OpenRouter in the last 30 days, newest first: who made it, how much text it can take in at once, and its price per million tokens (input · output).</div>
      <div class="chips" role="group" aria-label="Filter models">${FILTERS.map(([k, n]) => `<button class="chip" data-mf="${k}" aria-pressed="${k === ""}">${n}<span class="n">${k ? data.new.filter((m) => m[k]).length : data.new.length}</span></button>`).join("")}</div>
      <div id="results"></div>`;
    const draw = () => {
      const list = data.new.filter((m) => !state.f || m[state.f]);
      $("#results").innerHTML = list.length ? list.map((m) => `<article class="model">
        <div class="model-top"><div class="grow"><h3>${esc(m.name)}</h3><p class="muted small">${esc(m.by)} · added ${esc(fmtDate(m.d))}</p></div></div>
        <div class="tags">${m.reasoning ? '<span class="badge ai">Reasoning</span>' : ""}${m.open ? '<span class="badge se">Open weights</span>' : ""}${m.free ? '<span class="badge green">Free to try</span>' : ""}${(m.mod || []).filter((x) => x !== "text").map((x) => `<span class="badge">${esc(x)}</span>`).join("")}</div>
        ${m.x ? `<p class="sum full">${esc(m.x)}</p>` : ""}
        <dl class="facts"><div><dt>Context</dt><dd>${fmtCtx(m.ctx)} tokens</dd></div><div><dt>Price per 1M tokens</dt><dd>${m.in === 0 && m.out === 0 ? "free" : `${fmtPrice(m.in)} · ${fmtPrice(m.out)}`}</dd></div></dl>
        <div class="links"><a class="btn" href="${esc(safeUrl(m.u))}" target="_blank" rel="noopener">OpenRouter ${icon.ext}</a>${m.hf ? `<a class="btn" href="https://huggingface.co/${esc(m.hf)}" target="_blank" rel="noopener">Hugging Face ${icon.ext}</a>` : ""}</div>
      </article>`).join("") : `<div class="empty"><p>No models match.</p></div>`;
    };
    view.querySelectorAll("[data-mf]").forEach((b) => b.addEventListener("click", () => {
      state.f = b.dataset.mf; view.querySelectorAll("[data-mf]").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw();
    }));
    draw();
  } else if (sub === "trending") {
    view.innerHTML = `${tabs}<div class="notice">The models people are downloading and liking most on Hugging Face right now.</div>
      <ol class="trend-list">${data.trending.map((m) => `<li><a href="${esc(safeUrl(m.u))}" target="_blank" rel="noopener">
        <span class="grow"><b>${esc(m.name)}</b><span class="muted small">${esc(m.by)}${m.task ? ` · ${esc(m.task.replace(/-/g, " "))}` : ""}${m.d ? ` · ${esc(fmtDate(m.d))}` : ""}</span></span>
        <span class="count"><b>♥ ${fmtNum(m.likes)}</b>${fmtNum(m.dl)} downloads</span></a></li>`).join("")}</ol>`;
  } else {
    view.innerHTML = `${tabs}<div class="notice">Model launches and model news from the labs and AI newsrooms, the same story from several sources shown once.</div>
      ${data.news.length ? `<ul class="list">${data.news.map((s) => newsRow(s, "", false)).join("")}</ul>` : `<div class="empty"><p>No model news in the last two weeks.</p></div>`}`;
  }
}

/* ---------- Papers ---------- */
async function renderPapers(sub = "conferences") {
  setChrome("Research papers", "papers", false);
  view.innerHTML = skeleton();
  let idx;
  try { idx = await load("data/papers/index.json"); } catch { view.innerHTML = errorBox("Couldn't load the papers."); return; }
  setUpdated(idx.updated, "Papers");
  const field = store.get("paperField", "");
  const tabs = `<nav class="seg-tabs" aria-label="Paper sources">
    <a href="#/papers/conferences" ${sub === "conferences" ? 'aria-current="page"' : ""}>Conferences</a>
    <a href="#/papers/journals" ${sub === "journals" ? 'aria-current="page"' : ""}>Journals</a>
    <a href="#/papers/topics" ${sub === "topics" ? 'aria-current="page"' : ""}>My topics</a></nav>`;
  const fieldChips = `<div class="chips" role="group" aria-label="Filter by field">
    <button class="chip" data-field="" aria-pressed="${!field}">All fields</button>
    ${idx.fields.map((f) => `<button class="chip" data-field="${f.id}" aria-pressed="${field === f.id}">${esc(f.name)}</button>`).join("")}</div>`;
  const fieldName = Object.fromEntries(idx.fields.map((f) => [f.id, f.name]));
  let body = "";
  // Grouped by field in a fixed order, so each venue is always in the same place.
  const byField = (list, row) => idx.fields.filter((f) => !field || f.id === field).map((f) => {
    const rows = list.filter((x) => x.field === f.id);
    return rows.length ? `<p class="group-label">${esc(f.name)}</p>${rows.map(row).join("")}` : "";
  }).join("");
  const week = (n) => (n ? `<br><span style="color:var(--new)">+${n} this week</span>` : "");
  if (sub === "conferences") {
    body = `<div class="notice">These are papers whose authors posted them on arXiv and wrote "accepted at…". That usually happens weeks before the conference. Each conference also links to its full official program.</div>
      ${byField(idx.conferences, (c) => `<a class="venue" href="#/p/conf/${encodeURIComponent(c.key)}">
        <span class="grow"><h3>${esc(c.id)} ${c.year}</h3><p>${esc(c.name)}</p></span>
        <span class="count"><b>${c.count}</b>papers${week(c.week)}</span>${icon.chev}</a>`) || '<div class="empty">No conferences here yet.</div>'}`;
  } else if (sub === "journals") {
    body = `<div class="notice">The newest articles from each journal, with abstracts, refreshed daily.</div>
      ${byField(idx.journals, (j) => `<a class="venue" href="#/p/journal/${encodeURIComponent(j.key)}">
        <span class="grow"><h3>${esc(j.id)}</h3><p>${esc(j.name)}</p></span>
        <span class="count"><b>${j.count}</b>latest${week(j.week)}</span>${icon.chev}</a>`)}`;
  } else {
    body = `<div class="notice">New arXiv papers from the last 10 days on topics you follow.</div>
      ${idx.topics.map((t) => `<a class="venue" href="#/p/topic/${encodeURIComponent(t.key)}">
        <span class="grow"><h3>${esc(t.name)}</h3><p>arXiv search, newest first</p></span>
        <span class="count"><b>${t.count}</b>papers${t.week ? `<br><span style="color:var(--new)">+${t.week} this week</span>` : ""}</span>${icon.chev}</a>`).join("")}`;
  }
  view.innerHTML = `${tabs}${sub === "topics" ? "" : fieldChips}<div style="margin-top:10px">${body}</div>`;
  view.querySelectorAll("[data-field]").forEach((b) => b.addEventListener("click", () => { store.set("paperField", b.dataset.field); renderPapers(sub); }));
}

async function renderPaperList(kind, key) {
  setChrome("…", "papers", true);
  view.innerHTML = skeleton();
  let idx;
  try { idx = await load("data/papers/index.json"); } catch { view.innerHTML = errorBox("Couldn't load the papers."); return; }
  const list = { conf: idx.conferences, journal: idx.journals, topic: idx.topics }[kind] || [];
  const v = list.find((x) => x.key === key);
  if (!v) { view.innerHTML = errorBox("This list isn't available any more."); return; }
  const title = kind === "conf" ? `${v.id} ${v.year}` : kind === "journal" ? v.id : v.name;
  setChrome(title, "papers", true);
  setUpdated(idx.updated, "Papers");
  let data;
  try { data = await load(`data/papers/${v.file}`); } catch { view.innerHTML = errorBox("Couldn't load this list."); return; }
  data.items.forEach((i) => { i.venue = i.venue || title; });

  const state = { q: "", kind: "", topic: "", shown: PAGE_SIZE };
  const kinds = v.kinds ? Object.entries(v.kinds).sort((a, b) => b[1] - a[1]) : [];
  const topicCounts = QUICK_TOPICS.map(([n, re]) => [n, re, data.items.filter((i) => re.test(i.t + " " + i.abs)).length]).filter((x) => x[2]);
  const intro = kind === "conf"
    ? `<div class="notice"><b>${esc(v.name)}</b><br>${v.count} accepted papers found on arXiv so far.
       <a href="${esc(safeUrl(v.official))}" target="_blank" rel="noopener">See the full official program ↗</a></div>`
    : kind === "journal" ? `<div class="notice"><b>${esc(v.name)}</b><br>Newest ${v.count} articles.</div>`
    : `<div class="notice">Newest arXiv papers: <b>${esc(v.name)}</b>.</div>`;
  view.innerHTML = `${intro}
    <div class="tools">
      <input class="search" type="search" placeholder="Search titles, abstracts, authors" aria-label="Search papers" enterkeyhint="search">
      ${kinds.length > 1 ? `<div class="chips" role="group" aria-label="Track">
        <button class="chip" data-kind="" aria-pressed="true">All tracks<span class="n">${data.items.length}</span></button>
        ${kinds.map(([k, n]) => `<button class="chip" data-kind="${esc(k)}" aria-pressed="false">${esc(k)}<span class="n">${n}</span></button>`).join("")}</div>` : ""}
      ${topicCounts.length ? `<div class="chips" role="group" aria-label="Quick topics">
        ${topicCounts.map(([n, , c]) => `<button class="chip" data-topic="${esc(n)}" aria-pressed="false">${esc(n)}<span class="n">${c}</span></button>`).join("")}</div>` : ""}
    </div><div id="results"></div>`;
  const results = $("#results");
  function draw() {
    const re = QUICK_TOPICS.find(([n]) => n === state.topic)?.[1];
    const items = data.items.filter((i) => (!state.kind || i.k === state.kind) && (!re || re.test(i.t + " " + i.abs)) && matches(state.q, i.t, i.abs, (i.a || []).join(" ")));
    if (!items.length) { results.innerHTML = `<div class="empty"><div class="big">🔍</div><p>No papers match.</p></div>`; return; }
    results.innerHTML = items.slice(0, state.shown).map((i) => paperCard(i, state.q, title)).join("")
      + (items.length > state.shown ? `<button class="more" id="more">Show more (${items.length - state.shown} left)</button>` : "");
    $("#more")?.addEventListener("click", () => { state.shown += PAGE_SIZE; draw(); });
  }
  let t;
  $(".search", view).addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); state.shown = PAGE_SIZE; draw(); }, 150); });
  view.querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => {
    state.kind = b.dataset.kind; state.shown = PAGE_SIZE;
    view.querySelectorAll("[data-kind]").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw();
  }));
  view.querySelectorAll("[data-topic]").forEach((b) => b.addEventListener("click", () => {
    state.topic = state.topic === b.dataset.topic ? "" : b.dataset.topic; state.shown = PAGE_SIZE;
    view.querySelectorAll("[data-topic]").forEach((x) => x.setAttribute("aria-pressed", x.dataset.topic === state.topic)); draw();
  }));
  draw();
}

function paperCard(i, q, venue) {
  const v = visited.has(i.u);
  const who = (i.a || []).join(", ") + (i.na > (i.a || []).length ? ` +${i.na - i.a.length} more` : "");
  return `<article class="paper${v ? " visited" : ""}">
    <div class="top"><div class="grow">
      <h3>${highlight(i.t, q)}</h3>
      <p class="authors">${highlight(who, q)}</p>
      <div class="tags">${i.k ? `<span class="badge ${i.k === "Main" ? "main" : ""}">${esc(i.k)}</span>` : ""}<span class="muted small">${esc(fmtDate(i.d))}</span>${venue ? `<span class="muted small">· ${esc(venue)}</span>` : ""}</div>
    </div>${saveBtn(i.u, i.t)}</div>
    ${i.abs ? `<details ${settings.abstracts || q ? "open" : ""}><summary>Abstract</summary><p class="abs">${highlight(i.abs, q)}</p>${i.absSrc ? `<p class="muted small">Abstract from the <a href="${esc(safeUrl(i.arxiv))}" target="_blank" rel="noopener">${esc(i.absSrc)}</a>; the published version may differ slightly.</p>` : ""}${i.cm ? `<p class="muted small">Author note: ${esc(i.cm)}</p>` : ""}</details>` : `<p class="muted small" style="margin:8px 0 0">No abstract shared by the publisher.</p>`}
    <div class="links">
      <a class="btn primary-link" href="${esc(safeUrl(i.u))}" target="_blank" rel="noopener" data-visit="${esc(i.u)}">Open paper ${icon.ext}</a>
      ${i.pdf ? `<a class="btn" href="${esc(safeUrl(i.pdf))}" target="_blank" rel="noopener" data-visit="${esc(i.u)}">PDF</a>` : ""}
    </div>
  </article>`;
}
// Keep the item so it can be saved without re-fetching.
const itemByKey = new Map();
function remember(items, kind) { items.forEach((i) => itemByKey.set(i.u, { kind, item: i })); }

/* ---------- Saved ---------- */
function renderSaved() {
  setChrome("Saved", "saved", false);
  $("#updated").textContent = saved.length ? `${saved.length} saved` : "";
  if (!saved.length) {
    view.innerHTML = `<div class="empty"><div class="big">🔖</div><p>Nothing saved yet.</p><p class="small">Tap the bookmark next to any story, video or paper to read it later.</p></div>`;
    return;
  }
  view.innerHTML = `<p class="muted small" style="margin:4px 4px 12px">Saved on this device only.</p>` + saved.map((s) => {
    if (s.kind === "paper") return paperCard(s.item, "", s.item.venue);
    if (s.kind === "video") return `<div class="vgrid" style="margin-bottom:10px">${videoCard(s.item, "")}</div>`;
    return `<ul class="list">${newsRow(s.item, "", false)}</ul>`;
  }).join("");
}

/* ---------- global click handling ---------- */
document.addEventListener("click", (e) => {
  const s = e.target.closest("[data-save]");
  if (s) {
    e.preventDefault();
    const key = s.dataset.save;
    let rec = itemByKey.get(key) || saved.find((x) => x.key === key);
    if (!rec) return;
    const on = toggleSave(key, rec.kind, rec.item);
    document.querySelectorAll(`[data-save="${CSS.escape(key)}"]`).forEach((b) => { b.setAttribute("aria-pressed", on); b.setAttribute("aria-label", on ? "Remove from saved" : "Save for later"); });
    if (location.hash === "#/saved" && !on) renderSaved();
    return;
  }
  const a = e.target.closest("[data-visit]");
  if (a) {
    markVisited(a.dataset.visit);
    a.closest(".row, .vcard, .paper")?.classList.add("visited");
  }
});

/* Wrap loaders so every item we draw can be saved. */
const _load = load;
load = async (path) => {
  const d = await _load(path);
  if (d && d.items && !d.__seen) {
    const kind = path.includes("/papers/") ? "paper" : path.endsWith("videos.json") ? "video" : "news";
    remember(d.items, kind);
    d.__seen = true;
  }
  if (d && d.news && !d.__seen) {
    remember(d.news, "news");
    d.__seen = true;
  }
  return d;
};

/* ---------- settings dialog ---------- */
const dlg = $("#settings");
$("#open-settings").addEventListener("click", () => {
  dlg.querySelectorAll(".seg").forEach((seg) => seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", settings[seg.dataset.setting] === b.value)));
  dlg.querySelectorAll("input[data-setting]").forEach((i) => (i.checked = !!settings[i.dataset.setting]));
  dlg.showModal();
});
dlg.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
  const seg = b.parentElement; settings[seg.dataset.setting] = b.value; applySettings();
  seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
}));
dlg.querySelectorAll("input[data-setting]").forEach((i) => i.addEventListener("change", () => { settings[i.dataset.setting] = i.checked; applySettings(); }));
dlg.addEventListener("close", route);
dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
document.querySelectorAll(".seg[data-setting=size] button").forEach((b, n) => b.setAttribute("aria-label", ["Small", "Medium", "Large", "Extra large"][n] + " text"));

/* ---------- router ---------- */
function commitSeen() {
  Object.assign(lastSeen, pendingSeen);
  for (const k in pendingSeen) delete pendingSeen[k];
  store.set("lastSeen", lastSeen);
}
function route() {
  commitSeen();
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  window.scrollTo(0, 0);
  if (parts[0] === "c" && parts[1]) return renderCategory(parts[1]);
  if (parts[0] === "videos") return renderCategory("videos");
  if (parts[0] === "papers") return renderPapers(parts[1] || store.get("paperTab", "conferences"));
  if (parts[0] === "p" && parts[1]) return renderPaperList(parts[1], parts.slice(2).join("/"));
  if (parts[0] === "saved") return renderSaved();
  if (parts[0] === "models") return renderModels(parts[1] || "news");
  if (parts[0] === "s" && parts[1]) return renderSearch(parts.slice(1).join("/"));
  return renderHome();
}
window.addEventListener("hashchange", () => {
  const m = location.hash.match(/^#\/papers\/(\w+)/); if (m) store.set("paperTab", m[1]);
  route();
});
window.addEventListener("pagehide", commitSeen);
// Coming back to the tab after a while: drop cached data so the newest hour shows.
let hiddenAt = 0;
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { hiddenAt = Date.now(); commitSeen(); }
  else if (Date.now() - hiddenAt > 10 * 60 * 1000) { cache.clear(); route(); }
});
route();
