"""Fetch every source in feeds.json and build the daily brief.

Writes to site/data/news/:
  <category>.json  every story in that category, newest first
  models.json      Model Watch: newly released models (OpenRouter) and trending open models (Hugging Face)
  index.json       the brief (top stories per category, no story twice), source counts, problems

Source types in feeds.json:
  rss (default)  an RSS/Atom feed
  html           a listing page with no feed: links matching "match" are opened once each and their
                 title, date, picture and opening paragraphs read from the page (remembered in page_cache.json)
  gnews          Google News search (for sites that block automated access, e.g. the IEA). With "link",
                 each result points straight to the site's own page, built from the title

The same story from several sources becomes one story: the original source leads and the rest are
listed under it. Stories are ranked by how many sources cover them, whether the company itself
published it, and how recent it is. Summaries are the article's own opening sentences (no AI).

Run hourly by GitHub Actions. A source that fails is skipped and reported; the run never fails because of one source.
"""
import html
import json
import math
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import feedparser

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "news"
# Kept between runs by the Actions cache, outside site/ so they are not published.
CACHE_DIR = ROOT / ".cache"
CACHE_FILE = CACHE_DIR / "page_cache.json"
LAST_GOOD_FILE = CACHE_DIR / "last_good.json"
UA = "Mozilla/5.0 (compatible; TechPulse/1.0; personal news reader)"
PER_FEED = 25
DEFAULT_MAX_AGE_DAYS = 14
BRIEF_PER_SECTION = 3
SAME_STORY_HOURS = 72        # two headlines only count as one story if published this close together
PAGE_FETCHES_PER_RUN = 80    # article pages opened per run (for scraped sources and missing summaries)
CACHE_DAYS = 45
MODEL_DAYS = 30

TAG_RE = re.compile(r"""<(?:"[^"]*"|'[^']*'|[^'">])*>""")
IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
WS_RE = re.compile(r"\s+")
# Feed boilerplate that is not part of the story.
JUNK_RE = re.compile(r"(^Back to (Articles|Blog)\s*|The post .{0,200}? appeared first on .*$|Continue reading.*$|Read more.*$|Article URL:.*$|\[…\]|\[\.\.\.\]|…\s*$)", re.I | re.S)
SENT_RE = re.compile(r"(?<=[.!?])[\"”’)]?\s+(?=[A-Z0-9\"“‘(])")

# A model release: a release word plus the name of a model family (or "model" next to an AI word).
RELEASE_RE = re.compile(r"\b(introduc\w*|launch\w*|releas\w*|unveil\w*|announc\w*|debut\w*|rolls? out|now available|open[- ]sourc\w*|welcome)\b", re.I)
MODEL_RE = re.compile(r"\b(GPT[- ]?\d[\w.]*|o\d(-\w+)?|Claude|Opus|Sonnet|Haiku|Gemini|Gemma|Llama|Qwen\w*|DeepSeek|Mistral|Mixtral|Grok|Phi-\d|Kimi|MiniMax|GLM|Nemotron|Granite|Command [AR]|Codex|Sora|Veo|Imagen|FLUX|Genie|Muse|LFM\d*)\b"
                      r"|\b(model|LLM|reasoning model|open[- ]weights?)\b(?=.*\b(AI|LLM|reasoning|open|weights|parameters|benchmark)\b)", re.I)

STOP = set("""a an the and or but for to of in on at by from with as is are was were be been being it its this that these those
new how why what when who which where now after over into about says said say will would can could may might should you your
our we us they their them he she his her just more most than up out not no has have had get gets got first report reports reportedly
via amid update updates week today year years day days here there all any some one two three also off back down like make makes made
use uses using inside behind under against still big top best ever every own way ways things thing look looks going""".split())
DIGEST_RE = re.compile(r"^\[AINews\]|\bDaily:|\bweekly\b|round-?up|this week|newsletter|digest|podcast|episode|\bTWiT\b|links for", re.I)
# Customer stories and marketing posts from company blogs rank lower.
PROMO_RE = re.compile(r"\b(uses?|using|helps?|powers?|chooses?) (OpenAI|ChatGPT|Claude|Gemini|Azure|AWS|Copilot|NVIDIA)\b|customer stor|case study|webinar|\bsponsored\b", re.I)
GENERIC = set("launch launches launched announces announced announcing introduces introducing introduce unveils unveiled releases released release rolls".split())


