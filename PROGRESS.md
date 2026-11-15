# Smriti: where we stand

_Last updated: 2026-11-15_

**Now:** the MVP pipeline (D-024, D-027, D-028) runs end to end: bge-m3 towers, a cross-encoder student fine-tuned on the local LLM's labels, story links with LLM link types, a story page with key-moment dots (D-030) and a "Today's stories" front page (D-032, D-033). The 2026-10-25 run (teacher relabelled with hard-case rules, retrain, full regroup; D-034, D-035) fixed I-023: the Tiger Shroff shooting is its own story (314 articles, no FDA news). Student on the gold set: 93.5% right, AUC 0.976, precision 0.91, recall 0.82 (was 92.5%, 0.966, 0.87, 0.81). The stories: precision 0.91, recall 0.70 (was 0.86, 0.67); Nepal floods, flydubai and *Toxic* are one story each. 2026-10-26: news categories as front-page tabs with an India / World switch (D-036; classifier weak, I-025), simpler cards (D-037), English only (D-038), an LLM referee for AI titles and dot labels (I-022). Nothing is running.

**Next 3 actions:**
1. Refresh the data (last fetch 2026-10-25 11:53, 21 days old on 2026-11-15), hand-check the front page's AI titles and categories at http://localhost:5173 (I-022, I-025), then build the twice-daily automatic fetch of D-032.
2. Grouping recall (I-016): the 18 same-story gold pairs still split, 15 with no link (`logs/gold3.out`); and check the CJP story (issue 8, 1,820 articles) for SIR / election-commission drift (I-001).
3. A 2-line story summary, checked against the headlines like the titles and dot labels.

**Waiting on the user:** the repo is public (D-039); ask GitHub Support to drop the old commits that still show the Gmail address (D-040; check: `curl -s -o /dev/null -w '%{http_code}' https://api.github.com/repos/joybratasarkar/smriti/commits/5978700` should give 404), confirm the copyright name, add repo topics, enable private vulnerability reporting; feedback on the front page (http://localhost:5173: categories, simpler cards) and the story page; how strict the title check should be (I-022).

**MVP (top priority, `[MVP]` in DECISIONS):** story grouping as a connected, traversable graph (D-023); two towers + cross-encoder, LLM only labels and referees (D-024, D-028). Build plan in `docs/WORKFLOW.md` section 5.

Open problems: [`docs/ISSUES.md`](docs/ISSUES.md) · Decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md) · Diagrams: [`docs/WORKFLOW.md`](docs/WORKFLOW.md) · How it works: [`docs/TECHNICAL.md`](docs/TECHNICAL.md)

## Data snapshot (2026-10-26)

| | |
|---|---|
| Articles | 149,641, Aug 21 – Oct 25 2026; last fetch 2026-10-25 11:53 IST (RSS + GDELT, 6 days) |
| Embeddings, stories, links | As of the 2026-10-25 grouping: 149,641 embedded, 148,502 grouped; 83,636 stories (18,321 with 2+ articles; largest 1,820, CJP); 15,760 links, 500 named |
| Gold pairs | 250: 200 in four cosine strata (196 by Claude, 4 by the user) + 50 shared-name (Claude, 2026-10-25) |
| Training pairs | 4,000 (3,000 cosine strata + 1,000 shared-name), relabelled 2026-10-25; old labels in `train_pairs_before_d035` |
| AI text | 1,896 dot labels (300 biggest stories + front-page stories; the referee removed 78 old ones, 61 rewritten, 2026-10-26, I-022), 108 front titles (`story_titles`) |
| Last LLM test | 2026-10-20: 30/30 ran, quotes verified 128/146 (88%), 21.3 s/article |

## How to run

From the project root with `source .venv/bin/activate`. Every script creates/updates the schema (`python -m app.db`).

| What | Command |
|---|---|
| Fetch news | `python -m app.fetch` (RSS, 7 days; `--days N`; `--gdelt` adds GDELT bulk files) |
| Check stored articles | `python -m app.stats` |
| Embed new articles | `python -m app.embed` (bge-m3 on GPU) |
| Group into stories | `python -m app.group` (`--reset`); cut-offs in `app/group.py` |
| Story links | `python -m app.links`; `--types N` has the LLM name the N strongest |
| Timeline labels (D-030) | `python -m app.moments --label N` (the N biggest stories) |
| Front-page titles + summaries (D-032, D-042) | `python -m app.front --titles N`; run after grouping |
| Categories (D-036) | `python -m app.categories --label N` (LLM labels N articles), then `python -m app.categories` (classifier, all stories) and `--stories` (LLM, front-page stories); run after grouping |
| Teacher labels (G-4) | `python -m app.teach` (progress), `--sample N`, `--names N` (shared-name pairs), `--opinion N` (editorial / review vs news, D-041), `--label` |
| Fine-tune (G-5) | `python -m app.train` → `models/ce-same-story/` (needed by `app.group`) |
| Gold set (G-2) | `python -m app.gold` (progress), `--sample N`, `--label`; `--stories` scores the stories; `--export` / `--import data/gold_pairs.csv` |
| Compare models (G-3) | `python -m app.compare` (`--methods ...`); per-pair scores in `logs/compare_<date>.jsonl` |
| Review issues / LLM test | `python -m app.issues` (`--top 30`, `--id 42`) · `python -m app.llm_test` (`--limit 10`) |
| API + frontend | `nohup .venv/bin/uvicorn app.api:app --reload --port 8010 > logs/api.log 2>&1 &` and `(cd frontend && nohup npm run dev > ../logs/frontend.log 2>&1 &)`; stop with `pkill -f "uvicorn app.api"; pkill -f vite` |

Refresh data: fetch → embed → group → categories (classifier, then `--stories`) → links → front titles (`/refresh` still lists only fetch → embed → group).

## Environment quirks

- Postgres 16 on port **5433** (db and role `smriti`). Port 5432 is a PG15 cluster for SonarQube: don't touch it. Create databases with `TEMPLATE template0`.
- GPU: GTX 1650, 4 GB VRAM; 7.1 GB system RAM. Models above ~4B don't fit. Ollama 0.40.2.
- Git: branch `main`, pushed to https://github.com/joybratasarkar/smriti (public since 2026-11-15, AGPL-3.0, D-039).
- Claude Code: `/status` (read-only), `/handoff` (docs, commit, push), `/refresh`, `/grill-me`, `/grilling`; caveman installed globally (`/caveman`, "normal mode" to stop; telemetry on).
