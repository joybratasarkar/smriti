# Smriti

An app that remembers the news. Normal news apps show the latest story and forget the rest. Smriti follows an issue over time: what happened, what action was taken, who was involved, and what is still unresolved, with every fact linked to its source article.

Accuracy rules: every event must be traceable to a source article, and we store attributed facts, not conclusions. Only links and metadata are stored, never full article text.

## Status

| Part | State |
|---|---|
| Ingest: RSS from 15 Indian and world outlets into Postgres | Done |
| Group: embeddings + similarity clustering into issues | Done (gives event-level clusters; being replaced) |
| Web app: issue list and per-issue timeline | Done (read-only) |
| Understand: local LLM extracts events (who, what, when, where, quote) | Testing |
| Remember: issues → events → people/orgs as Postgres tables, LLM-judged merges | Designed |

Where things stand:

| File | Answers |
|---|---|
| [`PROGRESS.md`](PROGRESS.md) | Where are we now, and what's next? |
| [`docs/ISSUES.md`](docs/ISSUES.md) | What's broken or uncertain, and can it be fixed? |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | What did we decide, and why? |
| [`docs/WORKFLOW.md`](docs/WORKFLOW.md) | Diagrams: pipeline, issue board, merge design |
| [`docs/TECHNICAL.md`](docs/TECHNICAL.md) | How it works: sources, schema, algorithms, API |

## Stack

- Python, FastAPI, psycopg 3
- PostgreSQL 16 with pgvector (everything, including the graph, is plain tables)
- fastembed (`paraphrase-multilingual-MiniLM-L12-v2`) for embeddings
- Ollama with Qwen3-4B-Instruct-2507 for extraction (runs on a 4 GB GPU)
- Svelte 5 + Vite for the frontend

## Setup

1. **Database.** PostgreSQL 16 with a database and role named `smriti`, then enable pgvector (needs a superuser):
   ```
   createdb -T template0 smriti
   sudo -u postgres psql -d smriti -c "CREATE EXTENSION vector;"
   ```
2. **Python.**
   ```
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Config.** Copy `.env.example` to `.env` and set `DATABASE_URL`. `.env` is git-ignored.
4. **Schema.** `python -m app.db` (every script also applies it on start).
5. **Frontend.** `cd frontend && npm install`
6. **LLM (only for the extraction test).** Install Ollama and `ollama pull qwen3:4b-instruct-2507-q4_K_M`.

## Usage

Run from the project root with the virtualenv active.

| What | Command |
|---|---|
| Fetch news (RSS, last 7 days) | `python -m app.fetch` (`--days N`, `--gdelt`) |
| Check stored articles | `python -m app.stats` |
| Embed new articles | `python -m app.embed` |
| Group into issues | `python -m app.group` (`--threshold 0.7`, `--reset`) |
| Review issues | `python -m app.issues` (`--top 30`, `--id 42`) |
| LLM extraction test | `python -m app.llm_test` (`--limit 10`) |
| API | `uvicorn app.api:app --reload --port 8010` |
| Frontend | `cd frontend && npm run dev`, then open http://localhost:5173 |

To refresh the data, run fetch → embed → group in that order. Feeds are listed in `feeds.txt` (`name | url`); add a line to add a source.

## Layout

```
app/          Python: fetch, embed, group, api, review tools, llm_test
frontend/     Svelte UI (issue list, timeline per issue)
schema.sql    all tables; the only schema file
feeds.txt     RSS sources
docs/         issues, decisions, diagrams, technical notes
logs/         run logs (git-ignored)
```
