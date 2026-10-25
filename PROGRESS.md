# Smriti: where we stand

_Last updated: 2026-10-24_

**Now:** MVP grouping pipeline built and run on all 60 days (D-024, D-027, D-028): bge-m3 towers, a cross-encoder fine-tuned on the LLM's labels (teacher-student), weighted story links, LLM link types, "Connected stories" in the UI. The overnight run (`logs/full_run.sh`, 2026-10-20 15:19 – 22:48, exit 0) did all of it: the LLM labelled 3,000 pairs; the fine-tuned cross-encoder agrees with it on 93.1% of held-out pairs (86% before; AUC 0.908 → 0.967); 138,229 articles became 72,591 stories (14,782 with 2 or more articles); 10,390 links, the 500 strongest named by the LLM; 200 gold pairs sampled. Per-step logs: `logs/*_full.out`, `logs/links_types.out`, `logs/gold_sample.out`. Biggest open problem: one event split into parallel stories (I-016).

**Measured on the gold set (2026-10-20, 199 pairs labelled by Claude, D-029; `logs/compare_2026-10-20.jsonl`):** the fine-tuned student ranks best of all methods (AUC 0.966; LLM 0.959, cosine 0.918) and at the 0.5 cut-off gets 92.5% of pairs right (precision 0.87, recall 0.81); before training the same model got 85.9% (recall 0.54). The teacher LLM gets 94.0% but is 24 times slower. The app's stories get 89% right (precision 0.86) but keep only 67% of same-story pairs together: the gap between 81% and 67% is how grouping uses the student (I-016).

**New story page (2026-10-24, D-030):** a story's timeline is now a path of up to 7 key-moment dots ending at "now", with short AI labels checked against the headlines, connected stories as side dots, and the full day-by-day list folded below. `app/moments.py`, `frontend/src/StoryPath.svelte`; prototype at https://claude.ai/artifact/JhpoMNAk8rpebmUryvRNto. Labels for the 300 biggest stories are being written (`logs/moments_label.out`).

**Tonight (2026-10-25, from 22:00, detached):** the 2026-10-24 start never happened: the laptop suspended and a plain `sleep` stops counting while suspended. Relaunched 2026-10-25 11:00 under `systemd-inhibit` (blocks sleep, idle and lid-close suspend), waiting on the wall clock; a reboot at 11:04 killed it before any step ran, relaunched again 11:06 (check with `systemd-inhibit --list | grep smriti`; a reboot kills it, relaunch with the same command). `logs/run_2026-10-24.sh` regroups all 60 days with the trust fixes (D-031: closest-member scoring and the merge pass for I-016, no blank titles I-017, no second copies I-019), then links, link names, AI labels for the 300 biggest stories, and the gold-set check of the stories (`logs/gold2.out`). `logs/run2.done` says how it ended (expected around 05:30 on 2026-10-26). Front-page round 1 answered (yes to all, 2026-10-25). The app shows half-built stories while it runs.

**Next 3 actions:**
1. When `logs/run2.done` says `exit 0`: compare `logs/gold2.out` with the stories' scores before the fix (precision 0.86, recall 0.67) and check the split examples (Nepal, CJP, Tiger Shroff, flydubai).
2. Front page "Today's stories": design interview, then a prototype (UI/UX review, 2026-10-24).
3. Clean AI story titles and a 2-line summary, checked against the headlines like the dot labels.

**Waiting on the user:** answers to the front-page design questions; feedback on the story page.

**MVP (top priority, see `[MVP]` in DECISIONS):**
- Story grouping as a connected, traversable graph (D-023).
- Model: two towers + cross-encoder transformer, link type + weight, LLM only labels and referees (D-024); unit = article (D-025); pipeline first (D-027); cross-encoder fine-tuned on LLM labels (D-028). Build plan in `docs/WORKFLOW.md` section 5.

Open problems: [`docs/ISSUES.md`](docs/ISSUES.md) · Decisions and why: [`docs/DECISIONS.md`](docs/DECISIONS.md) · Diagrams: [`docs/WORKFLOW.md`](docs/WORKFLOW.md) · How it works: [`docs/TECHNICAL.md`](docs/TECHNICAL.md)

## Data snapshot (2026-10-20)

| | |
|---|---|
| Articles | 138,229 (2,091 RSS + 136,138 GDELT), Aug 21 – Oct 20 2026 |
| Embeddings | 138,229 (all) |
| Stories (issues) | 72,591; 14,782 with more than one article; largest 224 (a CJP protest story) |
| Links | 10,390; the 500 strongest named: same_topic 330, unrelated 70, same_story 66, same_actor 34 |
| Gold pairs | 200 (50 per stratum), all labelled: 196 by Claude (D-029), 4 by the user |
| Last fetch | 2026-10-20 13:18 IST (RSS); GDELT backfill finished 15:39 IST |
| Last LLM test | 2026-10-20 rerun: 30/30 ran, JSON 30/30, quotes verified 128/146 (88%), 21.3 s/article, 100% GPU, 1 OOM kill retried |

## How to run

From the project root with `source .venv/bin/activate`.

| What | Command |
|---|---|
| Create/update schema | `python -m app.db` (every script also does this) |
| Fetch news (RSS, 7 days) | `python -m app.fetch` (`--days N`; `--gdelt` adds GDELT bulk files, ~24 GB for 60 days) |
| Check stored articles | `python -m app.stats` |
| Embed new articles | `python -m app.embed` (bge-m3 on GPU) |
| Group into stories | `python -m app.group` (`--reset`); cut-offs in `app/group.py` |
| Story links | `python -m app.links`; `--types N` has the LLM name the N strongest |
| Timeline labels (D-030) | `python -m app.moments --label N`: AI labels for the key moments of the N biggest stories (unlabelled moments show a trimmed headline) |
| Teacher labels (G-4) | `python -m app.teach` (progress), `--sample 3000`, `--label` |
| Fine-tune (G-5) | `python -m app.train` → `models/ce-same-story/` (needed by `app.group`) |
| Review issues | `python -m app.issues` (`--top 30`, `--id 42`) |
| Gold set (G-2) | `python -m app.gold` (progress), `--sample 200`, `--label` |
| Compare models (G-3) | `python -m app.compare` (`--methods cosine tfidf ...`); per-pair scores in `logs/compare_<date>.jsonl` |
| LLM extraction test | `python -m app.llm_test` (`--limit 10`); output `logs/llm_test_<date>.jsonl` |
| API | `uvicorn app.api:app --reload --port 8010` |
| Frontend | `cd frontend && npm run dev` (port 5173, proxies `/api` to 8010) |

Refresh data: fetch → embed → group → links, or `/refresh` (its skill still lists fetch → embed → group).

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
