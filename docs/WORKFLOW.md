# Smriti: diagrams

_Last updated: 2026-10-20._ Where we stand in words: [`PROGRESS.md`](../PROGRESS.md). Problems: [`ISSUES.md`](ISSUES.md). Why things are the way they are: [`DECISIONS.md`](DECISIONS.md).

How the story model works, in reading order: grouping (section 3), the transformer inside it (section 4), how it learned (section 5), links and the graph (section 6). The decisions behind it: section 7.

## 1. Pipeline

Green = built. Yellow = testing or running. Grey = designed, not built. Red = blocked.

```mermaid
flowchart LR
    RSS["16 RSS feeds<br/>(15 outlets)"] --> F["app.fetch<br/>dedupe by URL"]
    GD["GDELT GKG bulk files<br/>60-day backfill (D-026)"] --> F
    F --> A[("articles<br/>138,229: Aug 21 – Oct 20")]
    A --> E["app.embed<br/>bge-m3, 1024-dim"]
    E --> V[("article_embeddings")]
    V --> G["app.group<br/>towers + fine-tuned<br/>cross-encoder (section 3)"]
    T["app.teach + app.train<br/>the LLM teaches the<br/>cross-encoder (section 5)"] --> G
    G --> I[("issues + article_issues<br/>= the stories")]
    I --> LK["app.links<br/>weight + LLM type (section 6)"]
    LK --> L[("issue_links<br/>= the edges")]
    I --> API["FastAPI<br/>app.api + app.moments<br/>key moments (D-030)"] --> UI["Svelte UI<br/>story path: dots to 'now'<br/>+ connected stories"]
    L --> API
    ML[("moment_labels<br/>AI labels, checked")] --> API

    A --> X["LLM extraction<br/>Qwen3-4B on GPU<br/>(I-002..I-005)"]
    X --> EV[("events + entities<br/>+ aliases")]
    EV -. "attach to the article's story (D-025)" .-> I

    classDef done fill:#d4edda,stroke:#2e7d32,color:#000
    classDef testing fill:#fff3cd,stroke:#b8860b,color:#000
    classDef planned fill:#eeeeee,stroke:#888,color:#000
    classDef blocked fill:#f8d7da,stroke:#c62828,color:#000
    class RSS,GD,F,A,E,V,T,G,I,LK,L,API,UI,ML done
    class X testing
    class EV planned
```

Run on all 60 days (2026-10-20, `logs/full_run.sh`): 72,591 stories and 10,390 links. Numbers in [`PROGRESS.md`](../PROGRESS.md); what is still wrong in section 2.

## 2. Issue board

IDs link to [`ISSUES.md`](ISSUES.md). P1 issues are marked with ★.

```mermaid
flowchart LR
    subgraph OPEN["Open"]
        direction TB
        I016["★ I-016<br/>one event, parallel stories"]
        I017["I-017<br/>blank titles, junk story"]
        I018["I-018<br/>similar incidents chain"]
        I019["I-019<br/>same article twice"]
        I005["I-005<br/>duplicate events"]
        I011["I-011<br/>old NVIDIA package"]
        I012["I-012<br/>git credential warning"]
    end
    subgraph PROG["In progress"]
        direction TB
        I001["★ I-001<br/>event vs issue clusters"]
        I002["★ I-002<br/>who errors"]
        I003["I-003<br/>action_type"]
        I004["I-004<br/>speculation as fact"]
        I015["I-015<br/>daily columns chain"]
    end
    subgraph BLOCK["Blocked"]
        direction TB
        NONE["(none)"]
    end
    subgraph DONE["Closed"]
        direction TB
        I006["I-006 quotes"]
        I007["I-007 Ollama OOM-killed"]
        I020["I-020 outlet names"]
        I021["I-021 stale 'no reports'"]
        I008["I-008 TECHNICAL.md"]
        I009["I-009 data stale"]
        I010["I-010 GDELT (won't fix)"]
        I013["I-013 Secure Boot"]
        I014["I-014 model too big"]
    end
    OPEN ~~~ PROG ~~~ BLOCK ~~~ DONE

    classDef p1 fill:#f8d7da,stroke:#c62828,color:#000
    classDef normal fill:#fff,stroke:#888,color:#000
    classDef closed fill:#d4edda,stroke:#2e7d32,color:#000
    class I016,I001,I002 p1
    class I017,I018,I019,I005,I011,I012,I003,I004,I015,NONE normal
    class I006,I007,I008,I009,I010,I013,I014,I020,I021 closed
```

