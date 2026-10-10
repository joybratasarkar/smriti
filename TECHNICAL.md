# Smriti: Technical Notes

How the system works today: how data comes in, how it is stored, how articles are grouped into issues, and how the timeline is built. For run commands and current status, see `PROGRESS.md`.

_Last updated: 2026-10-10. Covers Step 1, Step 2 and the read-only web app._

---

## 1. Pipeline overview

```
 feeds.txt (16 RSS feeds)
        │
        ▼
 app.fetch   ──►  articles               (links + metadata only, deduped by URL)
        │
        ▼
 app.embed   ──►  article_embeddings     (384-d multilingual vectors, pgvector)
        │
        ▼
 app.group   ──►  issues + article_issues (incremental clustering by cosine similarity)
        │
        ▼
 app.api (FastAPI, :8010)  ──►  frontend (Svelte 5 + Vite, :5173)
                                 issue list + per-issue timeline
```

Each stage is a separate command. Each one picks up only new work and is safe to re-run. The order is always **fetch → embed → group**.

---

## 2. Data sources (Step 1)

### Options compared

| Source | Verdict |
|---|---|
| **NewsAPI** | The free tier is for development only (no production use), returns only 24h-delayed articles, and has limited Indian coverage. Rejected. |
| **GNews** | The free tier is small (around 100 requests/day) and non-commercial. Rejected as the main source. |
| **GDELT DOC 2.0 API** | Free, multilingual, and supports `sourcecountry:IN`. Implemented, but in testing (Oct 2026) it returned persistent HTTP 429s even with 60–90 s gaps between requests, and accepted requests came back empty. It is **opt-in only** (`--gdelt`). |
| **RSS feeds** | Free, reliable, published directly by the outlets, and include a snippet. **This is the default source.** |

### RSS feeds in use (`feeds.txt`, format `Name | URL`)

There are 16 feed URLs from 15 distinct sources (Times of India has two feeds).

- **India:** The Hindu, The Indian Express, NDTV, Hindustan Times, Times of India (×2), The Economic Times, Mint, India Today, News18, Scroll, BBC News India, BBC Hindi
- **International:** BBC News World, Al Jazeera, The Guardian World

To add a source, add a line to `feeds.txt`. No code change is needed.

### Fetch behaviour (`app/fetch.py`)

