# Smriti: what has been built and decided so far

_Snapshot: 2026-10-10. For day-to-day state and commands, see `PROGRESS.md`._

Smriti remembers the news. It follows one issue over time (what happened, who acted, what is still open) and links every fact to its source article.

## 1. The whole pipeline at a glance

Green = built and working. Yellow = being tested now. Grey = designed, not built yet.

```mermaid
flowchart LR
    RSS["16 RSS feeds<br/>(15 Indian outlets)"] --> F["app.fetch<br/>dedupe by URL"]
    F --> A[("articles<br/>1,053 rows")]
    A --> E["app.embed<br/>MiniLM, 384-dim"]
    E --> V[("article_embeddings")]
    V --> G["app.group<br/>cosine ≥ 0.70"]
    G --> I[("issues<br/>795 rows")]
    I --> API["FastAPI<br/>app.api"] --> UI["Svelte UI<br/>timeline per issue"]

    A --> X["LLM extraction<br/>Qwen3-4B on GPU"]
    X --> EV[("events + entities<br/>+ aliases")]
    EV --> M["Merge events into issues<br/>candidates + LLM judge"]
    M --> I

    classDef done fill:#d4edda,stroke:#2e7d32,color:#000
    classDef testing fill:#fff3cd,stroke:#b8860b,color:#000
    classDef planned fill:#eeeeee,stroke:#888,color:#000
    class RSS,F,A,E,V,G,I,API,UI done
    class X testing
    class EV,M planned
```

## 2. Timeline of the work

```mermaid
flowchart TD
    S1["Step 1: Ingest<br/>Compared NewsAPI, GNews, GDELT, RSS.<br/>Chose RSS: free, best Indian coverage.<br/>GDELT kept opt-in (constant 429s)."]
    S2["Step 2: Group<br/>Embeddings + cosine similarity.<br/>Articles join the nearest issue<br/>active in the last 14 days."]
    WEB["Read-only web app<br/>API + Svelte timeline,<br/>'no reports since &lt;date&gt;'"]
    P["Problem found<br/>Clusters are events, not issues:<br/>87 'issues' are all the same<br/>CJP / Jantar Mantar protest"]
    D["Design: grilling rounds 1 and 2<br/>Embeddings only find candidates.<br/>Structured facts + LLM decide merges."]
    LLM["LLM choice<br/>Local model on GPU via Ollama,<br/>not a paid API"]
    GPU["GPU fix<br/>nvidia-595 driver, MOK key enrolled<br/>(Secure Boot), Ollama 0.1.38 → 0.40.2"]
    T["Model test on CJP articles<br/>Qwen3.5-4B too big for 4 GB.<br/>Swapped to Qwen3-4B-Instruct-2507."]
    NEXT["Next: build extraction<br/>into real tables"]

    S1 --> S2 --> WEB --> P --> D --> LLM --> GPU --> T --> NEXT
```

## 3. Why the design changed

Similarity alone gives clusters at the **event** level ("trains cancelled for protest"), not the **issue** level ("the CJP protest against the CEC"). One story was split into 87 issues.

New approach: embeddings only **suggest** candidates. Structured facts plus an LLM **decide**.

```mermaid
flowchart TD
    N["New article"] --> NE{"cosine ≥ 0.90 to an<br/>existing event?"}
    NE -- yes --> JOIN["Join that event<br/>(near-duplicate, automatic)"]
    NE -- no --> NEWEV["New event"]
    JOIN --> C
    NEWEV --> C["Find candidate issues<br/>(active in last 30 days):<br/>cosine ≥ ~0.45 to any event<br/>OR a shared person/org"]
    C --> TOP["Top 5 candidates"]
    TOP --> J["LLM judge:<br/>same ongoing story?"]
    J -- same --> MERGE["Merge whole event into issue.<br/>Store verdict, reason,<br/>evidence, model. Reversible."]
    J -- different --> NEWI["New issue"]
```

## 4. Decisions so far (grilling rounds 1 and 2)

| # | Question | Decision |
|---|---|---|
| 1 | When to merge automatically? | Only near-duplicates (cosine ≥ 0.90) join an event automatically. Every issue-level merge goes to the LLM. |
| 2 | What is a candidate? | Cosine ≥ ~0.45 to any event of the issue, or at least one shared key person/org. Only issues active in the last 30 days. Top 5 go to the LLM. |
| 3 | Which signals matter most? | People and orgs are strong signals. Places, action types and dates are context for the LLM, never filters. |
| 4 | Who decides? | The LLM, automatically. Verdict, reason, evidence and model are stored. Every merge can be undone. |
| 5 | Graph storage | Typed Postgres tables (`issues`, `events`, `entities`) plus link tables. No graph database. |
| 7 | Full article text? | Fetched at extraction time, given to the LLM, then discarded. Only facts, the exact quote and the URL are stored. |
| 8 | What is one issue? | The same ongoing story: same core dispute or demand, same main people/orgs, over time. A different group's protest at the same place is a different issue. |
| 9 | What does the LLM compare? | A whole event (all its articles) against an issue, one call per event. The event's articles move together. |
| 10 | Same person, different spellings? | `entities` (one row per real person/org) plus `entity_aliases` (every spelling seen). Start with exact match on normalized text. |

## 5. The LLM and GPU story

```mermaid
flowchart LR
    A["Goal: local LLM,<br/>free, private"] --> B["Blocker: Secure Boot<br/>rejected NVIDIA driver"]
    B --> C["Fixed: MOK key enrolled,<br/>nvidia-smi works"]
    C --> D["Ollama upgraded<br/>to 0.40.2"]
    D --> E["Qwen3.5-4B:<br/>65% GPU, ~120 s/article"]
    E --> F["Qwen3-4B-Instruct-2507,<br/>forced 100% GPU:<br/>~50 s/article"]
    F --> G["Cap at 5 events:<br/>~22 s/article"]
```

Hardware limit: GTX 1650 with 4 GB VRAM and 7.1 GB system RAM, so models above ~4B parameters don't fit.

Settings that make the model fit fully on the GPU (sent with every request): `num_ctx` 4096, `num_gpu` 99, thinking off, JSON-schema-constrained output.

## 6. Latest test result (30 CJP articles)

Command: `python -m app.llm_test`. Per-article output: `logs/llm_test_2026-10-10.jsonl`.

| Measure | Result |
|---|---|
| Full text fetched | 30 / 30 |
| Valid JSON | 24 / 24 that ran (6 failed because the Ollama service restarted mid-run, not a model fault) |
| Quotes found word for word in the article | 89 / 116 (77%) |
| Seconds per article | 22.2 |
| On GPU | 100% |

Still to check by hand: whether `who` and `what` are correct on about 10 articles.

## 7. What comes next

1. Check about 10 extracted articles by hand for field accuracy.
2. Decide what to do with quotes that are not word for word: drop the event, or keep it without a quote.
3. Add the `events`, `entities`, `entity_aliases` and link tables to `schema.sql`.
4. Build the real extraction step, then the candidate-and-judge merge.