## 3. How an article joins a story (built, D-024 and D-028)

`app.group` takes every article once, oldest first. An assigned article never moves, so story ids stay stable. The cut-offs (0.40, 0.92, 0.5) are provisional until the gold set measures them (D-027).

```mermaid
flowchart TD
    N["New article: title + snippet<br/>(oldest first)"] --> TA["Tower: bge-m3 turns it into<br/>a vector of 1024 numbers"]
    TA --> K["Cosine against the centre (centroid) of every story<br/>seen in the last 30 days, all at once on the GPU<br/>keep the 3 closest with cosine ≥ 0.40"]
    K --> Q1{"any candidate<br/>left?"}
    Q1 -- "no" --> NEW["Start a new story<br/>with this article"]
    Q1 -- "yes" --> Q2{"closest cosine ≥ 0.92?<br/>(near-duplicate)"}
    Q2 -- "yes" --> J1["Join that story<br/>(no cross-encoder needed)"]
    Q2 -- "no" --> CE["Fine-tuned cross-encoder reads the article<br/>together with each candidate's 3 latest headlines<br/>→ P(same story) for each candidate"]
    CE --> Q3{"best P ≥ 0.5?"}
    Q3 -- "yes" --> J2["Join the best story"]
    Q3 -- "no" --> NEW
    J1 --> SAVE[("article_issues<br/>story, cosine, P, model")]
    J2 --> SAVE
    NEW --> SAVE
    SAVE --> UPD["The story is updated: centroid = mean of its<br/>article vectors, latest headlines, first and last seen"]
```

- **Why two models:** the tower turns each text into a vector on its own, so one article is compared with every story centre in a single GPU step, but cosine only measures how alike two texts look. The cross-encoder reads the article and the story together, so it can tell two horoscopes (same topic) from two reports of the same flood (same story). It costs about 0.1 s per article, so it only sees the 3 candidates.
- **What gets stored:** `article_issues` keeps each article's story, the tower cosine, and the cross-encoder probability and model (empty when the towers decided alone). A story's timeline is its articles by date.
- **Known problems:** one event can still split into parallel stories (I-016); the daily-column chains (I-015) look fixed by the fine-tuned model.

## 4. Inside the transformer

Both models are the same kind of transformer (XLM-RoBERTa-large). The difference is what goes in and what comes out.

```mermaid
flowchart TD
    subgraph BI["Towers (bi-encoder, bge-m3): each text alone"]
        direction TB
        A1["Article text"] --> T1["Transformer encoder"] --> P1["article vector<br/>1024 numbers"]
        S1["The story's articles"] --> T2["Same encoder,<br/>same weights"] --> P2["their vectors averaged<br/>= story centroid"]
        P1 --> COS["cosine: how alike they look<br/>fast, centroids kept on the GPU"]
        P2 --> COS
    end
    subgraph CR["Cross-encoder (bge-reranker-v2-m3, fine-tuned): both texts together"]
        direction TB
        J["[CLS] article [SEP] story's 3 latest headlines [SEP]"] --> T3["Transformer encoder<br/>self-attention runs across both texts"]
        T3 --> CLS["[CLS] vector"] --> H["Head: one number<br/>sigmoid → P(same story), 0 to 1"]
    end
```

What happens inside one encoder (numbers for `bge-m3` / `bge-reranker-v2-m3`, XLM-RoBERTa-large):

