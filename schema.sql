-- Step 1: news articles (links and metadata only, no full text).
CREATE TABLE IF NOT EXISTS articles (
    id            BIGSERIAL PRIMARY KEY,
    url           TEXT NOT NULL UNIQUE,      -- normalized: no tracking params or #fragment
    title         TEXT NOT NULL,
    snippet       TEXT,                      -- short description from RSS; NULL for GDELT
    source_name   TEXT NOT NULL,             -- e.g. "The Hindu"
    source_domain TEXT NOT NULL,             -- e.g. "thehindu.com"
    language      TEXT,                      -- ISO 639-1 code where known, e.g. "en", "hi"
    published_at  TIMESTAMPTZ,               -- RSS: publisher's date. GDELT: first-seen time.
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_hash  TEXT NOT NULL,             -- sha256 of normalized title + snippet
    provider      TEXT NOT NULL              -- 'rss' or 'gdelt'
);

CREATE INDEX IF NOT EXISTS articles_published_at_idx ON articles (published_at);
CREATE INDEX IF NOT EXISTS articles_content_hash_idx ON articles (content_hash);

CREATE TABLE IF NOT EXISTS gdelt_files (        -- GDELT GKG files already read, so reruns skip them
    stamp       TIMESTAMPTZ PRIMARY KEY,        -- the file's 15-minute timestamp (UTC)
    articles    INT NOT NULL,                   -- rows kept from our outlets
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Step 2: group articles into issues.
-- The vector extension must be created once by a superuser:
--   sudo -u postgres psql -p 5433 -d smriti -c "CREATE EXTENSION vector;"
CREATE EXTENSION IF NOT EXISTS vector;

-- D-024: the MiniLM vectors (384-dim) were replaced by bge-m3 (1024-dim). Vectors and the issues
-- built from them are derived data, so they are dropped once; app.embed and app.group rebuild them.
DO $$
BEGIN
    IF (SELECT atttypmod FROM pg_attribute
        WHERE attrelid = to_regclass('article_embeddings') AND attname = 'embedding') = 384 THEN
        DROP TABLE article_embeddings, article_issues, issues CASCADE;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS article_embeddings (
    article_id  BIGINT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    model       TEXT NOT NULL,              -- so we can re-embed if the model changes
    embedding   vector(1024) NOT NULL,      -- bge-m3, L2-normalized
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS issues (
    id             BIGSERIAL PRIMARY KEY,
    label          TEXT NOT NULL,           -- headline of the most central article, for now
    centroid       vector(1024) NOT NULL,   -- mean of member embeddings
    article_count  INT NOT NULL DEFAULT 0,
    first_seen     TIMESTAMPTZ NOT NULL,    -- earliest member article's date
    last_seen      TIMESTAMPTZ NOT NULL,    -- latest member article's date
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS issues_last_seen_idx ON issues (last_seen);

CREATE TABLE IF NOT EXISTS article_issues (     -- relation table: article -> issue
    article_id  BIGINT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    issue_id    BIGINT NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    similarity  REAL NOT NULL,              -- tower (bge-m3) cosine to the issue when assigned
    probability REAL,                       -- cross-encoder P(same story); NULL when the towers decided alone
    model       TEXT,                       -- the cross-encoder that decided; NULL when none did
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS article_issues_issue_idx ON article_issues (issue_id);

-- G-6: weighted links between stories (app/links.py). from_issue is the older story.
CREATE TABLE IF NOT EXISTS issue_links (
    from_issue  BIGINT NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    to_issue    BIGINT NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    weight      REAL NOT NULL,              -- cross-encoder probability that the two stories are connected
    link_type   TEXT NOT NULL DEFAULT 'related'   -- 'related' until the LLM names the type
                CHECK (link_type IN ('related', 'same_story', 'follow_up', 'same_actor', 'same_topic', 'unrelated')),
    evidence    TEXT,                       -- the LLM's one-line reason
    model       TEXT NOT NULL,              -- the cross-encoder that weighed it
    typed_by    TEXT,                       -- the LLM that named the type
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (from_issue, to_issue),
    CHECK (from_issue <> to_issue)
);

CREATE INDEX IF NOT EXISTS issue_links_to_idx ON issue_links (to_issue);

-- G-2: article pairs labelled by hand; only used to measure grouping models (app/gold.py).
CREATE TABLE IF NOT EXISTS gold_pairs (
    id          BIGSERIAL PRIMARY KEY,
    article_a   BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    article_b   BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    stratum     TEXT NOT NULL,              -- high / middle / low cosine band
    cosine      REAL NOT NULL,              -- tower (bge-m3) cosine when sampled
    label       TEXT CHECK (label IN ('same_story', 'follow_up', 'same_actor', 'same_topic', 'unrelated', 'unsure')),
    labeled_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (article_a < article_b),
    UNIQUE (article_a, article_b)
);

-- G-4: article pairs labelled by the LLM judge (the teacher), to fine-tune the cross-encoder (app/teach.py).
-- Never the same pair as in gold_pairs.
CREATE TABLE IF NOT EXISTS train_pairs (
    id          BIGSERIAL PRIMARY KEY,
    article_a   BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    article_b   BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    stratum     TEXT NOT NULL,              -- high / middle / low cosine band, as in gold_pairs
    cosine      REAL NOT NULL,              -- tower (bge-m3) cosine when sampled
    label       TEXT CHECK (label IN ('same_story', 'follow_up', 'same_actor', 'same_topic', 'unrelated')),
    labeled_by  TEXT,                       -- the LLM that labelled it
    labeled_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (article_a < article_b),
    UNIQUE (article_a, article_b)
);

-- D-030: short labels for the key moments on a story's timeline path (app/moments.py). Moments are computed on
-- request; a label is keyed by the moment's articles, so it stops applying when the moment changes.
CREATE TABLE IF NOT EXISTS moment_labels (
    moment_key  TEXT PRIMARY KEY,           -- md5 of the moment's sorted article ids
    issue_id    BIGINT NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,              -- 4 to 7 words, checked against the moment's headlines
    model       TEXT NOT NULL,              -- the LLM that wrote it
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- D-032: clean titles for the stories on the front page (app/front.py). Keyed like moment_labels, by the story's
-- newest moment, so a title is rewritten only when the story gets a new newest dot. No foreign key to issues:
-- `app.group --reset` truncates issues, and a title still fits the same articles after a regroup.
CREATE TABLE IF NOT EXISTS story_titles (
    moment_key  TEXT PRIMARY KEY,           -- md5 of the newest moment's sorted article ids
    title       TEXT NOT NULL,              -- 5 to 9 words, checked against the story's main headlines
    model       TEXT NOT NULL,              -- the LLM that wrote it
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- D-042: a 2-sentence summary per front-page story (what it is about, then the latest), keyed like story_titles.
CREATE TABLE IF NOT EXISTS story_summaries (
    moment_key  TEXT PRIMARY KEY,           -- md5 of the newest moment's sorted article ids
    summary     TEXT NOT NULL,              -- each sentence checked against the headlines it was written from
    model       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- D-036: news categories. The LLM labels a sample of articles (keyed by article, so labels survive a regroup);
-- app.categories fits a small classifier on their bge-m3 vectors and writes every story's category and region.
CREATE TABLE IF NOT EXISTS article_categories (
    article_id  BIGINT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    category    TEXT NOT NULL,              -- one of app.categories.CATEGORIES
    region      TEXT NOT NULL CHECK (region IN ('India', 'World')),
    model       TEXT NOT NULL,              -- the LLM that labelled it
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE issues ADD COLUMN IF NOT EXISTS category TEXT;   -- predicted by app.categories; NULL until it runs
ALTER TABLE issues ADD COLUMN IF NOT EXISTS region TEXT;     -- 'India' or 'World'
ALTER TABLE issues ADD COLUMN IF NOT EXISTS category_by TEXT; -- 'llm' (front-page stories) or 'classifier'

-- app.links: md5 of the cross-encoder name and the latest headlines it last weighed this story by, so a rerun
-- only weighs pairs where one of the two stories changed (the weight of an unchanged pair is the same).
ALTER TABLE issues ADD COLUMN IF NOT EXISTS links_key TEXT;
