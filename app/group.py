"""Assign embedded articles to issues.

Run with:  python -m app.group                  (assign new articles)
           python -m app.group --threshold 0.7
           python -m app.group --reset          (delete all issues and regroup from scratch)

Each unassigned article, oldest first, joins the most similar issue active in the
last WINDOW_DAYS days if the similarity is at least the threshold; otherwise it
starts a new issue. Already-assigned articles never move, so issue ids stay stable.
"""

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from app.db import connect_with_vectors

DEFAULT_THRESHOLD = 0.70  # tuned on Oct 3-10 2026 articles; see app.issues to review
WINDOW_DAYS = 14

log = logging.getLogger("group")


@dataclass
class Issue:
    id: int | None          # None until saved
    centroid: np.ndarray    # mean of member embeddings
    count: int
    first_seen: datetime
    last_seen: datetime
    label: str


def best_match(issues: list[Issue], vector: np.ndarray, when: datetime) -> tuple[int, float]:
    """Index and cosine similarity of the closest issue active around `when`, or (-1, 0)."""
    since = when - timedelta(days=WINDOW_DAYS)
    candidates = [i for i, issue in enumerate(issues) if issue.last_seen >= since]
    if not candidates:
        return -1, 0.0
    centroids = np.array([issues[i].centroid for i in candidates])
    sims = centroids @ vector / np.linalg.norm(centroids, axis=1)
    best = int(np.argmax(sims))
    return candidates[best], float(sims[best])


def assign(issues: list[Issue], articles, threshold: float) -> list[tuple[int, int, float]]:
    """Group articles (id, title, when, vector) into issues, updating `issues` in place.

    Returns (article_id, index into issues, similarity) for every article.
    Pure in-memory logic, so it can be tried with different thresholds without touching the DB.
    """
    assignments = []
    for article_id, title, when, vector in articles:
        idx, sim = best_match(issues, vector, when)
        if idx >= 0 and sim >= threshold:
            issue = issues[idx]
            issue.centroid = (issue.centroid * issue.count + vector) / (issue.count + 1)
            issue.count += 1
            issue.first_seen = min(issue.first_seen, when)
            issue.last_seen = max(issue.last_seen, when)
        else:
            issues.append(Issue(None, vector.copy(), 1, when, when, title))
            idx, sim = len(issues) - 1, 1.0
        assignments.append((article_id, idx, sim))
    return assignments


def as_array(vector) -> np.ndarray:
    return vector.to_numpy().astype(np.float64)


def load_unassigned(conn):
    rows = conn.execute("""
        SELECT a.id, a.title, coalesce(a.published_at, a.fetched_at) AS ts, e.embedding
        FROM articles a
        JOIN article_embeddings e ON e.article_id = a.id
        LEFT JOIN article_issues ai ON ai.article_id = a.id
        WHERE ai.article_id IS NULL
        ORDER BY ts, a.id
    """).fetchall()
    return [(article_id, title, ts, as_array(vec)) for article_id, title, ts, vec in rows]


def load_recent_issues(conn, since: datetime) -> list[Issue]:
    rows = conn.execute("""
        SELECT id, centroid, article_count, first_seen, last_seen, label
        FROM issues WHERE last_seen >= %s
    """, (since,)).fetchall()
    return [Issue(issue_id, as_array(centroid), count, first, last, label)
            for issue_id, centroid, count, first, last, label in rows]


def save(conn, issues: list[Issue], assignments, touched: set[int]) -> None:
    with conn.cursor() as cur:
        for idx in touched:
            issue = issues[idx]
            centroid = issue.centroid.astype(np.float32)
            if issue.id is None:
                cur.execute("""
                    INSERT INTO issues (label, centroid, article_count, first_seen, last_seen)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                """, (issue.label, centroid, issue.count, issue.first_seen, issue.last_seen))
                issue.id = cur.fetchone()[0]
            else:
                cur.execute("""
                    UPDATE issues SET centroid = %s, article_count = %s, first_seen = %s, last_seen = %s
                    WHERE id = %s
                """, (centroid, issue.count, issue.first_seen, issue.last_seen, issue.id))

        cur.executemany(
            "INSERT INTO article_issues (article_id, issue_id, similarity) VALUES (%s, %s, %s)",
            [(article_id, issues[idx].id, sim) for article_id, idx, sim in assignments],
        )

        # Label each changed issue with the headline closest to its centroid.
        for idx in touched:
            cur.execute("""
                UPDATE issues SET label = (
                    SELECT a.title FROM article_issues ai
                    JOIN articles a ON a.id = ai.article_id
                    JOIN article_embeddings e ON e.article_id = ai.article_id
                    WHERE ai.issue_id = issues.id
                    ORDER BY e.embedding <=> issues.centroid
                    LIMIT 1)
                WHERE id = %s
            """, (issues[idx].id,))
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Group articles into issues.")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"min cosine similarity to join an issue (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--reset", action="store_true", help="delete all issues first and regroup everything")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

    with connect_with_vectors() as conn:
        if args.reset:
            conn.execute("TRUNCATE article_issues, issues RESTART IDENTITY")
            conn.commit()
            log.info("Deleted all issues.")

        articles = load_unassigned(conn)
        if not articles:
            log.info("No unassigned articles.")
            return

        issues = load_recent_issues(conn, articles[0][2] - timedelta(days=WINDOW_DAYS))
        existing = len(issues)
        assignments = assign(issues, articles, args.threshold)
        touched = {idx for _, idx, _ in assignments}
        save(conn, issues, assignments, touched)

        joined_existing = sum(1 for _, idx, _ in assignments if idx < existing)
        log.info("Assigned %d articles (threshold %.2f): %d new issues, %d joined existing issues",
                 len(assignments), args.threshold, len(issues) - existing, joined_existing)


if __name__ == "__main__":
    main()
