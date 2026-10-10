---
name: refresh
description: Refresh Smriti's data by running the pipeline in order (fetch, embed, group) and report what changed. Use when the user says refresh, update the news, or run the pipeline.
disable-model-invocation: true
---

Run Smriti's data pipeline from the project root, in this order. Each stage only processes new work, so re-running is safe.

1. Record the counts before running:
   `.venv/bin/python -m app.stats` (note total articles), and the issue count from `.venv/bin/python -m app.issues --top 0`.
2. `.venv/bin/python -m app.fetch` (RSS, last 7 days). Add `--gdelt` only if the user asks.
3. `.venv/bin/python -m app.embed`
4. `.venv/bin/python -m app.group`
5. If later pipeline stages exist (for example extraction or issue merging), check `PROGRESS.md` for their commands and run them after grouping, in the order listed there.

Stop at the first stage that fails. Show its error, and don't run later stages on partial data.

At the end, report briefly:
- new articles, and feeds that failed or returned nothing (from the fetch output and `logs/fetch.log`)
- articles embedded
- articles grouped, new issues versus articles that joined existing issues
- new totals (articles, issues, newest article date)

Then update the "Data snapshot" table in `PROGRESS.md` with the new totals and today's date.