```mermaid
flowchart LR
    TXT["Text"] --> TOK["Tokenizer<br/>250k-word vocabulary"] --> EMB["Token + position<br/>embeddings, 1024-dim"]
    EMB --> ATT
    subgraph LAYER["Transformer layer, repeated 24 times"]
        direction TB
        ATT["Multi-head self-attention, 16 heads<br/>Query · Key → attention weights → mix of Values"] --> N1["Add + LayerNorm"]
        N1 --> FF["Feed-forward<br/>1024 → 4096 → 1024"] --> N2["Add + LayerNorm"]
    end
    N2 --> POOL["Pooling<br/>[CLS] vector"] --> HEAD["Task head"]
```

- **Self-attention:** every token looks at every other token, left and right. In the cross-encoder, "trains cancelled" in the article can attend to "CJP protest" in the story; with cosine the two texts never see each other.
- **Fine-tuning (D-028):** only the cross-encoder's top 4 layers (21 to 24) and its head were trained, on the teacher's labels (section 5), with binary cross-entropy: same story or not. Layers 1 to 20 stay frozen, which keeps training inside the 4 GB GPU (about 10 minutes for 3,000 pairs). The towers are used as downloaded.
- **Same model, two jobs:** grouping uses the fine-tuned cross-encoder ("same story?"). Links use the original, zero-shot one, because a link can be any connection, not only the same story (section 6).

## 5. How the model gets built (G-1 to G-7)

The LLM is too slow to judge every article, so it teaches the cross-encoder instead (teacher-student, D-028): it labels pairs once, offline, with the gold-set rules, and the cross-encoder learns to copy it.

```mermaid
flowchart LR
    P["app.teach samples 3,000 article pairs<br/>40% nearest: an article and its closest one within 3 days<br/>10% high cosine (0.6 – 0.95), 40% middle (0.4 – 0.6)<br/>10% low (below 0.4, sharing a rare title word)<br/>never a gold pair"] --> T["Teacher: Qwen3-4B (local LLM)<br/>labels each pair by the gold-set rules<br/>0.9 s per pair"]
    T --> D[("train_pairs<br/>3,000 labels, 20% same_story")]
    D --> S["Student: bge-reranker-v2-m3 (app.train)<br/>learns same story yes / no<br/>top 4 layers + head, 2 epochs"]
    S --> C{"better than before<br/>on the 10% held out?"}
    C -- "no" --> STOP["not saved, the run stops"]
    C -- "yes: AUC 0.908 → 0.967<br/>accuracy 0.86 → 0.931" --> M[("models/ce-same-story")]
    M --> G["app.group decides with it<br/>(section 3)"]
    GOLD[("gold_pairs: 200 pairs<br/>labelled by Claude (D-029)")] -. "measures only, never trains" .-> CMP["app.compare: cosine, TF-IDF,<br/>zero-shot models, LLM, student"]
    M -.-> CMP
```

The held-out check compares the student with the teacher's labels: it shows the student copies the teacher well, not that the teacher is right. The gold set is the real test (G-3). Claude labelled it, not the teacher, so the test stays independent of what the student learned (D-029). Retraining reuses the stored labels: the LLM only labels new pairs, and the student is trained again from the original model on all of them.

The build order changed (D-027, D-028): the pipeline and the fine-tuning came first; the gold set now measures them.

```mermaid
flowchart LR
    G1["G-1 Backfill<br/>GDELT, 60 days"] --> G4["G-4 Teacher labels<br/>LLM labels 3,000 pairs"]
    G4 --> G5["G-5 Fine-tune<br/>cross-encoder, top 4 layers"]
    G5 --> G6["G-6 Graph tables<br/>model groups + links"]
    G6 --> G7["G-7 UI<br/>timeline + connected stories"]
    G7 --> G2["G-2 Gold set<br/>200 pairs, labelled<br/>by Claude (D-029)"]
    G2 --> G3["G-3 Compare<br/>every model on the gold set"]
    G3 --> CHK{"student beats<br/>the baselines?"}
    CHK -- "no" --> G4
    CHK -- "yes: AUC 0.966,<br/>cosine 0.918" --> CUT["Set the cut-offs on the gold set<br/>student's best 0.485: keep 0.5"]

    classDef done fill:#d4edda,stroke:#2e7d32,color:#000
    classDef testing fill:#fff3cd,stroke:#b8860b,color:#000
    classDef planned fill:#eeeeee,stroke:#888,color:#000
    class G1,G4,G5,G6,G7,G2,G3,CHK done
    class CUT testing
```

