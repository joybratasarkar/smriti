# Smriti: Technical Notes

How the system works today: how data comes in, how it is stored, how articles are grouped into issues, and how the timeline is built. For run commands and current status, see [`PROGRESS.md`](../PROGRESS.md); for open problems, [`ISSUES.md`](ISSUES.md); for why, [`DECISIONS.md`](DECISIONS.md).

_Last updated: 2026-10-26. Covers Step 1, Step 2 and the read-only web app._

---

## 1. Pipeline overview

```
 feeds.txt (RSS feeds) + optional GDELT
        │
        ▼
 app.fetch       ──►  articles               (links + metadata only, deduped by URL)
        │
        ▼
 app.embed       ──►  article_embeddings     (bge-m3, 1024-d, pgvector)
        │
        ▼
 app.group       ──►  issues + article_issues (towers find candidates; the fine-tuned
        │                                      cross-encoder decides "same story?")
        ▼
 app.categories  ──►  story categories       (classifier on bge-m3 vectors)
 app.links       ──►  issue_links            (edges between related stories)
 app.front       ──►  story_titles           (LLM titles for the front page)
        │
        ▼
 app.api (FastAPI, :8010)  ──►  frontend (Svelte 5 + Vite, :5173)
                                 front page, story list, story page with a timeline
```

Each stage is a separate command. Each one picks up only new work and is safe to re-run. The order is **fetch → embed → group → categories → links → front titles**. `app.group` needs the fine-tuned model from `app.teach` + `app.train` (section 5a).

---

## 2. Data sources (Step 1)

### Options compared

| Source | Verdict |
|---|---|
| **NewsAPI** | The free tier is for development only (no production use), returns only 24h-delayed articles, and has limited Indian coverage. Rejected. |
| **GNews** | The free tier is small (around 100 requests/day) and non-commercial. Rejected as the main source. |
| **GDELT DOC 2.0 API** | Free, multilingual, and supports `sourcecountry:IN`, but it answers HTTP 429 even to the first request (Oct 2026). Dropped. |
| **GDELT GKG bulk files** | One file every 15 minutes, no rate limit, includes page titles and goes back years. About 4 MB per file (~24 GB for 60 days), English only, no snippet. Used for **backfill, opt-in** (`--gdelt`, D-026). |
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
- **GDELT details (when enabled):** downloads `https://data.gdeltproject.org/gdeltv2/<YYYYMMDDHHMMSS>.gkg.csv.zip` for every 15 minutes from the cutoff to 30 minutes ago, and keeps rows whose URL domain is in `GDELT_DOMAINS` (the Indian outlets we also read by RSS). Title from `<PAGE_TITLE>`, date = GDELT's first-seen time, language `en`, snippet NULL. Files already read are listed in `gdelt_files` and skipped, so reruns and longer `--days` only download what is missing; failed files are retried next run. One log line per day.
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

### `gdelt_files`: GDELT files already read (Step 1 backfill)

| Column | Type | Notes |
|---|---|---|
| `stamp` | TIMESTAMPTZ PK | The file's 15-minute timestamp (UTC) |
| `articles` | INT NOT NULL | Rows kept from our outlets |
| `fetched_at` | TIMESTAMPTZ NOT NULL | When it was read |

### `article_embeddings`: one vector per article (Step 2)

| Column | Type | Notes |
|---|---|---|
| `article_id` | BIGINT PK → `articles(id)` ON DELETE CASCADE | |
| `model` | TEXT NOT NULL | Model name, so we can re-embed if the model changes |
| `embedding` | `vector(1024)` NOT NULL | bge-m3, L2-normalized. Was MiniLM `vector(384)` until D-024; `schema.sql` drops the old vectors and issues once |
| `created_at` | TIMESTAMPTZ | |

