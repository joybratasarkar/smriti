# Smriti: where we stand

_Last updated: 2026-10-25_

**Now:** the MVP pipeline (D-024, D-027, D-028) runs end to end: bge-m3 towers, a cross-encoder student fine-tuned on the local LLM's labels, story links with LLM link types, a story page with key-moment dots (D-030) and a "Today's stories" front page (D-032, D-033). Last full result (2026-10-20 grouping, gold set of 199 pairs): student 92.5% right (AUC 0.966), the stories' precision 0.86, recall 0.67 (I-016). On 2026-10-25 the user found the Tiger Shroff shooting inside Tukaram Mundhe's FDA ad-notice story (I-023), which led to per-headline scoring (D-034) and hard-case rules for the teacher (D-035: teacher 91.5% → 94.5% on the gold set).

**Running now (from 2026-10-25 12:14, detached under `systemd-inhibit`):** `logs/run_2026-10-25.sh`: the teacher relabels all 4000 training pairs → train → student scored on the gold set (`logs/compare3.out`) → embed → `group --reset` (~6–9 h) → links → link names → AI labels → front titles → stories' gold check (`logs/gold3.out`). Progress in `logs/run3.log`; `logs/run3.done` says how it ended (expected early 2026-10-26). Alive? `systemd-inhibit --list | grep smriti`. A reboot kills it: rerun the script (labels already written stay). The app shows half-built stories while it runs.

**Next 3 actions:**
1. When `logs/run3.done` says `exit 0`: compare `logs/compare3.out` and `logs/gold3.out` with the numbers above (the gold set is now 250 pairs, D-035); check the Tiger Shroff shooting is its own story with the FDA notices as a connected story, and the split examples (Nepal, CJP, flydubai).
2. Hand-check the front page's AI titles (I-022), then build the twice-daily automatic fetch of D-032.
3. A 2-line story summary, checked against the headlines like the titles and dot labels.

**Waiting on the user:** feedback on the front page (http://localhost:5173) and the story page; how strict the title check should be (I-022).

**MVP (top priority, `[MVP]` in DECISIONS):** story grouping as a connected, traversable graph (D-023); two towers + cross-encoder, LLM only labels and referees (D-024, D-028). Build plan in `docs/WORKFLOW.md` section 5.

Open problems: [`docs/ISSUES.md`](docs/ISSUES.md) · Decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md) · Diagrams: [`docs/WORKFLOW.md`](docs/WORKFLOW.md) · How it works: [`docs/TECHNICAL.md`](docs/TECHNICAL.md)

## Data snapshot (2026-10-25)

| | |
|---|---|
| Articles | 149,641, Aug 21 – Oct 25 2026; last fetch 2026-10-25 11:53 IST (RSS + GDELT, 6 days) |
| Embeddings, stories, links | As of the 2026-10-20 grouping: 138,229 embedded; 72,591 stories (14,782 with 2+ articles); 10,390 links. Rebuilt by the running job |
| Gold pairs | 250: 200 in four cosine strata (196 by Claude, 4 by the user) + 50 shared-name (Claude, 2026-10-25) |
| Training pairs | 4,000 (3,000 cosine strata + 1,000 shared-name), relabelled 2026-10-25; old labels in `train_pairs_before_d035` |
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
| Front-page titles (D-032) | `python -m app.front --titles N`; run after grouping |
| Teacher labels (G-4) | `python -m app.teach` (progress), `--sample N`, `--names N` (shared-name pairs), `--label` |
| Fine-tune (G-5) | `python -m app.train` → `models/ce-same-story/` (needed by `app.group`) |
| Gold set (G-2) | `python -m app.gold` (progress), `--sample N`, `--label` |
| Compare models (G-3) | `python -m app.compare` (`--methods ...`); per-pair scores in `logs/compare_<date>.jsonl` |
| Review issues / LLM test | `python -m app.issues` (`--top 30`, `--id 42`) · `python -m app.llm_test` (`--limit 10`) |
| API + frontend | `nohup .venv/bin/uvicorn app.api:app --reload --port 8010 > logs/api.log 2>&1 &` and `(cd frontend && nohup npm run dev > ../logs/frontend.log 2>&1 &)`; stop with `pkill -f "uvicorn app.api"; pkill -f vite` |

Refresh data: fetch → embed → group → links → front titles (`/refresh` still lists only fetch → embed → group).

## Environment quirks

- Postgres 16 on port **5433** (db and role `smriti`). Port 5432 is a PG15 cluster for SonarQube: don't touch it. Create databases with `TEMPLATE template0`.
- GPU: GTX 1650, 4 GB VRAM; 7.1 GB system RAM. Models above ~4B don't fit. Ollama 0.40.2.
- Git: branch `main`, pushed to private https://github.com/joybratasarkar/smriti.
- Claude Code: `/status` (read-only), `/handoff` (docs, commit, push), `/refresh`, `/grill-me`, `/grilling`; caveman installed globally (`/caveman`, "normal mode" to stop; telemetry on).
