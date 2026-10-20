---
name: status
description: Show where the Smriti project stands in about 10 lines (current step, next actions, open issues, blockers), read from PROGRESS.md and docs/ISSUES.md. Read-only. Use when the user says status, where are we, where do we stand, or what's next.
---

Read-only: never edit files or run the pipeline.

1. Read `PROGRESS.md` and the "Open" table of `docs/ISSUES.md`. Run `git status --short` and `git log origin/main..main --oneline` (unpushed commits).
2. Print, in about 10 lines:
   - **Now:** the current step, one line.
   - **Next:** the 3 next actions from PROGRESS.
   - **Open issues:** count by type, then each P1 as `I-xxx title (status)`.
   - **Blocked / waiting on you:** anything blocked or waiting on the user, else "nothing".
   - **Repo:** uncommitted files and unpushed commits, else "clean, pushed".
   - **Data:** last fetch date from the data snapshot; flag it if older than 3 days.
3. If the docs disagree with what you see (for example an issue marked open whose fix is already committed, or PROGRESS older than the latest commit), say so in one line and suggest `/handoff`.