def clean_text(s):
    s = TAG_RE.sub(" ", html.unescape(TAG_RE.sub(" ", s or "")))     # some feeds escape their HTML twice
    s = WS_RE.sub(" ", html.unescape(s)).strip()
    return JUNK_RE.sub("", s).strip()


# Sentences that are not about the story: author bios, sponsor lines, newsletter housekeeping.
NOT_STORY_RE = re.compile(r"\bis an? (writer|journalist|editor|reporter|contributor)\b|covering the .{0,30}beat|\(Sponsored\)|^\[(Webinar|Sponsored|Ad)\]"
                          r"|^(Before we start|Programming note|Quick note|Hi everyone|Hey everyone|Welcome to|This (post|article|episode) is sponsored)|subscribe|sign up for", re.I)


def summarize(text, title="", limit=320):
    """The opening sentences of the article, up to about two sentences."""
    s = clean_text(text)
    if not s or norm(s) == norm(title) or len(s) < 40:
        return ""
    if norm(s).startswith(norm(title)) and len(title) > 20:
        s = s[len(title):].lstrip(" .:-–—|")
    out, sents = "", SENT_RE.split(s)
    if any(NOT_STORY_RE.search(x) for x in sents[:3]):
        return ""      # the feed's text is a bio or an advert; the article page's own description is used instead
    for sent in sents:
        if out and len(out) + len(sent) > limit:
            break
        out = f"{out} {sent}".strip()
        if len(out) >= 170:
            break
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0] + "…"
    return out


def clean_url(u):
    p = urlsplit(u)
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "mc_"))]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), ""))


def url_key(u):
    p = urlsplit(u)
    return p.netloc.lower().removeprefix("www.") + (p.path.rstrip("/") or "/")


def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


WORD_RE = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")


def tokens(title):
    """Key words of a headline. Names with versions ("GPT-6.1", "M6", "iOS 27.2") stay one word."""
    t = re.sub(r"[\u2010-\u2015]", "-", (title or "").lower()).replace("’", "'")
    t = re.sub(r"'s\b", "", t)
    out, words = set(), WORD_RE.findall(t)
    plain = lambda w: w.isalpha() and w not in STOP and w not in GENERIC
    for n, w in enumerate(words):
        if any(ch.isdigit() for ch in w):           # a product and its version: "genie 4", "ios 27.2", "gpt-6.1 terra"
            if n and plain(words[n - 1]):
                out.add(f"{words[n - 1]} {w}")
            if n + 1 < len(words) and plain(words[n + 1]) and len(words[n + 1]) > 2:
                out.add(f"{w} {words[n + 1]}")
        if w in STOP or w in GENERIC or (len(w) < 3 and not any(ch.isdigit() for ch in w)):
            continue
        out.add(stem(w))
    return out


def stem(w):
    """Crude stemming so "expands", "expanding" and "expanded" match."""
    if any(ch.isdigit() for ch in w) or len(w) <= 4:
        return w
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4 and not w.endswith("ss"):
            return w[: -len(suf)]
    return w


def image_of(e):
    for key in ("media_thumbnail", "media_content"):
        for m in e.get(key) or []:
            if m.get("url") and (key == "media_thumbnail" or "image" in (m.get("type") or "image") or m.get("medium") == "image"):
                return m["url"]
    for l in e.get("links") or []:
        if l.get("rel") == "enclosure" and (l.get("type") or "").startswith("image"):
            return l.get("href")
    for blob in [e.get("summary", "")] + [c.get("value", "") for c in e.get("content") or []]:
        m = IMG_RE.search(blob or "")
        if m and not m.group(1).startswith("data:"):
            return html.unescape(m.group(1))
    return None


def when(e):
    st = e.get("published_parsed") or e.get("updated_parsed")
    return datetime(*st[:6], tzinfo=timezone.utc) if st else None


def get_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read(1_500_000).decode(r.headers.get_content_charset() or "utf-8", "replace")


META_RE = re.compile(r"<meta\s[^>]*>", re.I)
ATTR_RE = re.compile(r'([a-z:_-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')', re.I)
P_RE = re.compile(r"""<p(?:\s(?:"[^"]*"|'[^']*'|[^'">])*)?>(.*?)</p>""", re.I | re.S)