## 6. Links and the graph in Postgres (built, G-6)

Stories are the nodes, `issue_links` rows are the edges (D-006, D-011, D-024). `app.links` runs after `app.group`:

```mermaid
flowchart TD
    S["Every story with 2 or more articles"] --> NN["Towers: its 5 closest other stories<br/>centroid cosine ≥ 0.5, at most 30 days apart"]
    NN --> W["Cross-encoder (zero-shot) reads<br/>both stories' 3 latest headlines<br/>→ probability = the link's weight"]
    W --> K{"weight ≥ 0.2?"}
    K -- "no" --> DROP["no edge"]
    K -- "yes" --> L[("issue_links: older → newer story<br/>type 'related', weight, model")]
    L --> NAME["app.links --types N: the LLM names the N strongest<br/>same_story / follow_up / same_actor / same_topic / unrelated<br/>+ a one-line reason, stored as evidence"]
    NAME --> L
```

Full run (2026-10-20): the 14,782 stories with 2 or more articles gave 62,039 candidate pairs, and 10,390 links were kept. The LLM named the 500 strongest: same_topic 330, unrelated 70, same_story 66, same_actor 34, follow_up 0. The strongest links are mostly look-alikes (market updates, horoscopes): the weight comes from the cross-encoder before fine-tuning (`BAAI/bge-reranker-v2-m3`), which rates look-alikes high.

Walking the graph: a story's page (`GET /api/issues/{id}`) shows the stories linked to it in either direction, strongest first, up to 20, with links named `unrelated` hidden. Each one opens that story's page, with its own links, so you walk the graph one hop at a time. A multi-hop query (`WITH RECURSIVE` over `issue_links`) is planned.

```mermaid
flowchart LR
    A(["Story A<br/>timeline of its articles"]) -- "type + weight + reason" --> B(["Story B"])
    B -- "its own links" --> C(["Story C"])
    A -- "type + weight + reason" --> D(["Story D"])
```

The tables:

```mermaid
erDiagram
    articles ||--o| article_issues : "belongs to"
    issues ||--o{ article_issues : "has"
    issues ||--o{ issue_links : "links from"
    issues ||--o{ issue_links : "links to"
    issues {
        bigint id
        text label "headline nearest the centroid"
        vector centroid "mean of the article vectors"
        int article_count
        timestamptz first_seen
        timestamptz last_seen
    }
    article_issues {
        bigint article_id
        bigint issue_id
        real similarity "tower cosine when assigned"
        real probability "cross-encoder P, empty if the towers decided"
        text model
    }
    issue_links {
        bigint from_issue
        bigint to_issue
        real weight "cross-encoder probability"
        text link_type "related until the LLM names it"
        text evidence "the LLM's one-line reason"
        text model
        text typed_by
    }
```

## 7. The decisions behind this (D-023 to D-029)

All taken 2026-10-20. Full text in [`DECISIONS.md`](DECISIONS.md).

```mermaid
flowchart TD
    OLD["Before: MiniLM cosine ≥ 0.70 grouped articles;<br/>the plan was for the LLM to judge every merge (D-007 to D-014)<br/>Result: the CJP protest split into 87 'issues' (I-001)"]
    OLD --> D23["D-023 [MVP] Story grouping is the core:<br/>stories as a connected graph you can walk"]
    D23 --> D24["D-024 [MVP] Towers find candidates, a cross-encoder decides<br/>and weighs links; the LLM only labels and names"]
    D24 --> D25["D-025 [MVP] The unit is the article (title + snippet),<br/>not extracted events"]
    D25 --> D26["D-026 60 days of data from GDELT bulk files"]
    D26 --> D27["D-027 [MVP] Build the whole pipeline now<br/>with pretrained models, measure after"]
    D27 --> D28["D-028 [MVP] Fine-tune the cross-encoder now:<br/>the LLM teaches it with 3,000 labelled pairs"]
    D28 --> D29["D-029 Claude labels the gold set,<br/>not the LLM that taught the student"]
```
