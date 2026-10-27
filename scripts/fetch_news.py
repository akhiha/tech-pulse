"""Fetch every feed in feeds.json and write site/data/news/<category>.json + site/data/news/index.json.

Run hourly by GitHub Actions. A feed that fails is skipped and reported; the run never fails because of one feed.
"""
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import feedparser

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "news"
UA = "Mozilla/5.0 (compatible; TechPulse/1.0; personal news reader)"
PER_FEED = 25
DEFAULT_MAX_AGE_DAYS = 14

TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
WS_RE = re.compile(r"\s+")


def clean_text(s, limit=300):
    s = WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", s or ""))).strip()
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0] + "…"
    return s


def clean_url(u):
    p = urlsplit(u)
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "mc_"))]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), ""))


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


def fetch(cat, feed):
    t0 = time.time()
    d = feedparser.parse(feed["url"], agent=UA)
    status = getattr(d, "status", None)
    if not d.entries or (status and status >= 400):
        return feed, [], f"no items (HTTP {status}) {d.get('bozo_exception', '')}"[:200]
    cutoff = datetime.now(timezone.utc) - timedelta(days=cat.get("maxAgeDays", DEFAULT_MAX_AGE_DAYS))
    items = []
    for e in d.entries:
        dt = when(e)
        if not dt or dt < cutoff or not e.get("link") or not e.get("title"):
            continue
        body = e.get("summary") or ""
        if not body and e.get("content"):
            body = e["content"][0].get("value", "")
        full_words = len(TAG_RE.sub(" ", " ".join(c.get("value", "") for c in e.get("content") or []) or body).split())
        it = {
            "t": clean_text(e.title, 220),
            "u": clean_url(e.link),
            "s": feed["name"],
            "d": dt.isoformat(timespec="minutes"),
            "x": clean_text(body),
            "img": image_of(e),
        }
        if e.get("yt_videoid"):
            it["v"] = e.yt_videoid
            it["img"] = f"https://i.ytimg.com/vi/{e.yt_videoid}/mqdefault.jpg"
            it["x"] = clean_text(e.get("media_description") or body, 200)
        elif full_words > 150:
            it["min"] = max(1, round(full_words / 230))
        items.append(it)
        if len(items) >= PER_FEED:
            break
    return feed, items, None if items else "no recent items"


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def main():
    cfg = json.loads((ROOT / "feeds.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(c, f) for c in cfg["categories"] for f in c["feeds"]]
    with ThreadPoolExecutor(16) as ex:
        results = list(ex.map(lambda j: (j[0], *fetch(*j)), jobs))

    index = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "categories": [], "problems": []}
    for cat in cfg["categories"]:
        seen_u, seen_t, items, sources = set(), set(), [], []
        for c, feed, its, err in results:
            if c is not cat:
                continue
            if err:
                index["problems"].append({"category": cat["name"], "source": feed["name"], "error": err})
            sources.append({"name": feed["name"], "count": len(its)})
            for it in its:
                k = norm_title(it["t"])
                if it["u"] in seen_u or k in seen_t:
                    continue
                seen_u.add(it["u"]); seen_t.add(k)
                items.append(it)
        items.sort(key=lambda i: i["d"], reverse=True)
        (OUT / f"{cat['id']}.json").write_text(json.dumps({"items": items}, ensure_ascii=False, separators=(",", ":")))
        index["categories"].append({
            "id": cat["id"], "name": cat["name"], "count": len(items),
            "sources": sources, "top": items[:3],
        })
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    for c in index["categories"]:
        print(f"{c['name']:22} {c['count']:5} items")
    for p in index["problems"]:
        print("PROBLEM", p)


if __name__ == "__main__":
    main()