def page_meta(url):
    """Title, date, picture, description and opening paragraphs read from an article page."""
    h = get_html(url)
    meta = {}
    for tag in META_RE.findall(h):
        a = {m[0].lower(): (m[2] or m[3]) for m in ATTR_RE.findall(tag)}
        k = a.get("property") or a.get("name") or a.get("itemprop")
        if k and "content" in a:
            meta.setdefault(k.lower(), html.unescape(a["content"]))
    date = meta.get("article:published_time") or meta.get("datepublished") or meta.get("date")
    if not date:
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', h)
        date = m.group(1) if m else None
    title = meta.get("og:title") or meta.get("twitter:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", h, re.I | re.S)
        title = clean_text(m.group(1)) if m else None
    body = re.sub(r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", h, flags=re.I | re.S)
    paras = [re.sub(r"^Skip to (main )?content\s*", "", clean_text(p), flags=re.I) for p in P_RE.findall(body)]
    paras = [p for p in paras if len(p) > 80 and re.search(r"[.!?]", p) and not re.search(r"cookie|subscribe|sign up|newsletter|©|all rights reserved", p, re.I)]
    return {"t": title, "d": date, "img": meta.get("og:image"),
            "desc": meta.get("og:description") or meta.get("description") or "",
            "lead": " ".join(paras[:2])[:900]}


def parse_date(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class Pages:
    """Article pages opened at most once and remembered between runs."""

    def __init__(self):
        self.data = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
        self.budget = PAGE_FETCHES_PER_RUN

    def get(self, url):
        hit = self.data.get(url)
        if hit is not None:
            return hit
        if self.budget <= 0:
            return None
        self.budget -= 1
        try:
            m = page_meta(url)
        except Exception as ex:  # noqa: BLE001 - one bad page must not stop the run
            m = {"err": str(ex)[:120]}
        m["seen"] = datetime.now(timezone.utc).date().isoformat()
        self.data[url] = m
        return m

    def save(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS)).date().isoformat()
        keep = {u: m for u, m in self.data.items() if m.get("seen", "") >= cutoff}
        CACHE_FILE.write_text(json.dumps(keep, ensure_ascii=False, separators=(",", ":")))


DATE_PART_RE = re.compile(r"^(january|february|march|april|may|june|july|august|september|october|november|december)?\s*(q[1-4][\s-]*)?\d{4}$", re.I)
NOT_A_REPORT = {"policy recommendations", "executive summary", "introduction", "overview", "data and assumptions"}


def report_title(title):
    """'Executive summary - Global Hydrogen Review 2026' is a page of 'Global Hydrogen Review 2026'."""
    parts = [p.strip() for p in title.split(" - ") if p.strip()]
    if len(parts) > 1 and not DATE_PART_RE.match(parts[-1]):
        parts = parts[-1:]
    title = " - ".join(parts)
    return None if title.lower() in NOT_A_REPORT else title


def slugify(title):
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def item_from_entry(e, feed, dt):
    body = e.get("summary") or ""
    content = " ".join(c.get("value", "") for c in e.get("content") or [])
    words = len(TAG_RE.sub(" ", content or body).split())
    title = clean_text(e.title)
    if feed.get("type") == "gnews":
        src = (e.get("source") or {}).get("title")
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        body = content = ""
        if feed.get("link"):
            title = report_title(title)
            if not title:
                return None
    it = {"t": title[:220], "u": clean_url(e.link) if feed.get("type") != "gnews" else feed["link"].format(slug=slugify(title)) if feed.get("link") else e.link, "s": feed["name"],
          "d": dt.isoformat(timespec="minutes"), "x": summarize(content or body, title) or summarize(body, title),
          "img": image_of(e)}
    if words > 150:
        it["min"] = max(1, round(words / 230))
    return it


def fetch_feed(cat, feed):
    url = feed.get("url")
    if feed.get("type") == "gnews":
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": feed["query"], "hl": "en-US", "gl": "US", "ceid": "US:en"})
    d = feedparser.parse(url, agent=UA)
    status = getattr(d, "status", None)
    if not d.entries or (status and status >= 400):
        return [], f"no items (HTTP {status}) {d.get('bozo_exception', '')}"[:200]
    cutoff = datetime.now(timezone.utc) - timedelta(days=feed.get("maxAgeDays", cat.get("maxAgeDays", DEFAULT_MAX_AGE_DAYS)))
    items = []
    for e in sorted(d.entries, key=lambda e: when(e) or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        dt = when(e)
        if not dt or dt < cutoff or not e.get("link") or not e.get("title"):
            continue
        it = item_from_entry(e, feed, dt)
        if not it or any(i["u"] == it["u"] for i in items):
            continue
        items.append(it)
        if len(items) >= PER_FEED:
            break
    return items, None if items else "no recent items"


def fetch_html(cat, feed, pages):
    """A listing page without a feed: open each linked article once and read it."""
    base = feed["url"]
    links = []
    for href in re.findall(r'href="([^"#?]+)"', get_html(base)):
        path = urlsplit(href).path
        if re.fullmatch(feed["match"], path) and not re.search(feed.get("skip", r"^$"), path):
            u = urllib.parse.urljoin(base, path)
            if u not in links:
                links.append(u)
    cutoff = datetime.now(timezone.utc) - timedelta(days=feed.get("maxAgeDays", cat.get("maxAgeDays", DEFAULT_MAX_AGE_DAYS)))
    items = []
    for u in links[:40]:
        m = pages.get(u)
        dt = parse_date(m.get("d")) if m else None
        if not m or not dt or dt < cutoff or not m.get("t"):
            continue
        title = re.sub(r"\s+[|–-]\s+Anthropic$", "", m["t"]).strip()
        generic = m.get("desc", "").startswith(feed.get("genericDesc", "\0"))
        items.append({"t": title, "u": clean_url(u), "s": feed["name"], "d": dt.isoformat(timespec="minutes"),
                      "x": summarize(m.get("lead") if generic or not m.get("desc") else m["desc"], title)
                      or summarize(m.get("lead", ""), title),
                      "img": m.get("img")})
    items.sort(key=lambda i: i["d"], reverse=True)
    return items[:PER_FEED], None if items else "no recent items"


def fetch(job, pages):
    cat, feed = job
    try:
        if feed.get("type") == "html":
            return fetch_html(cat, feed, pages)
        return fetch_feed(cat, feed)
    except Exception as ex:  # noqa: BLE001
        return [], str(ex)[:200]


# ---------- grouping the same story from several sources ----------

def same_story(a, b, idf, rare):
    """Two headlines share most of their key words, weighting rare words (names) above common ones."""
    shared = a["tok"] & b["tok"]
    if len(shared) < 2 or not any(idf[w] >= rare for w in shared):
        return False
    weight = lambda ws: sum(idf.get(w, 0) for w in ws)
    ratio = weight(shared) / min(weight(a["tok"]), weight(b["tok"]))
    named = any(" " in w and idf[w] >= rare for w in shared)     # both name the same product version
    if ratio >= 0.6 or (named and ratio >= 0.35):
        return True
    # A short headline whose key words almost all appear in the other source's headline and summary.
    if ratio >= 0.3 and len(shared) >= 3:
        for x, y in ((a, b), (b, a)):
            if weight(x["tok"] & (y["tok"] | y["xtok"])) / weight(x["tok"]) >= 0.75:
                return True
    return False


def group_stories(items):
    """Headlines become one story if they share the link, or if they are published within 72 h and match
    the story's first headline or at least two of its headlines (so one loose match can't chain stories together)."""
    df = {}
    for it in items:
        it["tok"] = tokens(it["t"])
        # Digests and podcasts cover many topics, so their summaries can't tie them to one story.
        it["xtok"] = set() if DIGEST_RE.search(it["t"]) else tokens(it.get("x") or "")
        it["ts"] = datetime.fromisoformat(it["d"]).timestamp()
        it["key"] = url_key(it["u"])
        for w in it["tok"]:
            df[w] = df.get(w, 0) + 1
    n = max(len(items), 1)
    idf = {w: math.log(n / c) for w, c in df.items()}
    rare = math.log(n / 8)                 # a word in at most ~8 headlines: a name, a product, a place
    groups, by_url = [], {}
    for it in sorted(items, key=lambda i: i["ts"]):
        g = by_url.get(it["key"])
        if g is None:
            best = 0
            for cand in groups:
                if it["ts"] - cand[0]["ts"] > SAME_STORY_HOURS * 3600:
                    continue
                hits = sum(1 for m in cand if same_story(it, m, idf, rare))
                if (hits >= 2 or (hits and same_story(it, cand[0], idf, rare))) and hits > best:
                    g, best = cand, hits
        if g is None:
            g = []
            groups.append(g)
        g.append(it)
        by_url.setdefault(it["key"], g)
    # Second pass: join stories that were started separately but match each other.
    merged = True
    while merged:
        merged = False
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                ga, gb = groups[a], groups[b]
                if not ga or not gb or abs(ga[0]["ts"] - gb[0]["ts"]) > SAME_STORY_HOURS * 3600:
                    continue
                hits = sum(1 for x in ga for y in gb if same_story(x, y, idf, rare))
                if hits >= 2 or (hits and same_story(ga[0], gb[0], idf, rare)):
                    ga.extend(gb)
                    gb.clear()
                    merged = True
    return [g for g in groups if g]


NEW_MODEL_NAMES = []   # filled from OpenRouter, e.g. "gpt-6.1 terra", "kimi k3.1"


def is_model_release(t):
    low = t.lower()
    named = any(n in low for n in NEW_MODEL_NAMES)
    return bool(RELEASE_RE.search(t) and (MODEL_RE.search(t) or named)) or (named and len(low) < 60)


def make_story(members, now, priority):
    # Lead: the company's own post if there is one, else the source with the best summary.
    members.sort(key=lambda m: (not m["off"], -m["w"], -len(m["x"] or ""), m["ts"]))
    lead = members[0]
    sources, seen = [], set()
    for m in members:
        if m["s"] not in seen:
            seen.add(m["s"])
            sources.append(m)
    # Sites that give only a date (no time) are counted from midday.
    newest = max(m["ts"] + (43200 if m["d"].endswith("T00:00+00:00") else 0) for m in members)
    age_h = max(0.0, (now - newest) / 3600)
    coverage = sum(max(m["w"] for m in members if m["s"] == s) for s in seen)
    score = (coverage + (1.5 if lead["off"] else 0)) * 0.5 ** (age_h / 30)
    if PROMO_RE.search(lead["t"]) and len(seen) == 1:
        score *= 0.4
    cats = {}
    for m in members:
        cats[m["cat"]] = cats.get(m["cat"], 0) + 1
    if any(is_model_release(m["t"]) for m in members) and any(m["cat"] in ("ai", "models", "giants") for m in members):
        home = "models"
    elif lead["off"]:
        home = lead["cat"]
    else:
        home = min(cats, key=lambda c: (-cats[c], priority.index(c)))
    best_x = next((m["x"] for m in members if m["off"] and m["x"]), "") or max((m["x"] or "" for m in members), key=len)
    st = {k: lead[k] for k in ("t", "u", "s", "d", "img", "min", "v") if lead.get(k)}
    st["x"] = best_x
    st["img"] = lead.get("img") or next((m["img"] for m in members if m.get("img")), None)
    st["also"] = [{"s": m["s"], "u": m["u"], "t": m["t"]} for m in sources[1:8]]
    st["n"] = len(sources)
    st["sc"] = round(score, 3)
    if lead["off"]:
        st["off"] = True
    return st, home, {m["cat"] for m in members}


def fill_summaries(stories, pages):
    """Stories in the brief with no usable summary: read the opening of the article itself."""
    for st in stories:
        if len(st.get("x") or "") >= 80 or "news.google.com" in st["u"]:
            continue
        for u in [st["u"]] + [a["u"] for a in st.get("also", [])]:
            if "news.google.com" in u:
                continue
            m = pages.get(u)
            if m and not m.get("err"):
                s = summarize(m.get("desc") or "", st["t"])
                if len(s) < 80:
                    s = summarize(m.get("lead") or "", st["t"]) or s
                if s:
                    st["x"] = s
                    st["img"] = st.get("img") or m.get("img")
                    break


TREND_SKIP = set("ai app apps company companies people million billion data model models tech new system systems user users pro max plus mini ultra lite".split())


def trending_terms(stories, n=12):
    """Words in the most headlines today, counting each source once per story."""
    count = {}
    for st in stories:
        words = {w for w in re.findall(r"[A-Za-z][A-Za-z0-9.+-]{2,}", st["t"])
                 if w.lower() not in STOP and w.lower() not in GENERIC and w.lower() not in TREND_SKIP}
        for w in words:
            key = w.rstrip(".").lower()
            c = count.setdefault(key, {"w": w.rstrip("."), "n": 0, "caps": 0})
            c["n"] += st["n"]
            c["caps"] += w[0].isupper()
    terms = [c for c in count.values() if c["n"] >= 3 and c["caps"] * 2 >= c["n"] / 2]
    terms.sort(key=lambda c: -c["n"])
    return [[c["w"], c["n"]] for c in terms[:n]]


# ---------- Model Watch ----------

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def first_sentence(s, limit=220):
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", WS_RE.sub(" ", s or ""))
    s = re.sub(r"[*_`#]+", "", s).strip()
    s = SENT_RE.split(s)[0] if s else ""
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "…"


def fetch_models():
    out, problems = {"new": [], "trending": []}, []
    try:
        data = get_json("https://openrouter.ai/api/v1/models")["data"]
        cutoff = (datetime.now(timezone.utc) - timedelta(days=MODEL_DAYS)).timestamp()
        seen = {}
        for m in sorted(data, key=lambda m: m["created"]):
            if m["created"] < cutoff:
                continue
            base = m["id"].split(":")[0]
            free = m["id"].endswith(":free") or float(m["pricing"].get("prompt") or 0) == 0
            if base in seen:          # :free / :batch variants of a model already listed
                seen[base]["free"] = seen[base]["free"] or free
                continue
            p_in = float(m["pricing"].get("prompt") or 0) * 1e6
            p_out = float(m["pricing"].get("completion") or 0) * 1e6
            name = re.sub(r"\s*\((free|beta|preview)\)$", "", m["name"].split(": ", 1)[-1], flags=re.I)
            seen[base] = {
                "name": name, "by": m["name"].split(": ", 1)[0] if ": " in m["name"] else base.split("/")[0],
                "id": base, "d": datetime.fromtimestamp(m["created"], timezone.utc).date().isoformat(),
                "ctx": m.get("context_length"), "in": round(p_in, 3), "out": round(p_out, 3), "free": free,
                "reasoning": "reasoning" in (m.get("supported_parameters") or []),
                "open": bool(m.get("hugging_face_id")), "hf": m.get("hugging_face_id") or None,
                "mod": (m.get("architecture") or {}).get("input_modalities") or [],
                "x": first_sentence(m.get("description")),
                "u": f"https://openrouter.ai/{base}",
            }
        out["new"] = sorted(seen.values(), key=lambda m: m["d"], reverse=True)
    except Exception as ex:  # noqa: BLE001
        problems.append({"category": "Model Watch", "source": "OpenRouter models", "error": str(ex)[:200]})
    try:
        hf = get_json("https://huggingface.co/api/models?sort=trendingScore&limit=30")
        out["trending"] = [{"id": m["id"], "by": m["id"].split("/")[0], "name": m["id"].split("/")[-1],
                            "task": m.get("pipeline_tag"), "likes": m.get("likes"), "dl": m.get("downloads"),
                            "d": (m.get("createdAt") or "")[:10], "u": f"https://huggingface.co/{m['id']}"}
                           for m in hf]
    except Exception as ex:  # noqa: BLE001
        problems.append({"category": "Model Watch", "source": "Hugging Face trending", "error": str(ex)[:200]})
    return out, problems


def main():
    cfg = json.loads((ROOT / "feeds.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(exist_ok=True)
    pages = Pages()
    priority = [c["id"] for c in cfg["categories"]]
    jobs = [(c, f) for c in cfg["categories"] for f in c["feeds"]]
    rss = [j for j in jobs if j[1].get("type") != "html"]
    scraped = [j for j in jobs if j[1].get("type") == "html"]
    with ThreadPoolExecutor(16) as ex:
        results = list(ex.map(lambda j: (j, fetch(j, pages)), rss))
    results += [(j, fetch(j, pages)) for j in scraped]    # one at a time: polite to the site

    # A source that fails this hour keeps its items from its last good run (still subject to the age limit).
    last_good = json.loads(LAST_GOOD_FILE.read_text()) if LAST_GOOD_FILE.exists() else {}
    for n, ((cat, feed), (its, err)) in enumerate(results):
        key = f"{cat['id']}|{feed['name']}"
        if its:
            last_good[key] = its
        elif last_good.get(key):
            cutoff = (datetime.now(timezone.utc) - timedelta(days=feed.get("maxAgeDays", cat.get("maxAgeDays", DEFAULT_MAX_AGE_DAYS)))).isoformat()
            kept = [i for i in last_good[key] if i["d"] >= cutoff]
            results[n] = ((cat, feed), (kept, f"{err} (showing {len(kept)} from the last good run)" if kept else err))
    LAST_GOOD_FILE.write_text(json.dumps(last_good, ensure_ascii=False, separators=(",", ":")))
    models, model_problems = fetch_models()
    NEW_MODEL_NAMES.extend(n for n in {m["name"].lower() for m in models["new"]} if len(n) >= 6)

    now = datetime.now(timezone.utc)
    index = {"updated": now.isoformat(timespec="minutes"), "categories": [], "problems": []}
    news_items, sources = [], {c["id"]: [] for c in cfg["categories"]}
    for (cat, feed), (its, err) in results:
        if err:
            index["problems"].append({"category": cat["name"], "source": feed["name"], "error": err})
        sources[cat["id"]].append({"name": feed["name"], "count": len(its)})
        for it in its:
            it["cat"], it["w"] = cat["id"], feed.get("weight", 1.0)
            it["off"] = bool(feed.get("official", cat.get("official", False)))
            news_items.append(it)

    # One story per event, across every category.
    stories = []
    for members in group_stories(news_items):
        st, home, cats = make_story(members, now.timestamp(), priority)
        stories.append((st, home, cats))
    stories.sort(key=lambda s: s[0]["d"], reverse=True)

    # The brief: the 3 highest-ranked stories first, then the top 3 of each category, never a story twice.
    used, brief = set(), []
    ranked = sorted(stories, key=lambda s: -s[0]["sc"])
    top = [s for s in ranked if s[0]["n"] >= 2][:BRIEF_PER_SECTION]
    used.update(s[0]["u"] for s in top)
    brief.append({"id": "top", "name": "Top stories", "stories": [s[0] for s in top]})
    for c in cfg["categories"]:
        pick = [s[0] for s in ranked if s[1] == c["id"] and s[0]["u"] not in used][:BRIEF_PER_SECTION]
        used.update(s["u"] for s in pick)
        brief.append({"id": c["id"], "name": c["name"], "stories": pick})
    fill_summaries([s for b in brief for s in b["stories"]], pages)

    for c in cfg["categories"]:
        items = [st for st, home, cats in stories if c["id"] in cats or home == c["id"]]
        if c["id"] == "models":          # Model Watch has its own file, written below
            model_news = items
            index["categories"].append({"id": c["id"], "name": c["name"], "count": len(items), "sources": sources[c["id"]]})
            continue
        (OUT / f"{c['id']}.json").write_text(json.dumps({"items": items}, ensure_ascii=False, separators=(",", ":")))
        index["categories"].append({"id": c["id"], "name": c["name"], "count": len(items), "sources": sources[c["id"]]})

    problems = model_problems
    models["news"] = model_news
    (OUT / "models.json").write_text(json.dumps(models, ensure_ascii=False, separators=(",", ":")))
    index["problems"] += problems
    index["brief"] = brief
    index["models"] = {"new": models["new"][:5], "count": len(models["new"])}
    index["trending"] = trending_terms([s[0] for s in stories if now.timestamp() - datetime.fromisoformat(s[0]["d"]).timestamp() < 86400 * 2])
    index["storyCount"] = len(stories)
    index["itemCount"] = len(news_items)
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    pages.save()

    print(f"{len(news_items)} headlines -> {len(stories)} stories; {len(models['new'])} new models")
    for b in brief:
        print(f"\n== {b['name']}")
        for s in b["stories"]:
            print(f"  [{s['n']} src, {s['sc']:.2f}] {s['t'][:90]}  ({s['s']})")
    for p in index["problems"]:
        print("PROBLEM", p)


if __name__ == "__main__":
    main()
