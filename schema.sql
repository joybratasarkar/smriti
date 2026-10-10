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

-- Step 2: group articles into issues.
-- The vector extension must be created once by a superuser:
--   sudo -u postgres psql -p 5433 -d smriti -c "CREATE EXTENSION vector;"
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS article_embeddings (
    article_id  BIGINT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    model       TEXT NOT NULL,              -- so we can re-embed if the model changes
    embedding   vector(384) NOT NULL,       -- L2-normalized
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS issues (
    id             BIGSERIAL PRIMARY KEY,
    label          TEXT NOT NULL,           -- headline of the most central article, for now
    centroid       vector(384) NOT NULL,    -- mean of member embeddings
    article_count  INT NOT NULL DEFAULT 0,
    first_seen     TIMESTAMPTZ NOT NULL,    -- earliest member article's date
    last_seen      TIMESTAMPTZ NOT NULL,    -- latest member article's date
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS issues_last_seen_idx ON issues (last_seen);

CREATE TABLE IF NOT EXISTS article_issues (     -- relation table: article -> issue
    article_id  BIGINT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    issue_id    BIGINT NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    similarity  REAL NOT NULL,              -- cosine similarity to the issue when assigned
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS article_issues_issue_idx ON article_issues (issue_id);