- **Window:** keeps articles published in the last 7 days (`--days N`). Older RSS entries are skipped and counted in the log.
- **HTTP:** uses `httpx` with a 30 s timeout, follows redirects, and sends a custom User-Agent.
- **Retries:** up to 3 attempts on network errors, 429 and 5xx, with exponential backoff (4 s, 8 s, 16 s). It honours `Retry-After` up to 120 s. Other 4xx responses are not retried.
- **Failure handling:** a failed or unparseable feed is logged and skipped; the run never crashes. Logs go to the console and `logs/fetch.log`.
- **URL normalization:** lowercases the scheme and host, drops `#fragment`, and removes `utm_*`, `fbclid`, `gclid`, `mc_cid`, `mc_eid`, `ref` and `ref_src`.
- **Text cleaning:** strips HTML tags and entities and collapses whitespace. Snippets are capped at 500 characters, cut at a word boundary.
- **Dates:** uses `published_parsed`, falling back to `updated_parsed`. Stored in UTC.
- **Language:** taken from the entry or feed language tag and reduced to ISO 639-1 (`en-US` → `en`).
- **Dedupe:** `INSERT … ON CONFLICT (url) DO NOTHING`, so re-running never creates duplicates. RSS runs before GDELT, so when both sources have the same URL, the RSS row (which has a snippet) wins.
- **GDELT details (when enabled):** query `sourcecountry:IN`, `mode=artlist`, 1-hour windows, max 250 records per window (GDELT's cap; capped windows are logged as possibly incomplete), 60 s pause between windows. It resumes from the newest GDELT article already stored. Language names are mapped to ISO codes.
- **Copyright:** **no full article text is stored**, only links and metadata.

---

## 3. Database schema (`schema.sql`)

The database is PostgreSQL 16 on port 5433, database `smriti`, with the `pgvector` extension. Everything is plain tables, including the future graph (nodes and edges as relation tables). The schema is idempotent (`CREATE … IF NOT EXISTS`) and is applied by every script on startup through `app.db.init_schema()`.

### `articles`: one row per news article (Step 1)

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `url` | TEXT UNIQUE NOT NULL | Normalized URL; the dedupe key |
| `title` | TEXT NOT NULL | Cleaned headline |
| `snippet` | TEXT | RSS description, ≤500 chars; NULL for GDELT |
| `source_name` | TEXT NOT NULL | e.g. "The Hindu" |
| `source_domain` | TEXT NOT NULL | e.g. `thehindu.com` (no `www.`) |
| `language` | TEXT | ISO 639-1 where known |
| `published_at` | TIMESTAMPTZ | Publisher's date (RSS) or first-seen time (GDELT) |
| `fetched_at` | TIMESTAMPTZ NOT NULL | Defaults to `now()` |
| `content_hash` | TEXT NOT NULL | sha256 of lowercased title + snippet, for spotting the same text at different URLs |
| `provider` | TEXT NOT NULL | `rss` or `gdelt` |

Indexes: `published_at`, `content_hash`.

### `article_embeddings`: one vector per article (Step 2)

| Column | Type | Notes |
|---|---|---|
| `article_id` | BIGINT PK → `articles(id)` ON DELETE CASCADE | |
| `model` | TEXT NOT NULL | Model name, so we can re-embed if the model changes |
| `embedding` | `vector(384)` NOT NULL | L2-normalized |
| `created_at` | TIMESTAMPTZ | |

### `issues`: a group of related articles (Step 2)

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | Stable: never renumbered unless `--reset` |
| `label` | TEXT NOT NULL | Headline of the member article closest to the centroid |
| `centroid` | `vector(384)` NOT NULL | Mean of member embeddings |
| `article_count` | INT | |
| `first_seen` / `last_seen` | TIMESTAMPTZ | Earliest and latest member article date |
| `created_at` | TIMESTAMPTZ | |

Index: `last_seen`.

### `article_issues`: relation table, article → issue (Step 2)

| Column | Type | Notes |
|---|---|---|
| `article_id` | BIGINT PK → `articles(id)` | PK means each article belongs to exactly one issue |
| `issue_id` | BIGINT → `issues(id)` ON DELETE CASCADE | Indexed |
| `similarity` | REAL | Cosine similarity to the issue when assigned (1.0 if it founded the issue) |
| `assigned_at` | TIMESTAMPTZ | |

### Entity relationships

```
articles 1 ── 1 article_embeddings
articles 1 ── 1 article_issues N ── 1 issues
```

The planned Step 3/4 tables (events, people, organizations, places, and the edges between them) do not exist yet.

---

## 4. Embeddings (`app/embed.py`)

- **Library:** `fastembed`, which runs ONNX on CPU. No GPU or PyTorch is needed.
- **Model:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions. It was chosen because it is **multilingual**: a Hindi and an English headline about the same event land close together, which matters for BBC Hindi and future Indian-language feeds. The model downloads on first run.
- **Input text:** `"{title}. {snippet}"`, or just the title when there is no snippet. Full text is not available, by design.
- **Normalization:** vectors are L2-normalized, so a dot product equals cosine similarity.
- **Incremental:** only embeds articles with no embedding, or whose stored `model` differs from the current one. Changing `MODEL` triggers a full re-embed automatically.
- **Batching:** 256 articles per batch, committed per batch.

---

## 5. Grouping into issues (`app/group.py`)

The algorithm is **incremental single-pass clustering** (a leader/centroid approach), chosen over batch clustering (k-means, HDBSCAN) so that issue IDs stay stable as new news arrives.

1. Load all embedded articles that don't have an issue yet, sorted **oldest first** by `coalesce(published_at, fetched_at)`.
2. For each article, look only at issues **active in the 14 days before it** (`last_seen ≥ article_time − 14 days`).
3. Compute cosine similarity to each candidate issue's centroid.
4. If the best similarity is **≥ 0.70**, join that issue: update the centroid as a running mean, increment the count, and extend `first_seen` and `last_seen`.
5. Otherwise, **start a new issue** with this article as the seed.
6. Save the results. Each changed issue is **relabelled** with the member headline nearest its centroid (pgvector `<=>` operator).

Properties:
- An assigned article **never moves**, so issue URLs and IDs are stable.
- `--threshold` tunes how strict grouping is. `--reset` truncates issues and regroups from scratch.
- The `assign()` function is pure in-memory logic, so thresholds can be tested without touching the database.

**Known limitation:** at 0.70 the groups are **event-level** ("trains cancelled for protest"), not issue-level ("the farmers' protest"). Result: 795 issues for 1,053 articles, of which only 98 have more than one article. Merging related events into one issue is the open problem.

---

## 6. API (`app/api.py`)

The API is FastAPI, read-only, and returns JSON. Run it with `uvicorn app.api:app --reload --port 8010`. Each request opens a connection with `psycopg` and uses the `dict_row` row factory. Interactive docs are at `http://localhost:8010/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /api/summary` | Header stats: article, issue and multi-article issue counts, source count, oldest and newest publish date, last fetch time |
| `GET /api/issues` | Issue list. Params: `sort` = `recent` (by `last_seen`) or `biggest` (by `article_count`); `min_size` (default 2, hides single-article issues); `q` (case-insensitive search over **member article titles**); `limit` (1–200, default 50); `offset`. Returns `{total, issues[]}`, where each issue has `id, label, article_count, first_seen, last_seen, source_count, sources[]` |
| `GET /api/issues/{id}` | One issue plus all its articles (`id, title, url, snippet, source_name, language, published_at, similarity`), ordered oldest first. Returns 404 if the issue is missing |

`published_at` in the detail endpoint falls back to `fetched_at` when the feed gave no date.

---

## 7. Frontend and timeline (`frontend/`)

The frontend uses Svelte 5 (runes: `$state`, `$derived`, `$effect`) and Vite 6, with no router library or UI framework. The dev server runs on :5173 and proxies `/api` to :8010 (`vite.config.js`, port configurable with `API_PORT`).

### Routing (`App.svelte`)

A minimal hash router: `#/` shows the issue list, and `#/issues/42` shows one issue. The header shows the `/api/summary` stats.

### Issue list (`IssueList.svelte`)

- Search box (debounced 250 ms), **Latest** / **Most covered** toggle, and a "single-article stories" checkbox (switches `min_size` between 1 and 2).
- Pages of 30 with a "Show more" button.
- Each card shows the label, article count, source count, date range, sources, and an **active / quiet** badge.

### How the timeline is built (`IssueDetail.svelte` + `lib/format.js`)

1. Fetch `/api/issues/{id}`. The articles are already sorted oldest → newest by the API.
2. **Group by calendar day in Indian time** (`Asia/Kolkata`). `dayKey()` formats each timestamp as `YYYY-MM-DD` in IST, so a story published at 23:30 UTC lands on the correct Indian date.
3. Render an ordered list of days. Under each day, every article shows its **time (IST)**, a **headline linked to the original source** (opens in a new tab), the snippet, and the source name. Every entry is traceable to its source article.
4. The `lang` attribute is set from the article language, so Hindi text renders and is read correctly.

### Issue status

- An issue is **quiet** if there has been no new article for **48 hours** (`QUIET_AFTER_HOURS` in `lib/format.js`). Quiet issues show *"No reports found since \<date, time\> (N days ago)"*.
- Otherwise the issue is **active**: *"Still being reported · latest article N h ago"*.
- All dates and times are displayed in IST (`en-IN` locale).

---

## 8. Configuration and environment

- **`.env`:** `DATABASE_URL=postgresql://smriti:<password>@localhost:5433/smriti`. It is gitignored; the template is `.env.example`. No API keys are needed yet, because RSS and GDELT require none.
- **Python dependencies** (`requirements.txt`, pinned): `httpx`, `feedparser`, `psycopg[binary]`, `python-dotenv`, `fastembed`, `numpy`, `pgvector`, `fastapi`, `uvicorn`. Installed in `.venv/`.
- **Frontend dependencies:** `svelte` 5.57, `vite` 6.4, `@sveltejs/vite-plugin-svelte` 5.1.
- **Postgres quirks:** this cluster is on 5433; the PG15 cluster on 5432 belongs to SonarQube. Create databases from `template0` (glibc collation mismatch). The `vector` extension was created once as superuser.
- **Logs:** `logs/fetch.log`, `logs/api.log`, `logs/frontend.log`.

---

## 9. Not built yet (planned)

- **Event-level → issue-level merging:** the open problem from Step 2.
- **Step 3 (Understand, LLM):** extract structured events from each article: who, what, when, action type, exact quote, and source URL.
- **Step 4 (Remember, graph in Postgres):** Issue → Events → People / Organizations / Places, with every event linked to its source articles. Store attributed facts, not conclusions.
- **Scheduling:** fetch, embed and group are run by hand for now.
- **Remote backup:** the git repo is local only; no GitHub remote yet.
