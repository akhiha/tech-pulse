"""Test every feed in feeds.json: does it load, how fresh is it, how often does it post."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser

UA = "Mozilla/5.0 (tech-pulse feed checker)"


def check(cat, feed):
    t0 = time.time()
    d = feedparser.parse(feed["url"], agent=UA, request_headers={"Accept": "*/*"})
    status = getattr(d, "status", None)
    dates = []
    for e in d.entries:
        st = e.get("published_parsed") or e.get("updated_parsed")
        if st:
            dates.append(datetime(*st[:6], tzinfo=timezone.utc))
    now = datetime.now(timezone.utc)
    latest = max(dates) if dates else None
    week = sum(1 for x in dates if (now - x).days < 7)
    ok = bool(d.entries) and (status is None or status < 400)
    return {
        "category": cat["name"], "name": feed["name"], "url": feed["url"],
        "ok": ok, "http": status, "entries": len(d.entries),
        "latest": latest.isoformat() if latest else None, "last7d": week,
        "error": "" if ok else str(d.get("bozo_exception", "") or f"HTTP {status}, 0 items")[:120],
        "secs": round(time.time() - t0, 1),
    }


cfg = json.load(open("feeds.json"))
jobs = [(c, f) for c in cfg["categories"] for f in c["feeds"]]
with ThreadPoolExecutor(16) as ex:
    rows = list(ex.map(lambda j: check(*j), jobs))
json.dump(rows, open("feed_check.json", "w"), indent=1)
for r in rows:
    print(("OK " if r["ok"] else "BAD"), r["category"][:12].ljust(12), r["name"][:30].ljust(30), r["entries"], r["last7d"], r["latest"] and r["latest"][:10], r["error"])
