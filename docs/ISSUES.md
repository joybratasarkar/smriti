# Issues

Everything broken, weak or undecided, and whether it can be fixed. IDs are permanent and never reused.

- **Type:** `bug` (broken), `quality` (measured weakness), `question` (open design question; once answered it closes here and the answer goes to [DECISIONS.md](DECISIONS.md)), `chore` (environment upkeep).
- **Priority:** P1 blocks the next step, P2 matters soon, P3 whenever.
- **Status:** `open` → `in progress` → `solved` / `won't fix`, or `blocked` (on what).
- **Solvable?:** `yes` / `partly` / `no` / `unknown`.

## Open

| ID | Title | Type | P | Status | Solvable? | Next action |
|---|---|---|---|---|---|---|
| I-007 | Ollama killed by the out-of-memory killer during test runs | bug | P1 | open | yes | Retry when Ollama comes back; stop API/frontend during runs; rerun all 30 |
| I-001 | Grouping gives event-level clusters, not issues | question | P1 | in progress | yes | Design decided (D-005 to D-015); build events/entities tables, then merge |
| I-002 | LLM `who` field has wrong or invented entries | quality | P1 | in progress | partly | Hand-check the 2026-10-20 run |
| I-003 | Wrong `action_type`; `arrest_detention` overused | quality | P2 | in progress | yes | Hand-check the 2026-10-20 run |
| I-004 | Speculation ("could be arrested") stored as fact | quality | P2 | in progress | yes | Hand-check the 2026-10-20 run |
| I-005 | Same event listed twice in one article | quality | P3 | open | unknown | Measure in the hand check |
| I-009 | Data is stale: last fetch 2026-10-10 | chore | P2 | open | yes | Run `/refresh` |
| I-011 | Leftover `nvidia-driver-535` package | chore | P3 | open | yes | `sudo apt remove nvidia-driver-535` after checking it isn't in use |
| I-012 | Git warns `credential-manager-core` is not a git command | chore | P3 | open | yes | `git config --global --unset credential.helper` (push works without it) |

## Details (open)

### I-007 · Ollama killed by the out-of-memory killer
- **Evidence:** 2026-10-20 run: 10 of 30 articles failed with `Connection refused`. `journalctl`: `ollama.service: Failed with result 'oom-kill'`; kernel `Out of memory: Killed process (llama-server) anon-rss:3710560kB`. The 2026-10-10 run lost 6 articles the same way (then thought to be a "service restart").
- **Root cause:** the laptop has 7.1 GB RAM. `llama-server` uses ~3.7 GB of system RAM even with all layers on the GPU, and the API server, Vite and the browser use the rest.
- **Fix idea:** in `app/llm_test.py`, wait and retry when Ollama is unreachable instead of failing the article; stop `uvicorn` and `vite` during runs. If it still happens, lower `MAX_TEXT_CHARS` / `num_ctx`.

### I-001 · Event-level clusters, not issues
- **Evidence:** at cosine 0.70, 87 separate "issues" in the DB are all the CJP / Jantar Mantar protest.
- **Root cause:** similarity of title + snippet captures the event ("trains cancelled"), not the shared story behind it.
- **Plan:** D-005 to D-015: embeddings find candidates, LLM judges whole events against issues using people/orgs as the main signal.

### I-002 · `who` errors
- **Evidence (2026-10-20 hand check, 50 events, Oct 10 run):** invented acronym expansion "CJP (Chief Judicial Panel)"; non-entities "Facial Recognition System (FRS)", "Baliyan's brother"; "the government" turned into "Government of Delhi"; typo "Ashutosh Rank".
- **Progress:** prompt rules (D-020). Oct 20 rerun: only "Facial Recognition System (FRS)" left in an automatic scan of 100 events; not yet checked by hand.
- **Why only partly solvable:** a 4B model will keep making some name errors; `entity_aliases` (D-015) absorbs spelling variants, and outlets themselves spell names differently.

### I-003 · Wrong `action_type`
- **Evidence:** ~8 of 50 wrong in the Oct 10 run: statements, demands and warnings labelled `arrest_detention` or `policy_decision`; a court petition labelled `police_action`. Oct 20 run: `arrest_detention` 26 of 100.
- **Progress:** `demand` and `warning` added (D-020); used 5 and 3 times in the Oct 20 run.

### I-004 · Speculation stored as fact
- **Evidence:** Oct 10 run, article 183: "could be arrested" stored as an `arrest_detention` event.
- **Progress:** prompt rule (D-020). Oct 20 run: the 3 "could / will" events left are all statements by named people, which the rule allows.

### I-005 · Duplicate events
- **Evidence:** Oct 10 run, article 121: events 1 and 2 are the same detention of Deepak Baliyan.
- **Progress:** prompt rule (D-020); not measured yet.

## Closed

| ID | Title | Type | Closed | How |
|---|---|---|---|---|
| I-006 | Quotes not word for word | quality | 2026-10-20 | Two causes: checker too strict on `…`/`[ ]`, and quotes built from split sentences. Checker fixed, prompt rule added, unverified quotes dropped (D-019). Verified 77% → 92% |
| I-008 | `TECHNICAL.md` accidentally edited (stray `y`, "swap them" replacing a section) | bug | 2026-10-20 | Restored from the last commit |
| I-010 | GDELT returns 429s and empty results | chore | 2026-10-10 | Won't fix: GDELT kept opt-in (D-001) |
| I-013 | Secure Boot blocked the NVIDIA driver | chore | 2026-10-10 | MOK key enrolled; driver 595.99 / CUDA 13.2; Ollama upgraded to 0.40.2 |
| I-014 | Qwen3.5-4B doesn't fit in 4 GB VRAM | bug | 2026-10-10 | Switched to Qwen3-4B-Instruct-2507 (D-017) |
