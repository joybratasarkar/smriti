---
name: handoff
description: Save where the work stands into PROGRESS.md, docs/ISSUES.md, docs/DECISIONS.md and docs/WORKFLOW.md, then commit and push, so the next session can pick up after the terminal is closed. Use when the user says handoff, wrap up, save progress, or is about to close the terminal.
disable-model-invocation: true
---

Update the tracking docs so a fresh session, with no memory of this one, knows exactly where things stand. Each file has one job; don't repeat a fact in two files, link instead (`I-007`, `D-019`).

1. Read `PROGRESS.md`, `docs/ISSUES.md` and `docs/DECISIONS.md`. Run `git status` and `git log --oneline -10` to see what changed this session.
2. **`docs/ISSUES.md`:** add every new bug, quality finding, open question or chore found this session with the next free `I-` number (never reuse one). Update status, solvable? and next action of the ones that moved. Move solved / won't-fix issues to "Closed" with the date and how. Put evidence (numbers, log lines, file:line) in the detail block. A question that got answered closes here and its answer goes to DECISIONS.
3. **`docs/DECISIONS.md`:** add each decision made this session with the next free `D-` number, the date, and why. Never edit an old entry; a changed decision gets a new entry with "supersedes D-xxx". Add a node to the Timeline diagram if the session was a milestone.
4. **`docs/WORKFLOW.md`:** update the issue board (move IDs between columns, ★ for P1) and the pipeline colours (done / testing / planned / blocked) and row counts. Bump "Last updated".
5. **`PROGRESS.md`:** keep it under ~60 lines. Update "Now", "Next 3 actions", "Waiting on the user", the data snapshot (run `.venv/bin/python -m app.stats` if data changed), and the how-to-run table for new commands. No session log: git log is the log.
6. If `docs/TECHNICAL.md` describes something that changed (schema, algorithm, API, sources), update that section too.
7. Write absolute dates (YYYY-MM-DD), never "today" or "yesterday". Keep everything factual and short.
8. Show the user a short summary: issues opened / closed, decisions added, next action.
9. Commit and push. Stage only the files you changed plus code files the user agreed to commit this session, by name, never `git add -A` (stray edits must not slip in). If `git status` shows other changed files, list them for the user instead of committing them.
   `git add <files> && git commit -m "Handoff: <one-line summary>" && git push`
   If there is nothing to commit, say so. If the push fails, show the error; the commit is still safe locally.
