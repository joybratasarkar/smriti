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
- **Grilling round 1 (2026-10-10), all accepted:**
  1. Exception: near-duplicates (cosine ≥ 0.90) join the same event cluster automatically. Every issue-level merge goes to the LLM.
  2. Candidate = cosine ≥ ~0.45 to any event of the issue **or** at least one shared key person/org; only issues active in the last 30 days; top 5 go to the LLM. Thresholds to be measured on the CJP set.
  3. People/orgs are the strong signal and can make a candidate alone. Places, action types and dates are context for the LLM, never filters.
  4. The LLM decides automatically. Store verdict, reason, evidence and model; every merge is reversible; review page later.
  5. Typed tables (`issues`, `events`, `entities`) plus link tables, not a generic nodes/edges table.
- **LLM decided (2026-10-10):** use a **local open-source model on the GPU** (Ollama), not the Claude API. **Model: Qwen3.5-4B (Q4)**, run with thinking off and JSON-schema-constrained output (Ollama `format`, needs a new Ollama). Backup: Qwen3-4B-Instruct-2507. Gemma 3 4B dropped (superseded); Gemma 4 E4B only if `ollama ps` shows it fully on GPU. Test both Qwen models on ~30 CJP articles: JSON validity, field accuracy, seconds per article.
- **Model swapped (2026-10-10, after speed test):** main model is now **Qwen3-4B-Instruct-2507 (Q4_K_M)**. With `num_ctx` 4096 and `num_gpu` 99 it runs 100% on the GTX 1650 at ~38 tok/s (~50 s per real article with 10–16 events). Qwen3.5-4B only fits 65% on GPU (~10 tok/s, ~120 s/article) and runs out of memory when forced fully onto the GPU, so it is dropped. Batching (`OLLAMA_NUM_PARALLEL`) is not tried yet. Test script: `python -m app.llm_test`.
- **30-article test (2026-10-10, capped at 5 events/article):** full text 30/30, valid JSON 24/24 that ran (6 failed because the Ollama service restarted mid-run), quotes verbatim 89/116 (77%), 22.2 s/article, 100% GPU. Still to do: hand-check `who`/`what` on ~10 articles, and decide what to do with non-verbatim quotes.
- **GPU status (2026-10-10, resolved):** MOK enrolled, Secure Boot on, `nvidia-smi` shows GTX 1650 (4 GB) on driver 595.99 / CUDA 13.2. Ollama upgraded to 0.40.2. Next: pull `qwen3.5:4b` and `qwen3:4b-instruct-2507-q4_K_M`, then run the ~30-article CJP test. Leftover `nvidia-driver-535` package can be removed later. Laptop has 7.1 GB RAM, so models above ~4B won't fit.
- **Grilling round 2 (2026-10-10), all accepted:**
  7. Full text at extraction time: fetch the article, give it to the LLM, then discard it. Store only extracted facts + exact quote + source URL.
  8. Issue definition (goes into the LLM prompt): same issue = the same ongoing story, with the same core dispute/demand and the same main people/orgs, followed over time. Example: CJP demand → Jantar Mantar protest → detentions → trains cancelled → government response = one issue. A different group's protest at the same place = a different issue. The LLM judges against this rule.
  9. The LLM judges whole event clusters against an issue (one call per event), not individual articles. The event's articles move together.
  10. Entities: an `entities` table (one row per real person/org, one canonical name) plus `entity_aliases` (every spelling seen → entity). Start with exact match on the normalized alias (lowercase, no punctuation); add fuzzy/LLM matching only if duplicates show up.
- **Next:** design questions Q1–Q10 are all settled. Next is the ~30-article CJP model test (Qwen3.5-4B vs Qwen3-4B-Instruct-2507): JSON validity, field accuracy, seconds per article. Per CLAUDE.md, propose the test approach and wait for an OK before coding.

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

- `WORKFLOW.md`: diagrams of what has been built and decided so far (Mermaid).
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
