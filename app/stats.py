"""Show what is stored: counts and date range.

Run with:  python -m app.stats
"""

from app.db import connect

QUERIES = {
    "Totals": """
        SELECT count(*) AS articles,
               count(DISTINCT url) AS unique_urls,
               min(published_at) AS oldest_published,
               max(published_at) AS newest_published,
               count(*) FILTER (WHERE published_at IS NULL) AS no_date,
               max(fetched_at) AS last_fetched
        FROM articles
    """,
    "By provider": """
        SELECT provider, count(*) AS articles,
               count(snippet) AS with_snippet,
               min(published_at) AS oldest, max(published_at) AS newest
        FROM articles GROUP BY provider ORDER BY provider
    """,
    "By day (published, UTC)": """
        SELECT published_at::date AS day, count(*) AS articles,
               count(*) FILTER (WHERE provider = 'rss') AS rss,
               count(*) FILTER (WHERE provider = 'gdelt') AS gdelt
        FROM articles WHERE published_at IS NOT NULL
        GROUP BY day ORDER BY day
    """,
    "Top 20 sources": """
        SELECT source_name, provider, count(*) AS articles
        FROM articles GROUP BY source_name, provider
        ORDER BY articles DESC LIMIT 20
    """,
    "By language": """
        SELECT coalesce(language, '(unknown)') AS language, count(*) AS articles
        FROM articles GROUP BY language ORDER BY articles DESC LIMIT 15
    """,
}


def print_table(cursor) -> None:
    headers = [col.name for col in cursor.description]
    rows = [["" if v is None else str(v)[:19] for v in row] for row in cursor.fetchall()]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    print("  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    for row in rows:
        print("  " + "  ".join(v.ljust(w) for v, w in zip(row, widths)))


def main() -> None:
    with connect() as conn, conn.cursor() as cur:
        for title, sql in QUERIES.items():
            print(f"\n{title}")
            cur.execute(sql)
            print_table(cur)
    print()


if __name__ == "__main__":
    main()
