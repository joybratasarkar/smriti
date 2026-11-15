# Smriti

An app that remembers the news. Normal news apps show the latest story and forget the rest. Smriti follows an issue over time: what happened, what action was taken, who was involved, and what is still unresolved, with every fact linked to its source article.

Accuracy rules: every event must be traceable to a source article, and we store attributed facts, not conclusions. Only links and metadata are stored, never full article text.

## Status

| Part | State |
|---|---|
| Ingest: RSS from Indian and world outlets (plus optional GDELT) into Postgres | Done |
| Group: bge-m3 embeddings find candidates, a fine-tuned cross-encoder decides "same story?" | Done (MVP) |
| Story links: related stories connected as a graph, link types named by the LLM | Done |
| Web app: "Today's stories" front page with categories, story page with a timeline | Done (read-only) |
| Understand: local LLM extracts events (who, what, when, where, quote) | Testing |
| Automatic twice-daily fetch | Planned |

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
- PostgreSQL 16 with pgvector (everything, including the story graph, is plain tables)
- PyTorch + Hugging Face transformers on a small GPU (4 GB is enough):
  - `BAAI/bge-m3` embeddings (1024-dim) to find candidate articles
  - `BAAI/bge-reranker-v2-m3` cross-encoder, fine-tuned on the local LLM's labels (`python -m app.train`), to decide which articles are the same story
- Ollama with Qwen3-4B-Instruct-2507 as the teacher and referee: labels training pairs, names story links, writes front-page titles and timeline labels, sorts categories
- Svelte 5 + Vite for the frontend

## Requirements

- Linux or macOS (developed on Ubuntu 24.04)
- Python 3.12
- PostgreSQL 16 with the [pgvector](https://github.com/pgvector/pgvector) extension
- An NVIDIA GPU with about 4 GB of VRAM for embedding, grouping and training (CPU works, but slowly), and about 8 GB of RAM
- [Ollama](https://ollama.com) for the local LLM (labels, titles, categories)
- Node.js 20+ for the frontend
- About 10 GB of disk for the models (bge-m3, the cross-encoder and its fine-tuned copy, Qwen3-4B)

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
6. **LLM (labels, titles, categories, extraction test).** Install Ollama and `ollama pull qwen3:4b-instruct-2507-q4_K_M`.

## Usage

Run from the project root with the virtualenv active.

| What | Command |
|---|---|
| Fetch news (RSS, last 7 days) | `python -m app.fetch` (`--days N`; `--gdelt` adds GDELT bulk files) |
| Check stored articles | `python -m app.stats` |
| Embed new articles | `python -m app.embed` |
| Teacher labels for training | `python -m app.teach` (progress), `--sample N`, `--names N`, `--label` |
| Fine-tune the cross-encoder | `python -m app.train` → `models/ce-same-story/` |
| Group into stories | `python -m app.group` (`--reset` regroups everything) |
| Story links | `python -m app.links` (`--types N`: the LLM names the N strongest) |
| Categories | `python -m app.categories --label N`, then `python -m app.categories`, then `--stories` |
| Front-page titles | `python -m app.front --titles N` |
| Timeline labels | `python -m app.moments --label N` |
| Gold set, model comparison | `python -m app.gold` (`--sample N`, `--label`), `python -m app.compare` |
| Score the stories on the gold set | `python -m app.gold --stories` |
| Load the shared gold set | `python -m app.gold --import data/gold_pairs.csv` (pairs whose two URLs you have fetched) |
| Review stories, LLM test | `python -m app.issues` (`--top 30`, `--id 42`), `python -m app.llm_test` (`--limit 10`) |
| API | `uvicorn app.api:app --reload --port 8010` |
| Frontend | `cd frontend && npm run dev`, then open http://localhost:5173 |

To refresh the data, run fetch → embed → group → categories → links → front titles in that order. `app.group` needs the fine-tuned model in `models/ce-same-story/`, built from teacher labels (`python -m app.teach --sample N`, then `--label`) and `python -m app.train`. Feeds are listed in `feeds.txt` (`name | url`); add a line to add a source.

## Layout

```
app/          Python: fetch, embed, teach/train, group, links, categories, front, api, review tools
frontend/     Svelte UI (front page, story list, story page with a timeline)
models/       fine-tuned cross-encoder (git-ignored; build it with app.teach + app.train)
schema.sql    all tables; the only schema file
data/         gold_pairs.csv: the hand-checked gold set as URLs and labels (no article text)
feeds.txt     RSS sources
docs/         issues, decisions, diagrams, technical notes
logs/         run logs (git-ignored)
```

The docs cite files in `logs/` (run scripts, gold-check output) as evidence. They stay on the developer's machine and are not published.

## Data and copyright

Smriti stores links and metadata only: title, URL, source, dates, language, a short snippet and a content hash. Full article text is never stored. The LLM test (`app/llm_test.py`) downloads an article's text, passes it to the model and discards it. The article archive (the database) is not part of this repository and must not be published. News content belongs to its publishers. If you run a public instance, check each feed's terms of use, as many allow only personal, non-commercial use.

## License

Copyright (C) 2026 Joybrata Sarkar.

Smriti is free software under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0). You may use, change and share it. If you run a modified version as a network service, you must offer its source code to that service's users. For other licensing terms, including commercial use without AGPL obligations, contact the copyright holder through GitHub.

Contributions are welcome under the [Contributor License Agreement](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md). Security: see [SECURITY.md](SECURITY.md).
