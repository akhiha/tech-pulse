# Tech Pulse

A personal reader for tech news, videos and research papers, sorted by category.
It is a plain website (no app store). GitHub Actions refreshes it on its own:
news and videos every hour, papers once a day.

## What's where

| File | What it is |
|---|---|
| `feeds.json` | News and video sources, by category. Add or remove a feed here. |
| `papers.json` | Conferences, journals and arXiv topic searches. |
| `scripts/fetch_news.py` | Downloads the feeds into `site/data/news/`. |
| `scripts/fetch_papers.py` | Downloads papers into `site/data/papers/`. |
| `site/` | The website itself (`index.html`, `app.js`, `style.css`). |
| `.github/workflows/update.yml` | The hourly job that fetches and publishes. |
| `Tech-Pulse-Sources.xlsx` | Every source, for choosing what to keep. |

## Run it on your Mac

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt certifi
export SSL_CERT_FILE=$(.venv/bin/python -m certifi)
.venv/bin/python scripts/fetch_news.py
.venv/bin/python scripts/fetch_papers.py
cd site && python3 -m http.server 8931
```

Then open http://127.0.0.1:8931.

## Put it online (free)

1. Create a **public** repository on GitHub and push this folder to it.
2. In the repository: **Settings → Pages → Source: GitHub Actions**.
3. **Actions → Update and publish → Run workflow** for the first run.
   The site appears at `https://<your-username>.github.io/<repo-name>/`.
4. Optional: get a free OpenAlex key at https://openalex.org/settings/api and add it under
   **Settings → Secrets and variables → Actions** as `OPENALEX_API_KEY`
   (stops journal fetching from sharing a rate limit with other GitHub users).

GitHub pauses scheduled jobs in a repository with no activity for 60 days.
If updates ever stop, open **Actions** and press **Enable workflow**.

## On iPhone

Open the site in Safari → Share → **Add to Home Screen**. It opens full-screen like an app.
Saved items and reading settings stay on that device.

## How conference papers are found

Most authors post accepted papers on arXiv with a note such as "Accepted at ICSE 2027".
The fetcher searches those notes for each conference (this year and next), skipping
"under review" or "submitted to". Papers show up weeks before the conference.
Papers that never go on arXiv are missed, so every conference page also links to its
official program.
