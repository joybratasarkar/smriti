---
name: refresh
description: Refresh Smriti's data by running the whole pipeline (python -m app.refresh) and report what changed. Use when the user says refresh, update the news, or run the pipeline.
disable-model-invocation: true
---

Run Smriti's data pipeline from the project root with `.venv/bin/python -m app.refresh` (in the background: a catch-up after days without a fetch takes hours). It runs every stage in order (fetch, embed, group, categories, links, LLM text), stops at the first that fails, and ends with the `app.check` health report. Each stage only processes new work, so re-running is safe; a second run won't start while one is going.

Step output is in `logs/refresh/<start time>/<step>.out`. If a stage failed, show its error from that file and don't rerun later stages by hand on partial data.

At the end, report briefly:
- new articles, and feeds that failed or returned nothing (from the fetch output and `logs/fetch.log`)
- articles embedded
- articles grouped, new issues versus articles that joined existing issues
- new totals (articles, issues, newest article date)

Then update the "Data snapshot" table in `PROGRESS.md` with the new totals and today's date.
