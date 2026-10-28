"""Fetch research papers into site/data/papers/.

Three sources, all from papers.json:
  conferences: arXiv papers whose author comment says they were accepted at <VENUE> <YEAR>
               (next year back to YEARS_BACK years ago), so they show up as soon as authors post them.
               Past years change little, so they are fetched again only once a week.
  journals:    articles of the last YEARS_BACK+1 years from OpenAlex by ISSN, with abstracts. Where the publisher
               doesn't share the abstract, it is taken from the paper's arXiv preprint
               (matched by title; lookups are cached in abstract_cache.json).
  topics:      arXiv keyword searches for the newest papers on a research topic.

Run daily by GitHub Actions. arXiv asks for one request every 3 seconds; we keep to that.
Set OPENALEX_API_KEY to use your own free OpenAlex key (recommended on shared CI machines).
"""
import difflib
import json
import os
import re
import socket
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "papers"
UA = "TechPulse/1.0 (personal research reader)"
ARXIV = "https://export.arxiv.org/api/query?"
PAGE = 1000
MAX_PER_VENUE_YEAR = 6000
YEARS_BACK = 2             # conferences from 2 years ago (3 years with this one); journals from 3 years ago to today
PAST_YEAR_REFRESH_DAYS = 7
LOOKUPS_PER_RUN = 250      # arXiv title lookups per run (3 s each); the rest wait for tomorrow
RETRY_MISS_DAYS = 14       # a preprint may appear later, so look again after this
TITLE_MATCH = 0.93         # how alike two titles must be to count as the same paper
socket.setdefaulttimeout(90)

NOT_ACCEPTED = re.compile(r"under review|submitted to|in submission|under submission|submission to|preprint submitted|to be submitted", re.I)
WS = re.compile(r"\s+")
_last_arxiv = [0.0]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def arxiv(query, start=0, n=PAGE, sort="submittedDate"):
    wait = 3.1 - (time.time() - _last_arxiv[0])
    if wait > 0:
        time.sleep(wait)
    url = ARXIV + urllib.parse.urlencode({
        "search_query": query, "start": start, "max_results": n,
        "sortBy": sort, "sortOrder": "descending"})
    for attempt in range(3):
        _last_arxiv[0] = time.time()
        d = feedparser.parse(url, agent=UA)
        if d.entries or getattr(d, "status", 200) == 200 and "opensearch_totalresults" in d.feed:
            return d
        time.sleep((20 if getattr(d, "status", 200) == 429 else 5) * (attempt + 1))
    raise RuntimeError(f"arXiv gave no answer (HTTP {getattr(d, 'status', '?')})")


def authors(names):
    names = [WS.sub(" ", n).strip() for n in names if n]
    return {"a": names[:6], "na": len(names)}


def arxiv_item(e):
    pdf = next((l.href for l in e.get("links", []) if l.get("type") == "application/pdf"), None)
    st = e.get("published_parsed")
    return {
        "t": WS.sub(" ", e.title).strip(),
        **authors([a.get("name") for a in e.get("authors", [])]),
        "d": datetime(*st[:3]).date().isoformat() if st else None,
        "abs": WS.sub(" ", e.get("summary", "")).strip(),
        "u": e.get("id", "").replace("http://", "https://"),
        "pdf": pdf.replace("http://", "https://") if pdf else None,
        "cm": WS.sub(" ", e.get("arxiv_comment", "")).strip()[:200],
    }


def kind_of(comment):
    c = comment.lower()
    if "workshop" in c:
        return "Workshop"
    if "findings" in c:
        return "Findings"
    if re.search(r"\b(demo|tool|industry|doctoral|nier|new ideas|short paper|poster|companion|student)", c):
        return "Other track"
    return "Main"


def fetch_conference(v, year):
    q = f'co:"{v["id"]} {year}"'
    items, start, total = [], 0, None
    while start < MAX_PER_VENUE_YEAR:
        d = arxiv(q, start)
        total = int(d.feed.get("opensearch_totalresults", 0) or 0)
        for e in d.entries:
            it = arxiv_item(e)
            # The phrase must really be in the comment, and the paper must not be just "under review".
            if not re.search(rf"\b{re.escape(v['id'])}\W{{0,3}}{year}\b", it["cm"], re.I) or NOT_ACCEPTED.search(it["cm"]):
                continue
            it["k"] = kind_of(it["cm"])
            items.append(it)
        start += PAGE
        if not d.entries or start >= total:
            break
    return items


