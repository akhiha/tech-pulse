"""Test every source in feeds.json: does it load, how fresh is it, how often does it post.
Uses the site's own fetcher, so scraped pages and Google News sources are checked the same way."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import sys
import urllib.parse

sys.path.insert(0, "scripts")
import fetch_news  # noqa: E402

PAGES = fetch_news.Pages()


def check(cat, feed):
    t0 = time.time()
    url = feed.get("url") or "https://news.google.com/search?q=" + urllib.parse.quote(feed["query"])
    try:
        if feed.get("type") == "html":
            items, err = fetch_news.fetch_html(cat, feed, PAGES)
        else:
            items, err = fetch_news.fetch_feed({**cat, "maxAgeDays": 3650}, {**feed, "maxAgeDays": 3650})
    except Exception as ex:  # noqa: BLE001
        items, err = [], str(ex)
    now = datetime.now(timezone.utc)
    dates = [datetime.fromisoformat(i["d"]) for i in items]
    ok = bool(items)
    return {
        "category": cat["name"], "name": feed["name"], "url": url,
        "ok": ok, "http": None, "entries": len(items),
        "latest": max(dates).isoformat() if dates else None, "last7d": sum(1 for x in dates if (now - x).days < 7),
        "error": "" if ok else (err or "no items")[:120],
        "secs": round(time.time() - t0, 1),
    }


cfg = json.load(open("feeds.json"))
jobs = [(c, f) for c in cfg["categories"] for f in c["feeds"]]
with ThreadPoolExecutor(16) as ex:
    rows = list(ex.map(lambda j: check(*j), jobs))
json.dump(rows, open("feed_check.json", "w"), indent=1)
for r in rows:
    print(("OK " if r["ok"] else "BAD"), r["category"][:12].ljust(12), r["name"][:30].ljust(30), r["entries"], r["last7d"], r["latest"] and r["latest"][:10], r["error"])
