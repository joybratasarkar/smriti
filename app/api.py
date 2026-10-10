"""Read-only JSON API for the frontend.

Run with:  uvicorn app.api:app --reload --port 8010
"""

from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Query
from psycopg.rows import dict_row

from app.db import connect

app = FastAPI(title="Smriti API")


@contextmanager
def db():
    with connect() as conn:
        conn.row_factory = dict_row
        yield conn


@app.get("/api/summary")
def summary():
    with db() as conn:
        return conn.execute("""
            SELECT (SELECT count(*) FROM articles) AS articles,
                   (SELECT count(*) FROM issues) AS issues,
                   (SELECT count(*) FROM issues WHERE article_count > 1) AS multi_article_issues,
                   (SELECT count(DISTINCT source_name) FROM articles) AS sources,
                   (SELECT min(published_at) FROM articles) AS oldest,
                   (SELECT max(published_at) FROM articles) AS newest,
                   (SELECT max(fetched_at) FROM articles) AS last_fetched
        """).fetchone()


@app.get("/api/issues")
def list_issues(
    sort: str = Query("recent", pattern="^(recent|biggest)$"),
    min_size: int = Query(2, ge=1),
    q: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    order = "i.last_seen DESC" if sort == "recent" else "i.article_count DESC, i.last_seen DESC"
    with db() as conn:
        rows = conn.execute(f"""
            SELECT i.id, i.label, i.article_count, i.first_seen, i.last_seen,
                   count(DISTINCT a.source_name) AS source_count,
                   array_agg(DISTINCT a.source_name) AS sources,
                   count(*) OVER () AS total
            FROM issues i
            JOIN article_issues ai ON ai.issue_id = i.id
            JOIN articles a ON a.id = ai.article_id
            WHERE i.article_count >= %(min_size)s
              AND (%(q)s = '' OR i.id IN (
                    SELECT ai2.issue_id FROM article_issues ai2
                    JOIN articles a2 ON a2.id = ai2.article_id
                    WHERE a2.title ILIKE '%%' || %(q)s || '%%'))
            GROUP BY i.id
            ORDER BY {order}
            LIMIT %(limit)s OFFSET %(offset)s
        """, {"min_size": min_size, "q": q.strip(), "limit": limit, "offset": offset}).fetchall()
    total = rows[0]["total"] if rows else 0
    for row in rows:
        del row["total"]
    return {"total": total, "issues": rows}


@app.get("/api/issues/{issue_id}")
def get_issue(issue_id: int):
    with db() as conn:
        issue = conn.execute("""
            SELECT id, label, article_count, first_seen, last_seen
            FROM issues WHERE id = %s
        """, (issue_id,)).fetchone()
        if not issue:
            raise HTTPException(404, "Issue not found")
        issue["articles"] = conn.execute("""
            SELECT a.id, a.title, a.url, a.snippet, a.source_name, a.language,
                   coalesce(a.published_at, a.fetched_at) AS published_at, ai.similarity
            FROM article_issues ai JOIN articles a ON a.id = ai.article_id
            WHERE ai.issue_id = %s
            ORDER BY coalesce(a.published_at, a.fetched_at), a.id
        """, (issue_id,)).fetchall()
    return issue