def openalex(params):
    key = os.environ.get("OPENALEX_API_KEY")
    if key:
        params["api_key"] = key
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return json.load(urllib.request.urlopen(req, timeout=90))
        except Exception as ex:  # noqa: BLE001 - retry any network/HTTP error
            err = ex
            time.sleep(5 * (attempt + 1))
    raise err


def abstract_from_index(inv):
    if not inv:
        return ""
    pos = {}
    for word, idx in inv.items():
        for i in idx:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def fetch_journal(j, since):
    """Every article published on or after `since`, newest first."""
    works, page = [], 1
    while True:      # page= paging (cursor paging needs an API key)
        data = openalex({
            "filter": f"primary_location.source.issn:{j['issn']},type:article,from_publication_date:{since}",
            "sort": "publication_date:desc", "per_page": 100, "page": page,
            "select": "title,publication_date,doi,authorships,abstract_inverted_index,open_access,id",
        })
        works += data.get("results", [])
        if not data.get("results") or len(works) >= (data.get("meta") or {}).get("count", 0) or page >= 50:
            break
        page += 1
    items = []
    for w in works:
        if not w.get("title"):
            continue
        items.append({
            "t": WS.sub(" ", re.sub(r"<[^>]+>", "", w["title"])).strip(),
            **authors([a["author"]["display_name"] for a in w.get("authorships", [])]),
            "d": w.get("publication_date"),
            "abs": abstract_from_index(w.get("abstract_inverted_index")),
            "u": w.get("doi") or w.get("id"),
            "pdf": (w.get("open_access") or {}).get("oa_url"),
        })
    return items


STOPWORDS = set("a an the of for and in on to with by from at via is are its as or using based towards toward".split())


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def fill_from_arxiv(items, cache, budget):
    """Give items without an abstract the abstract of their arXiv preprint. Returns lookups used."""
    today = datetime.now(timezone.utc).date()
    used = 0
    for it in items:
        if it["abs"]:
            continue
        key = it["u"]
        hit = cache.get(key)
        if hit and "abs" in hit:
            it.update(abs=hit["abs"], absSrc="arXiv preprint", arxiv=hit["u"])
            it["pdf"] = it["pdf"] or hit.get("pdf")
            continue
        if hit and (today - datetime.fromisoformat(hit["miss"]).date()).days < RETRY_MISS_DAYS:
            continue
        if used >= budget:
            continue
        # Search on the title's main words (not the exact phrase), so punctuation and
        # capitalisation differences between preprint and journal titles don't matter.
        words = [w for w in norm_title(it["t"]).split() if w not in STOPWORDS and len(w) > 2][:8]
        if len(words) < 3:
            continue
        used += 1
        d = arxiv(" AND ".join(f"ti:{w}" for w in words), 0, 5, sort="relevance")
        want = norm_title(it["t"])
        best = max(d.entries, key=lambda e: difflib.SequenceMatcher(None, want, norm_title(e.title)).ratio(), default=None)
        if best and difflib.SequenceMatcher(None, want, norm_title(best.title)).ratio() >= TITLE_MATCH:
            a = arxiv_item(best)
            cache[key] = {"abs": a["abs"], "u": a["u"], "pdf": a["pdf"]}
            it.update(abs=a["abs"], absSrc="arXiv preprint", arxiv=a["u"])
            it["pdf"] = it["pdf"] or a["pdf"]
        else:
            cache[key] = {"miss": today.isoformat()}
    return used


def fetch_topic(t):
    d = arxiv(t["query"], 0, 200)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
    return [it for it in map(arxiv_item, d.entries) if (it["d"] or "") >= cutoff]


def write(name, payload):
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def week_count(items):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    return sum(1 for i in items if (i.get("d") or "") >= cutoff)


