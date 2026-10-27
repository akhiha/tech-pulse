/* Tech Pulse: a small hash-routed reader. Data comes from data/*.json, refreshed by GitHub Actions. */
"use strict";

const CATS = {
  tech:     { emoji: "📰", blurb: "The day's tech stories from the big newsrooms" },
  giants:   { emoji: "🏢", blurb: "Straight from Google, Apple, Microsoft, OpenAI and more" },
  ai:       { emoji: "🤖", blurb: "AI models, agents, labs and expert newsletters" },
  se:       { emoji: "🛠️", blurb: "Software engineering practice, tools and open source" },
  green:    { emoji: "🌱", blurb: "Climate, clean energy and the energy cost of computing" },
  security: { emoji: "🔒", blurb: "Breaches, vulnerabilities and security analysis" },
  hardware: { emoji: "🖥️", blurb: "Chips, GPUs, servers and data-centre hardware" },
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

/* ---------- Home: one card per category ---------- */
async function renderHome() {
  setChrome("Tech Pulse", "home", false);
  view.innerHTML = skeleton(5);
  let idx;
  try { idx = await load("data/news/index.json"); } catch { view.innerHTML = errorBox("Couldn't load the news."); return; }
  setUpdated(idx.updated);
  const hour = new Date().getHours();
  const hello = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const card = (c) => {
    const meta = CATS[c.id] || { emoji: "•", blurb: "" };
    const seen = lastSeen[c.id];
    const fresh = seen ? c.top.filter((i) => i.d > seen).length : 0;
    const href = c.id === "videos" ? "#/videos" : `#/c/${c.id}`;
    return `<section class="cat-card" aria-labelledby="h-${c.id}">
      <a class="cat-head" href="${href}">
        <span class="cat-emoji" aria-hidden="true">${meta.emoji}</span>
        <span class="grow"><h3 id="h-${c.id}">${esc(c.name)}</h3><p>${esc(meta.blurb)}</p></span>
        ${fresh ? `<span class="pill-new">${fresh}${fresh === 3 ? "+" : ""} new</span>` : ""}
      </a>
      <ul class="cat-top">${c.top.map((i) => `<li><a href="${esc(safeUrl(i.u))}" target="_blank" rel="noopener" data-visit="${esc(i.u)}">${esc(i.t)}<span class="meta">${esc(i.s)} · ${ago(i.d)}</span></a></li>`).join("")}</ul>
      <a class="see-all" href="${href}">See all ${c.count} ${c.id === "videos" ? "videos" : "stories"} ${icon.chev}</a>
    </section>`;
  };
  const news = idx.categories.filter((c) => c.id !== "videos");
  view.innerHTML = `<div class="lead"><h2>${hello}</h2><p class="muted">Pick a topic. Each one opens on its own page.</p></div>
    <p class="group-label">News</p>${news.map(card).join("")}
    <p class="group-label">Watch &amp; read</p>
    ${idx.categories.filter((c) => c.id === "videos").map(card).join("")}
    <section class="cat-card"><a class="cat-head" href="#/papers"><span class="cat-emoji" aria-hidden="true">📄</span>
      <span class="grow"><h3>Research papers</h3><p>Accepted conference papers, new journal articles and your research topics</p></span></a>
      <a class="see-all" href="#/papers">Browse conferences, journals and topics ${icon.chev}</a></section>`;
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
  const sources = (cat?.sources || []).filter((s) => s.count > 0);
  view.innerHTML = `
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
    const items = data.items.filter((i) => (!state.src || i.s === state.src) && matches(state.q, i.t, i.x, i.s));
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
        <div class="meta">${isNew && !v ? '<span class="dot-new" title="New since your last visit"></span><span class="sr-only">New.</span>' : ""}<span class="src">${esc(i.s)}</span><span>· ${ago(i.d)}</span>${i.min ? `<span>· ${i.min} min read</span>` : ""}</div>
        ${settings.summaries && i.x ? `<p class="sum">${highlight(i.x, q)}</p>` : ""}
      </a>
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
