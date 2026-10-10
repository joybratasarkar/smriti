---
name: handoff
description: Save where the work stands into PROGRESS.md (and commit it) so the next session can pick up after the terminal is closed. Use when the user says handoff, wrap up, save progress, or is about to close the terminal.
disable-model-invocation: true
---

Update `PROGRESS.md` so a fresh session, with no memory of this one, knows exactly where things stand.

1. Read the current `PROGRESS.md` and run `git status` and `git log --oneline -10` to see what changed this session.
2. Update these sections in place. Edit them; don't append duplicates:
   - **Where we left off:** what is done, what is half-done (name the files), the next concrete step, and any decision waiting on the user.
   - **Decisions:** add any decision made this session, with a one-line reason.
   - **Data snapshot:** refresh the counts if data changed (query the DB with `.venv/bin/python -m app.stats`).
   - **How to run / Code map:** add new commands, files or tables introduced this session.
   - **Log:** add one dated line (YYYY-MM-DD) summarizing the session.
3. If `TECHNICAL.md` describes something that changed (schema, algorithm, API, sources), update that section too.
4. Keep both files factual and short. Write absolute dates, never "today" or "yesterday".
5. Show the user a short summary of what you recorded, then commit all changes:
   `git add -A && git commit -m "Handoff: <one-line summary>"`.
   If there is nothing to commit, say so.