def main():
    cfg = json.loads((ROOT / "papers.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    old = {}
    if (OUT / "index.json").exists():
        old = json.loads((OUT / "index.json").read_text())
    year = datetime.now(timezone.utc).year
    index = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
             "fields": cfg["fields"], "conferences": [], "journals": [], "topics": [], "problems": []}

    def keep_old(kind, key):
        for e in old.get(kind, []):
            if e["key"] == key:
                return e
        return None

    today = datetime.now(timezone.utc).date()
    for v in cfg["conferences"]:
        for y in range(year + 1, year - YEARS_BACK - 1, -1):
            key = f"{v['id']} {y}"
            prev = keep_old("conferences", key)
            if (y < year and prev and prev.get("fetched") and (OUT / prev["file"]).exists()
                    and (today - datetime.fromisoformat(prev["fetched"]).date()).days < PAST_YEAR_REFRESH_DAYS):
                prev["week"] = 0
                index["conferences"].append(prev)
                continue
            try:
                items = fetch_conference(v, y)
            except Exception as ex:  # noqa: BLE001
                index["problems"].append({"source": key, "error": str(ex)[:200]})
                if prev:
                    index["conferences"].append(prev)
                continue
            if not items:
                if prev and (OUT / prev["file"]).exists():
                    index["conferences"].append(prev)
                continue
            f = f"conf-{slug(v['id'])}-{y}.json"
            write(f, {"items": items})
            kinds = {}
            for i in items:
                kinds[i["k"]] = kinds.get(i["k"], 0) + 1
            index["conferences"].append({
                "key": key, "id": v["id"], "year": y, "field": v["field"], "name": v["name"],
                "official": v["official"].format(year=y), "file": f,
                "count": len(items), "week": week_count(items), "kinds": kinds,
                "latest": max((i["d"] or "") for i in items), "fetched": today.isoformat(),
            })
            print(f"{key:16} {len(items):5} accepted papers on arXiv")

    cache_file = OUT / "abstract_cache.json"
    abs_cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    budget = LOOKUPS_PER_RUN
    oldest = (today - timedelta(days=365 * (YEARS_BACK + 1))).isoformat()
    for j in cfg["journals"]:
        # The whole three years once a week; on other days only the last 60 days, added to what we have.
        prev = keep_old("journals", j["id"])
        prev_file = OUT / prev["file"] if prev else None
        full = not (prev and prev.get("fetched") and prev_file.exists()
                    and (today - datetime.fromisoformat(prev["fetched"]).date()).days < PAST_YEAR_REFRESH_DAYS)
        try:
            items = fetch_journal(j, oldest if full else (today - timedelta(days=60)).isoformat())
            if not full:
                have = {i["u"] for i in items}
                items += [i for i in json.loads(prev_file.read_text())["items"] if i["u"] not in have and (i["d"] or "") >= oldest]
                items.sort(key=lambda i: i["d"] or "", reverse=True)
        except Exception as ex:  # noqa: BLE001
            index["problems"].append({"source": j["id"], "error": str(ex)[:200]})
            if prev:
                index["journals"].append(prev)
            continue
        had = sum(1 for i in items if i["abs"])
        try:
            budget -= fill_from_arxiv(items, abs_cache, budget)
        except Exception as ex:  # noqa: BLE001 - keep the articles even if arXiv lookups fail
            index["problems"].append({"source": f"{j['id']} abstracts", "error": str(ex)[:200]})
        cache_file.write_text(json.dumps(abs_cache, ensure_ascii=False, separators=(",", ":")))
        f = f"journal-{slug(j['id'])}.json"
        write(f, {"items": items})
        index["journals"].append({"key": j["id"], "id": j["id"], "field": j["field"], "name": j["name"],
                                  "file": f, "count": len(items), "week": week_count(items),
                                  "latest": max(((i["d"] or "") for i in items), default=""),
                                  "fetched": today.isoformat() if full else prev["fetched"]})
        print(f"{j['id']:16} {len(items):5} newest articles, abstracts {had} from publisher"
              f" + {sum(1 for i in items if i.get('absSrc'))} from arXiv")

    for t in cfg["topics"]:
        try:
            items = fetch_topic(t)
        except Exception as ex:  # noqa: BLE001
            index["problems"].append({"source": t["name"], "error": str(ex)[:200]})
            continue
        f = f"topic-{slug(t['id'])}.json"
        write(f, {"items": items})
        index["topics"].append({"key": t["id"], "id": t["id"], "name": t["name"], "file": f,
                                "count": len(items), "week": week_count(items)})
        print(f"{t['name']:32} {len(items):5} papers, last 10 days")

    write("index.json", index)
    for p in index["problems"]:
        print("PROBLEM", p)


if __name__ == "__main__":
    main()
