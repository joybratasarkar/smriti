# Smriti: where we stand

_Last updated: 2026-10-20_

**Now:** Step 3 (Understand, LLM) is in testing. Extraction works and runs fully on the GPU; quotes verify 92%. Test runs lose articles to an out-of-memory kill (I-007).

**Next 3 actions:**
1. Fix [I-007](docs/ISSUES.md): retry when Ollama comes back, stop API/frontend during runs; rerun all 30 articles.
2. Hand-check ~10 articles from the run for I-002 to I-005.
3. Propose the `events`, `entities`, `entity_aliases` tables and the real extraction step (wait for OK before coding).

**Waiting on the user:** nothing.

Open problems: [`docs/ISSUES.md`](docs/ISSUES.md) · Decisions and why: [`docs/DECISIONS.md`](docs/DECISIONS.md) · Diagrams: [`docs/WORKFLOW.md`](docs/WORKFLOW.md) · How it works: [`docs/TECHNICAL.md`](docs/TECHNICAL.md)

## Data snapshot (2026-10-10)

| | |
|---|---|
| Articles | 1,053 (all RSS), published Oct 3 – Oct 10 2026 |
| Embeddings | 1,053 |
| Issues | 795 (98 with more than one article) |
| Last fetch | 2026-10-10 19:47 IST |
| Last LLM test | 2026-10-20: 20/30 ran, JSON 20/20, quotes verified 92/100, 22.3 s/article, 100% GPU |

## How to run

From the project root with `source .venv/bin/activate`.

| What | Command |
|---|---|
| Create/update schema | `python -m app.db` (every script also does this) |
| Fetch news (RSS, 7 days) | `python -m app.fetch` (`--days N`, `--gdelt`) |
| Check stored articles | `python -m app.stats` |
| Embed new articles | `python -m app.embed` |
| Group into issues | `python -m app.group` (`--threshold 0.7`, `--reset`) |
| Review issues | `python -m app.issues` (`--top 30`, `--id 42`) |
| LLM extraction test | `python -m app.llm_test` (`--limit 10`); output `logs/llm_test_<date>.jsonl` |
| API | `uvicorn app.api:app --reload --port 8010` |
| Frontend | `cd frontend && npm run dev` (port 5173, proxies `/api` to 8010) |

Refresh data: fetch → embed → group, or `/refresh`.

Servers in the background (logs in `logs/`):
```
nohup .venv/bin/uvicorn app.api:app --reload --port 8010 > logs/api.log 2>&1 &
(cd frontend && nohup npm run dev > ../logs/frontend.log 2>&1 &)
```
Stop: `pkill -f "uvicorn app.api"; pkill -f vite`

## Environment quirks

- Postgres 16 on port **5433** (db and role `smriti`). Port 5432 is a PG15 cluster for SonarQube: don't touch it. Create databases with `TEMPLATE template0`.
- GPU: GTX 1650, 4 GB VRAM; 7.1 GB system RAM. Models above ~4B don't fit. Ollama 0.40.2.
- Git: branch `main`, pushed to private https://github.com/joybratasarkar/smriti.

## Claude Code add-ons

- `/status`: prints where we stand (read-only).
- `/handoff`: updates PROGRESS, ISSUES, DECISIONS and diagrams, then commits and pushes. Run before closing the terminal.
- `/refresh`: fetch → embed → group, reports what changed.
- `/grill-me`, `/grilling`: round-by-round design interviews.
- caveman (installed globally 2026-10-10): `/caveman` for terse mode, "normal mode" to stop. Telemetry on (`caveman telemetry off`).
