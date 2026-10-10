"""Review how articles were grouped.

Run with:  python -m app.issues              (summary + biggest issues)
           python -m app.issues --top 30
           python -m app.issues --id 42      (every article in one issue)
"""

import argparse

from app.db import connect

HEADLINES_PER_ISSUE = 6


def show_summary(conn, top: int) -> None:
    total, singles, biggest, articles = conn.execute("""
        SELECT count(*), count(*) FILTER (WHERE article_count = 1),
               max(article_count), coalesce(sum(article_count), 0)
        FROM issues
    """).fetchone()
    print(f"\n{articles} articles in {total} issues "
          f"({singles} single-article issues, largest has {biggest or 0} articles)\n")

    issues = conn.execute("""
        SELECT i.id, i.label, i.article_count, i.first_seen, i.last_seen,
               count(DISTINCT a.source_name) AS sources
        FROM issues i
        JOIN article_issues ai ON ai.issue_id = i.id
        JOIN articles a ON a.id = ai.article_id
        WHERE i.article_count > 1
        GROUP BY i.id
        ORDER BY i.article_count DESC, i.last_seen DESC
        LIMIT %s
    """, (top,)).fetchall()
    for issue_id, label, count, first, last, sources in issues:
        print(f"#{issue_id}  {label}")
        print(f"     {count} articles, {sources} sources, {first:%b %d} - {last:%b %d}")
        for title, source, sim in headlines(conn, issue_id, HEADLINES_PER_ISSUE):
            print(f"       {sim:.2f}  [{source}] {title[:100]}")
        if count > HEADLINES_PER_ISSUE:
            print(f"       ... {count - HEADLINES_PER_ISSUE} more")
        print()


def headlines(conn, issue_id: int, limit: int | None = None):
    return conn.execute("""
        SELECT a.title, a.source_name, ai.similarity
        FROM article_issues ai JOIN articles a ON a.id = ai.article_id
        WHERE ai.issue_id = %s
        ORDER BY coalesce(a.published_at, a.fetched_at)
        LIMIT %s
    """, (issue_id, limit)).fetchall()


def show_issue(conn, issue_id: int) -> None:
    row = conn.execute("SELECT label, article_count FROM issues WHERE id = %s", (issue_id,)).fetchone()
    if not row:
        print(f"No issue #{issue_id}")
        return
    print(f"\n#{issue_id}  {row[0]}  ({row[1]} articles)\n")
    for title, source, sim in headlines(conn, issue_id):
        print(f"  {sim:.2f}  [{source}] {title}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Review issues.")
    parser.add_argument("--top", type=int, default=15, help="how many issues to show (default 15)")
    parser.add_argument("--id", type=int, help="show every article in one issue")
    args = parser.parse_args()
    with connect() as conn:
        if args.id:
            show_issue(conn, args.id)
        else:
            show_summary(conn, args.top)


if __name__ == "__main__":
    main()
