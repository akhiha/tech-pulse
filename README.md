# Tech Pulse

A personal daily tech brief, built to be read in about 15 minutes, plus new AI models
and research papers. It is a plain website (no app store). GitHub Actions refreshes it on its own:
news and models every hour, papers once a day.

## How the brief is made (no AI needed)

1. **Collect.** Every source in `feeds.json` is read. Most have an RSS feed. Sites without one are
   scraped: Anthropic's listing pages are read and each new article is opened once for its title,
   date, picture and opening paragraphs (remembered in `.cache/`). The IEA blocks automated access,
   so its reports come through Google News, each linked straight to the report on iea.org.
2. **Group.** The same event reported by several sources becomes one story. Two headlines match
   when they share most of their key words, with rare words (names, products such as "GPT-6.1 Terra"
   or "iOS 27.2") counting for more than common ones, and were published within 72 hours.
   A big event is written about from many angles, so its headlines don't look alike: headlines
   naming the same company and the same kind of event (an IPO, an acquisition, a lawsuit, layoffs…)
   within four days join one **developing story** once three or more sources cover it.
3. **Rank.** A story scores higher the more sources cover it, if the company itself published it,
   and the more recent it is. Customer-story and sponsored posts rank lower.
4. **Pick.** The brief shows the 3 top stories overall, then the top 3 of each section. A story
   appears in one section only.
5. **Summarise.** Each summary is the article's own opening sentences (author bios, adverts and
   newsletter housekeeping are skipped). If the feed has nothing useful, the article page's own
   description is used.

The Today page also shows, on the side: the new models most written about, the models trending
on Hugging Face, and the GitHub projects gaining the most stars this week.

Model Watch adds every model added to OpenRouter in the last 30 days (price, context length,
reasoning, open weights) and the models trending on Hugging Face. Both are free public lists.

## What's where

| File | What it is |
|---|---|
| `feeds.json` | News and video sources, by category. Add or remove a feed here. |
| `papers.json` | Conferences, journals and arXiv topic searches (JMLR is read from jmlr.org, which OpenAlex no longer covers). |
| `scripts/fetch_news.py` | Reads every source, groups and ranks stories, writes `site/data/news/`. |
| `scripts/fetch_papers.py` | Downloads papers into `site/data/papers/`. |
| `site/` | The website itself (`index.html`, `app.js`, `style.css`). |
| `.github/workflows/update.yml` | The hourly job that fetches and publishes. |
| `Tech-Pulse-Sources.xlsx` | Every source, for choosing what to keep. |

## Run it on your Mac

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt certifi
export SSL_CERT_FILE=$(.venv/bin/python -m certifi)
.venv/bin/python scripts/fetch_news.py      # prints the brief it built
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
official program. Conferences cover the last three years (2024 on) plus next year; past years are re-checked weekly;
journals keep every article of the last three years.

Journal abstracts come from OpenAlex. Some publishers (often Elsevier and Springer) don't
share them; for those articles the fetcher looks for the paper's arXiv preprint by title
and uses its abstract, marked "Abstract from the arXiv preprint". Up to 250 lookups run per
day and results are remembered, so the backlog clears within a couple of days. Articles
with no preprint stay without an abstract and link to the publisher.

## About

Made by Akhila Matathammal, who was tired of checking a dozen sites and wading through AI slop to
stay up to date. The idea and the logic are Akhila's; the code was written with Claude Code.
Free to use however you like (MIT licence, see `LICENSE`).
