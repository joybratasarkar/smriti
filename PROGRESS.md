# Smriti: where we are

_Last updated: 2026-10-10_

## Where we left off

- Steps 1 and 2 are done. An early, read-only web app (API + Svelte UI) is also built.
- **Open question from Step 2:** with the threshold at 0.70, clusters come out at the **event** level (for example "trains cancelled for protest"), not the **issue** level. We still need a way to merge related events into one issue.
- **Decided (2026-10-10):**
  - Grouping by cosine similarity alone is not reliable: it gives event-level clusters, not issue-level ones. Embeddings are now **only a candidate finder**.
  - Merging events into issues will use **structured facts** (people, organizations, places, action types, dates) **plus an LLM judgment**.
  - The graph stays in **plain Postgres tables**, with no separate graph database.
  - Evidence: 87 separate "issues" in the DB are all about the CJP / Jantar Mantar protest.
- **Next:** the design discussion for extraction and merging is in progress (no code yet). Open questions: which LLM, whether to read full article text at extraction time without storing it, and how entities are normalized. Per CLAUDE.md, propose an approach and wait for an OK before coding.

## Data snapshot (2026-10-10)

| | |
|---|---|
| Articles | 1,053 (all RSS), published Oct 3 – Oct 10 2026 |
| Embeddings | 1,053 (all articles) |
| Issues | 795 (98 with more than one article) |
| Last fetch | 2026-10-10 19:47 IST |

## How to run

All Python commands run from the project root with the virtualenv active: `source .venv/bin/activate`.

| What | Command |
|---|---|
| Create/update schema | `python -m app.db` (every script also does this itself) |
| Fetch news (RSS, 7 days) | `python -m app.fetch` (`--days N`, `--gdelt` for opt-in GDELT) |
| Check stored articles | `python -m app.stats` |
| Embed new articles | `python -m app.embed` |
| Group into issues | `python -m app.group` (`--threshold 0.7`, `--reset` to regroup everything) |
| Review issues | `python -m app.issues` (`--top 30`, `--id 42`) |
| API | `uvicorn app.api:app --reload --port 8010` |
| Frontend | `cd frontend && npm run dev` (port 5173, proxies `/api` to 8010) |

To refresh the data, run fetch → embed → group in that order.

To run both servers in the background (logs go to `logs/api.log` and `logs/frontend.log`):
```
nohup .venv/bin/uvicorn app.api:app --reload --port 8010 > logs/api.log 2>&1 &
(cd frontend && nohup npm run dev > ../logs/frontend.log 2>&1 &)
```
To stop them: `pkill -f "uvicorn app.api"; pkill -f vite`

## Code map

- `TECHNICAL.md`: detailed technical notes (sources, schema, embeddings, grouping, API, timeline).
- `schema.sql`: all tables (`articles`, `article_embeddings`, `issues`, `article_issues`). This is the only schema file; there are no migrations.
- `app/db.py`: `connect()` reads `DATABASE_URL` from `.env`; `connect_with_vectors()` also registers pgvector.
- `app/fetch.py`: RSS from `feeds.txt` (16 feeds from 15 sources, in `name | url` format), optional GDELT, URL normalization, dedupe on URL, retries, logs to `logs/fetch.log`.
- `app/embed.py`: fastembed `paraphrase-multilingual-MiniLM-L12-v2` on title + snippet (384 dimensions, normalized).
- `app/group.py`: incremental grouping. Articles are assigned oldest first to the nearest issue centroid active in the last 14 days, or start a new issue. Assigned articles never move.
- `app/issues.py`, `app/stats.py`: command-line review tools.
- `app/api.py`: `/api/summary`, `/api/issues` (sort, min_size, q, paging), `/api/issues/{id}`.
- `frontend/src/`: `App.svelte` (hash router), `IssueList.svelte`, `IssueDetail.svelte` (timeline + "no reports since"), `lib/format.js`.

## Environment quirks

- Postgres 16 runs on port **5433**, database and role are both `smriti`. Port 5432 is a separate PG15 cluster holding SonarQube data; don't touch it.
- template1 has a glibc collation mismatch, so create new databases with `TEMPLATE template0`.
- The pgvector extension needs a superuser: `sudo -u postgres psql -p 5433 -d smriti -c "CREATE EXTENSION vector;"` (already done).
- GDELT gave persistent 429s and empty results, so it is opt-in only.
- Git repo initialized 2026-10-10 (branch `main`, local only, no remote). `.env`, `.venv/`, `logs/`, `node_modules/` and `dist/` are ignored.

## Claude Code add-ons

- `/refresh` (`.claude/skills/refresh`): runs fetch → embed → group in order, reports what changed, and updates the data snapshot.
- `/handoff` (`.claude/skills/handoff`): updates this file (and TECHNICAL.md if needed) and commits. Run it before closing the terminal.
- `.claude/skills/grill-me` and `.claude/skills/grilling` (from github.com/mattpocock/skills): `/grill-me` runs a round-by-round interview to stress-test a design. Added 2026-10-10.
- caveman (github.com/JuliusBrussee/caveman): CLI v2.1.0 installed globally by the user on 2026-10-10. Adds hooks to ~/.claude/settings.json (proxy + shrink) and the `caveman` skill. Telemetry is ON (turn off: `caveman telemetry off`). Turn terse mode on with `/caveman`, off with "normal mode".

## Log

- **2026-10-10:** Step 1 (RSS ingest), Step 2 (embeddings + grouping), and the read-only web app built. Renamed `claude.md` → `CLAUDE.md` so it loads automatically, and added this file. Started the API (8010) and frontend (5173) in the background and checked they respond. Added the start/stop commands above. No code changes.
- **2026-10-10 (later):** Decided that embeddings only find candidates; issue merging will use structured facts plus an LLM judge. Design discussion is open (see "Where we left off"). Added the grill-me skill. The caveman install was blocked in auto mode, so the user will run it themselves.