### `issues`: a group of related articles (Step 2)

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | Stable: never renumbered unless `--reset` |
| `label` | TEXT NOT NULL | Headline of the member article closest to the centroid |
| `centroid` | `vector(1024)` NOT NULL | Mean of member embeddings |
| `article_count` | INT | |
| `first_seen` / `last_seen` | TIMESTAMPTZ | Earliest and latest member article date |
| `category`, `region` | TEXT | One of the 9 categories and `India` / `World` (D-036, `app/categories.py`); NULL until it runs |
| `category_by` | TEXT | `llm` (front-page stories) or `classifier` |
| `created_at` | TIMESTAMPTZ | |

Index: `last_seen`.

### `article_issues`: relation table, article → issue (Step 2)

| Column | Type | Notes |
|---|---|---|
| `article_id` | BIGINT PK → `articles(id)` | PK means each article belongs to exactly one issue |
| `issue_id` | BIGINT → `issues(id)` ON DELETE CASCADE | Indexed |
| `similarity` | REAL | Tower (bge-m3) cosine to the issue when assigned (1.0 if it founded the issue) |
| `probability` | REAL | Cross-encoder P(same story) that made it join; NULL when the towers decided alone (new story or near-duplicate) |
| `model` | TEXT | The cross-encoder that decided; NULL when none did |
| `assigned_at` | TIMESTAMPTZ | |

### `issue_links`: weighted edges between stories (G-6, `app/links.py`)

| Column | Type | Notes |
|---|---|---|
| `from_issue`, `to_issue` | BIGINT FK → `issues(id)` ON DELETE CASCADE | PK together; `from_issue` is the older story. Index on `to_issue` |
| `weight` | REAL NOT NULL | Cross-encoder probability that the two stories are connected |
| `link_type` | TEXT NOT NULL | `related` until the LLM names it: `same_story`, `follow_up`, `same_actor`, `same_topic`, `unrelated` |
| `evidence` | TEXT | The LLM's one-line reason |
| `model`, `typed_by` | TEXT | Cross-encoder that weighed it; LLM that named it |
| `created_at` | TIMESTAMPTZ | |

### `gold_pairs`: hand-labelled article pairs (G-2, `app/gold.py`)

Used only to measure grouping models, never to train them.

| Column | Type | Notes |
|---|---|---|
| `article_a`, `article_b` | BIGINT FK | `article_a < article_b`, unique pair |
| `stratum` | TEXT | `nearest` (an article and its most similar article within 3 days, cosine 0.4–0.95), then bge-m3 cosine bands `high` (0.6–0.95), `middle` (0.4–0.6), `low` (< 0.4 but sharing a rare title word, in ≤ 0.5% of titles), `name` (0.4–0.95 and sharing a rare capitalised title word, mostly a name, I-023); articles ≤ 30 days apart. Gold set: 50 of each of the first four, 50 `name` (2026-10-25) |
| `cosine` | REAL | Tower (bge-m3) cosine when sampled |
| `label` | TEXT | `same_story`, `follow_up`, `same_actor`, `same_topic`, `unrelated`, `unsure` (unsure is left out of scoring); NULL until labelled |
| `labeled_at`, `created_at` | TIMESTAMPTZ | |

The labelling tool hides the cosine and stratum, shows pairs in shuffled order, and asks for the first label that fits.

### `train_pairs`: LLM-labelled article pairs (G-4, `app/teach.py`)

Same columns as `gold_pairs` plus `labeled_by` (the LLM); labels without `unsure`. A pair is never in both tables.

### `moment_labels`: short labels for the dots on a story's path (D-030, `app/moments.py`)

