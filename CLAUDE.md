# Project: Smriti (working name)

An application that remembers the news. Normal news apps show the latest story and forget the rest. Smriti follows an issue over time: what happened, what action was taken, who was involved, and what is still unresolved, with every fact linked to its source article.

## How we work

- We build in small steps, one at a time. Do NOT build ahead of the current step.
- At the start of each step, briefly propose your approach and wait for my OK before writing lots of code.
- Keep code simple and readable. No unnecessary frameworks or abstractions.
- After each step, tell me how to run it and how to verify it works.

## Stack

- **Backend:** Python (FastAPI preferred)
- **Database:** PostgreSQL. It stores everything, including the graph, as plain tables (nodes and edges via relation tables). No separate graph database for now. pgvector may be added later for embeddings.
- **Frontend:** the lightest option possible. Leaning towards server-rendered pages with htmx, or Svelte. Decided later, not part of the early steps.
- The project folder and environment are already set up. Check what exists before creating anything.

## Overall architecture (for context only, built in later steps)

1. **Ingest:** fetch news from APIs and store it in our own database. The stored archive is the "memory".
2. **Group (classic ML):** embeddings and clustering group articles into the same issue.
3. **Understand (LLM):** extract structured events (who, what, when, action type, exact quote, source URL) from articles.
4. **Remember (graph in Postgres):** Issue -> Events -> People / Organizations / Places, with each event linked to its source articles.
5. **Show:** a timeline view per issue, status of the issue, and "no reports found since <date>".

Accuracy rules to keep in mind from the start: every event must be traceable to a source article, and we store attributed facts, not conclusions.

## Progress

Current state, how to run things, and the next step live in `PROGRESS.md` (imported below). Update it at the end of every step or session.

Problems live in `docs/ISSUES.md` and decisions in `docs/DECISIONS.md` (diagrams in `docs/WORKFLOW.md`). When you find or fix a problem, update `docs/ISSUES.md` in the same commit as the code. Record each decision the user makes in `docs/DECISIONS.md`. `/handoff` checks all of them at session end; `/status` reads them back.

@PROGRESS.md

## STEP 1: Fetch and store news

Goal: reliably fetch the latest news for the past 7 days and store it in PostgreSQL.

Requirements:
- Before building, compare and recommend a source: NewsAPI, GNews, GDELT, or RSS feeds. Check the current free-tier limits (history window, request limits, licensing) and give me a short recommendation. Since I am in India, check coverage of Indian outlets.
- Store per article: title, url, source name, published_at, fetched_at, language, short description/snippet, and a content hash. Do NOT store full article text for now (copyright). Links and metadata only.
- Dedupe by URL so running the fetch twice never creates duplicates (idempotent).
- Keep API keys in a `.env` file, never in code.
- A single command should run the fetch, for example `python -m app.fetch`.
- Handle rate limits, failed requests, and empty responses without crashing, and log what happened.
- Include a simple check, such as a script or query, that shows how many articles were stored and the date range covered.

Out of scope for this step: clustering, LLM extraction, graph, frontend, scheduling.

Start by looking at the existing project, then propose the source choice and the table design before writing code.