`moment_key` (md5 of the moment's sorted article ids, primary key), `issue_id`, `label` (4 to 7 words), `model`, `created_at`. Moments themselves are not stored; a label stops applying when its moment's articles change.

### `story_titles`: clean titles for front-page stories (D-032, `app/front.py`)

`moment_key` (md5 of the story's **newest** moment's sorted article ids, primary key), `title` (5 to 9 words), `model`, `created_at`. A story gets a new title only when it gets a new newest dot. No foreign key to `issues` on purpose: `app.group --reset` truncates `issues` (D-033).

### `article_categories`: LLM category labels for sampled articles (D-036, `app/categories.py`)

`article_id` (PK → `articles(id)` ON DELETE CASCADE), `category`, `region` (`India` / `World`), `model`, `created_at`. Keyed by article, so the labels survive a regroup; they train the story classifier.

### Entity relationships

```
articles 1 ── 1 article_embeddings
articles 1 ── 1 article_issues N ── 1 issues
issues 1 ── N issue_links N ── 1 issues        (the story graph)
issues 1 ── N moment_labels                    (labels for the timeline path)
```

The planned Step 3/4 tables (events, people, organizations, places, and the edges between them) do not exist yet.

---

## 4. Embeddings, the "towers" (`app/embed.py`)

- **Model:** `BAAI/bge-m3` through `transformers` on the GPU in float16 (shared code in `app/models.py`), 1024 dimensions, CLS pooling. Multilingual, so a Hindi and an English headline about the same event land close together. Replaced MiniLM (fastembed, 384-dim) with D-024.
- **Input text:** `"{title}. {snippet}"`, or just the title when there is no snippet (all GDELT rows). Full text is not available, by design.
- **Normalization:** vectors are L2-normalized, so a dot product equals cosine similarity.
- **Incremental:** only embeds articles with no embedding, or whose stored `model` differs from the current one. Committed every 1,024 articles.

---

## 5. Grouping into stories (`app/group.py`)

**Incremental single-pass clustering**, so issue IDs stay stable as news arrives, with a two-stage decision (D-024):

1. Load unassigned embedded articles, **oldest first**, 2,000 at a time (progress is committed per chunk, so a crash loses little). Left out: blank titles (I-017), second copies of an article, meaning the same site and `content_hash` within a day (I-019), and headlines with Devanagari letters (English only for now, D-038). Hindi headlines grouped before D-038 are taken out of their stories at the start of every run (`leave_out_hindi`); stories left empty are deleted.
2. **Towers:** cosine between the article vector and the centroid of every story active in the **30 days** before it, on the GPU. The 3 best with cosine **≥ 0.40** are candidates. No candidate: new story.
3. **Near-duplicate:** best cosine **≥ 0.92** joins directly, without the cross-encoder.
4. **Fine-tuned cross-encoder** (`models/ce-same-story`, from `app/train.py`): reads the article against each of the candidate's 3 member headlines **closest to the article**, one pair at a time as in training, and takes the **mean** as P(same story) (D-034, 2026-10-25; before, the 3 were joined into one text, which let one shared name carry a new event in, I-023; until 2026-10-24 the latest 3, which split events, I-016). Member vectors are kept in memory as float16. Best **≥ 0.5** joins (stored in `article_issues.probability`); otherwise a new story. About 0.1 s per article for 3 candidates on the GTX 1650 with joined text; up to 9 pairs per article since D-034. Below near-duplicate it decides every case, because look-alikes are often different stories (daily horoscopes, two El Niño articles; D-028).
5. Each changed multi-article story is **relabelled** with the member headline nearest its centroid (pgvector `<=>`).
6. **Merge pass** (D-031), after every run: stories with ≥ 2 articles whose centres have cosine **≥ 0.88** and are at most 30 days apart are compared on their **3 closest article pairs**. When the cross-encoder gives every pair ≥ 0.5, they merge into the oldest story (union-find over the passing pairs), which gets a new centroid (pgvector `avg`), counts, dates and label. The deleted stories' links and moment labels go with them. Dry run on the 2026-10-20 stories: 633 pairs checked, 354 passed, 298 stories merged (Nepal floods 10 → 1, US–Iran war 10 → 1).

Full run (2026-10-20, `--reset`): 138,229 articles in 4 h 44 min, 8 a second. 72,591 stories; the cross-encoder decided 62,339 joins, and 3,299 near-duplicates joined directly.

The cut-offs are provisional (D-027, D-028) until the gold set measures them (G-3). `app.group` stops with an error if the fine-tuned model is missing. `--reset` deletes all issues and links and regroups from scratch. The LLM referee for uncertain cases (D-024) is not in the bulk run: at ~1 s per call it would take hours.

## 5a. Fine-tuning the cross-encoder (`app/teach.py`, `app/train.py`)

Teacher-student (D-028):
1. **Teacher** (`python -m app.teach --sample 3000 --label`): pairs are drawn like the gold set (40% nearest, 10% high, 40% middle, 10% low) into `train_pairs`, never a gold pair. The local LLM labels each with the gold-set rules plus the `HARD_CASES` rules (D-035; label only, ~1 s per pair). `--names N` adds N `name` pairs (1000 on 2026-10-25). On 2026-10-25 all 4000 pairs were relabelled with the hard-case rules; the old labels are in `train_pairs_before_d035`. Teacher on the gold set, label-only: 91.5% before the rules, 94.5% after (199 pairs); 87.8% on the 49 `name` pairs.
2. **Student** (`python -m app.train`): `bge-reranker-v2-m3`, target 1 if the teacher said `same_story`. Both orders of each pair. Top 4 transformer layers and the head are trained (the rest frozen), float32, batch 8, 128 tokens, AdamW 2e-5, 2 epochs; this fits next to the 2.3 GB model in 4 GB. Pairs with `id % 10 == 0` are held out; AUC and accuracy against the teacher are logged before and after. It is saved to `models/ce-same-story/` (gitignored, with `smriti.json` holding those numbers) only if the held-out AUC improved.

## 5b. Story links, the graph edges (`app/links.py`)

1. **Weigh** (`python -m app.links`): for each story with **≥ 2 articles**, the 5 other such stories with the closest centroid (cosine **≥ 0.5**) and at most **30 days** apart in time are candidates. The cross-encoder reads both stories' latest 3 headlines; its probability is the **weight**. Links with weight **≥ 0.2** are stored as `related`, older story first. A `related` link that drops below 0.2 on a rerun is deleted; named links are kept.
2. **Name** (`python -m app.links --types N`): the LLM judge (`app/judge.py`, same label rules as the gold set) labels the N strongest unnamed links and gives a one-line reason, stored as `evidence`. Each story is described to it by its label, date range and article count.

Full run (2026-10-20): 62,039 candidate pairs weighed in 73 min (14 a second), 10,390 kept. Naming the 500 strongest took 16 min (about 2 s each).

Rerun both after `app.group`. `app.group --reset` deletes all links (new issue IDs).

## 5c. Key moments, the dots on a story's path (`app/moments.py`, D-030)

1. **Cut** (on every `GET /api/issues/{id}`, about 0.2 s for 224 articles): the story's articles become one moment per day (Indian time); the two neighbouring moments with the highest score merge until at most **7** remain. Score = cosine of their mean bge-m3 vectors − 0.02 per quiet day between them − 0.5 × their share of the story, + 0.15 when one holds under 4% of it. A gap-only rule failed: news comes almost every day. Stories with fewer than **4** articles get no path (`mode: "list"`).
2. **Headlines:** each moment's distinct headlines, most central first; copies of one headline are folded into its `outlets`.
3. **Label** (`python -m app.moments --label N`, the N biggest stories): the LLM writes 4 to 7 plain words from the moment's 6 most central headlines. Every capitalised word and number must appear in those headlines (commas in numbers ignored), and the LLM as referee (`moments.supported`, I-022) must find a headline that backs what the label claims, or no label is stored and the page shows the trimmed central headline. Front-page titles get the same two checks; an empty or unreadable LLM answer is treated the same (I-024). A rerun keeps labels already stored. Last run (2026-10-25, 300 stories): 1,882 written, 185 failed the check.

## 5d. The front page, "Today's stories" (`app/front.py`, D-032)

1. **Rank** (on every `GET /api/front`, about 0.5 s): stories with articles published in the 48 hours before the last fetch, ranked by distinct outlets (sites) in that window, then by reports in it. Stories with fewer than **4** articles are left out.
2. **Category and region:** `issues.category` and `issues.region` from `app.categories` (section 5e); the tabs are the 9 categories, with an All / India / World switch. A story not yet labelled shows as Society · India. Tabs with fewer than 3 stories are hidden.
3. **Left out:** stories where most articles are in a repeating column or paid content (`/astrology/`, `/brandhub/`, `/trending/` in the first 3 path parts, `front.JUNK_SECTIONS`) or have headlines matching `front.JUNK_TITLE` (horoscope, "gold rate today", wishes ...). `#/all` still lists them.
4. **Card** (D-037): category · region, **New** when the story began inside the window; title from `story_titles`, else the trimmed central headline; "Latest:" = the newest moment's label, else its trimmed headline; outlets and time since the last report; the moments' sizes for the lead card's mini dot-path.
5. **Titles** (`python -m app.front --titles N`, the N top stories): the LLM writes 5 to 9 words from the story's 6 most central headlines, with the dot labels' two checks (section 5c), and labels the newest moment if it has no label. First run 2026-10-25: 54 of 60 titles passed, one of those was false and was deleted (I-022); the referee's recheck on 2026-10-26 removed 4 of 53.

## 5e. News categories (`app/categories.py`, D-036)

Teacher and student, as for grouping. Run after every `app.group`.
1. **Teacher** (`python -m app.categories --label N`): the local LLM labels N more articles, one per story, with a category and India / World, first saying in a few words what the article is about (74/80 against Claude's labels). Stored in `article_categories`.
2. **Student** (`python -m app.categories`): a softmax regression on the labelled articles' bge-m3 vectors (5-fold agreement with the LLM logged) labels every story's centroid in seconds (`category_by = 'classifier'`). 71% agreement, Sports almost never predicted (I-025).
3. **Front-page stories** (`--stories`): the LLM labels each front-page story from its main headlines (`category_by = 'llm'`), overriding the classifier.

---

## 6. API (`app/api.py`)

The API is FastAPI, read-only, and returns JSON. Run it with `uvicorn app.api:app --reload --port 8010`. Each request opens a connection with `psycopg` and uses the `dict_row` row factory. Interactive docs are at `http://localhost:8010/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /api/front` | The front page (section 5d). Params: `topic` = `Top` or a category; `region` = `All`, `India` or `World`; `limit` (0–50, default 13; 0 returns only the tabs and `checked`, for the top bar); `offset`. Returns `{checked, since, tabs[{name, count}], total, stories[]}`, each story with `id, category, region, outlets, recent, reports, first_seen, last_seen, title, title_ai, new, latest, latest_ai, dots[]` (article count per moment) |
| `GET /api/summary` | Header stats: article, issue and multi-article issue counts, source count (news sites), oldest and newest publish date, last fetch time |
| `GET /api/issues` | Issue list. Params: `sort` = `recent` (by `last_seen`) or `biggest` (by `article_count`); `min_size` (default 2, hides single-article issues); `q` (case-insensitive search over **member article titles**); `limit` (1–200, default 50); `offset`. Returns `{total, issues[]}`, where each issue has `id, label, article_count, first_seen, last_seen, source_count, sources[]` |
| `GET /api/issues/{id}` | One issue plus all its articles (`id, title, url, snippet, source_name, language, published_at, similarity, probability`), ordered oldest first; `links`: up to 20 connected stories (`id, label, article_count, first_seen, last_seen, link_type, weight, evidence`), strongest first, `unrelated` hidden; `mode` (`path` or `list`) and `moments` (`start, end, count, label, labelled, heads[{title, time, outlets[{name, url}]}], more`, section 5c); `checked`: the last fetch time. Returns 404 if the issue is missing |

`published_at` in the detail endpoint falls back to `fetched_at` when the feed gave no date. Source names are shown one per site (I-020): a GDELT row, whose `source_name` is its site, gets the feed's name for that site (`moments.outlet_names`, read once per server start).

---

## 7. Frontend and timeline (`frontend/`)

The frontend uses Svelte 5 (runes: `$state`, `$derived`, `$effect`) and Vite 6, with no router library or UI framework. The dev server runs on :5173 and proxies `/api` to :8010 (`vite.config.js`, port configurable with `API_PORT`).

### Routing (`App.svelte`)

A minimal hash router: `#/` is the front page, `#/topic/Sports` one category tab, `#/topic/Sports/India` that tab in one region (`#/topic/Top/World`: every category), `#/all` every story, `#/search/<words>` the search results (the list with that search), and `#/issues/42` one story. The top bar (D-032) has the name (logo "S", D-038), the topic tabs from `/api/front?limit=0`, a search box that goes to `#/search/…`, and "checked HH:MM", which turns amber ("news may be out of date · last checked 20 Oct") when the last fetch is more than 24 hours old.

### Front page (`FrontPage.svelte`, `StoryCard.svelte`)

An All / India / World switch, one lead card (bigger title and the mini dot-path), then a grid of 12 cards (3 columns, 2 under 900 px, 1 under 600 px) and "Show 12 more". Cards follow D-037 (section 5d). The mini dot-path has no labels: dots evenly spaced, size by the moment's share, the newest in the accent colour, then a pulsing green "now". The whole card links to the story page.

### Issue list, "All stories" (`IssueList.svelte`)

- Search box (debounced 250 ms), **Latest** / **Most covered** toggle, and a "single-article stories" checkbox (switches `min_size` between 1 and 2).
- Pages of 30 with a "Show more" button.
- Each card shows the label, article count, source count, date range, sources, and an **active / quiet** badge ("active · latest 20 Oct", "quiet since 9 Sept").

### The story page: a path of key moments (`IssueDetail.svelte`, `StoryPath.svelte`, D-030)

1. Fetch `/api/issues/{id}`; the API has already cut the story into moments (section 5c).
2. **The path** (`StoryPath.svelte`): one dot per moment, sized by its reports, with its date range, label and report count, on a road drawn through the dot centres after layout (an SVG behind the HTML, redrawn by a `ResizeObserver`). Left to right with a wave when the box is 640 px or wider, winding downward when narrower. The last stop is **NOW** (the latest report, pulsing unless reduced motion is set). Linked stories (the 6 strongest) are purple side dots under the moment closest to their first report, named in plain words ("same event", "similar news") and opening that story's page. Arrow keys move between dots.
3. **One dot open at a time**, under the path; the page opens on NOW ("Where it stands now": the latest report and when the news was last checked). A moment shows its 4 most central headlines (all on request), each linking to the article, with copies folded into "+N more copies".
4. **All reports, day by day:** the full list, folded at the bottom (open by default for stories with no path), grouped by calendar day in Indian time (`dayKey()`), with time, linked headline, snippet and outlet. Hindi gets its `lang` attribute.

### Issue status

- Measured against the **last fetch**, not today (I-021): an issue is **quiet** when its last article is more than **48 hours** older than the last fetch (`QUIET_AFTER_HOURS` and `isQuiet()` in `lib/format.js`). It shows *"No new reports since \<date, time\> · news checked up to \<date\>"*; an active one shows *"Still being reported · latest report \<date, time\> · news checked up to \<date\>"*.
- All dates and times are displayed in IST (`en-IN` locale).

---

## 8. Configuration and environment

- **`.env`:** `DATABASE_URL=postgresql://smriti:<password>@localhost:5433/smriti`. It is gitignored; the template is `.env.example`. No API keys are needed yet, because RSS and GDELT require none.
- **Python dependencies** (`requirements.txt`, pinned): `httpx`, `feedparser`, `psycopg[binary]`, `python-dotenv`, `fastembed` (only the old MiniLM baseline in `app/compare.py`), `numpy`, `pgvector`, `fastapi`, `uvicorn`, `trafilatura` (full text for the LLM test, in memory only), `torch` and `transformers` (bge-m3 and the cross-encoder). Installed in `.venv/`.
- **Frontend dependencies:** `svelte` 5.57, `vite` 6.4, `@sveltejs/vite-plugin-svelte` 5.1.
- **Postgres quirks:** the developer's machine runs this database on port 5433 because another Postgres uses 5432; set your own port in `DATABASE_URL`. Create databases from `template0` (glibc collation mismatch). The `vector` extension was created once as superuser.
- **Logs:** `logs/fetch.log`, `logs/api.log`, `logs/frontend.log`.

---

## 9. Grouping model comparison (G-3, `app/compare.py`)

Scores every labelled gold pair (`gold_pairs`, unsure left out) with each candidate, zero-shot, and prints AUC for `same_story` vs the rest, AUC for `same_story` + `follow_up` vs the rest, the best F1 for `same_story` with its threshold, and ms per pair. Per-pair scores go to `logs/compare_<date>.jsonl`.

| Method | What it is | Model |
|---|---|---|
| `minilm` | Grouping signal before D-024 | MiniLM via fastembed, computed on the fly |
| `tfidf` | Shared words weighted by rarity (IDF over all articles) | none |
| `bge_m3` | Two-tower: cosine of CLS embeddings | `BAAI/bge-m3` (MIT) |
| `nemotron_embed` | Two-tower: cosine of mean-pooled embeddings, `passage: ` prefix on both | `nvidia/llama-nemotron-embed-1b-v2` (OpenMDW-1.1) |
| `bge_reranker` | Cross-encoder, text pair, sigmoid of the logit | `BAAI/bge-reranker-v2-m3` (Apache-2.0) |
| `smriti_ce` | The same, fine-tuned on the LLM's labels | `models/ce-same-story` (`app/train.py`) |
| `nemotron_rerank` | Cross-encoder, `question:{a} \n \n passage:{b}` template, sigmoid | `nvidia/llama-nemotron-rerank-1b-v2` (OpenMDW-1.1) |
| `llm` | Qwen3-4B judge with the same label rules as the gold set (`MEANINGS` in `app/gold.py`); labels ranked 1 / 0.75 / 0.5 / 0.25 / 0 | via `app/ollama.py` |

Cross-encoders score both orders (a, b) and (b, a) and average them, because a link has no direction. Transformers run one at a time on the GPU, BGE in float32 (float16 is ~5x slower on the GTX 1650) and the ~1B NVIDIA models in float16 (float32 doesn't fit in 4 GB); the Ollama model is unloaded first. Zero-shot AUC on the proxy pairs of D-027: cosine 0.893, bge_reranker 0.900, nemotron_rerank 0.857. On the gold set (2026-10-20, 199 pairs labelled by Claude, D-029), AUC for `same_story`: minilm 0.876, tfidf 0.888, bge_m3 0.918, nemotron_embed 0.915, bge_reranker 0.957, smriti_ce 0.966, nemotron_rerank 0.938, llm 0.959. Best F1: smriti_ce 0.863 (cut-off 0.485), llm 0.884, bge_m3 0.757. The NVIDIA models run their own code from the model repo (`trust_remote_code`).

`app/ollama.py` holds the shared Ollama call (`chat`) with the I-007 retry, used by `app/llm_test.py` and `app/compare.py`.

## 10. Not built yet (planned)

- **Grouping model (MVP):** built and run (sections 5 to 5b). Measured on the gold set (story precision 0.91, recall 0.70; see PROGRESS.md). Still to do: better recall, as one event still splits into parallel stories (I-016), a multi-hop graph query (`WITH RECURSIVE` over `issue_links`), and the LLM referee for uncertain cases (D-024).
- **Step 3 (Understand, LLM):** extract structured events from each article: who, what, when, action type, exact quote, and source URL. Being tested with `app/llm_test.py` (D-016 to D-020).
- **Step 4 (Remember, graph in Postgres):** Issue → Events → People / Organizations / Places, with every event linked to its source articles. Store attributed facts, not conclusions.
- **Scheduling:** fetch, embed and group are run by hand for now.
