"""Connect stories: weighted links between issues, the edges of the story graph (G-6, D-024).

Run with:  python -m app.links              (weigh links between stories)
           python -m app.links --types 200  (the LLM names the 200 strongest links it hasn't named yet)

Weighing: for every story with at least MIN_ARTICLES articles, the towers pick the LINK_K other such
stories with the closest centroids (cosine >= FLOOR) within WINDOW_DAYS of it in time. The cross-encoder
reads both stories' latest headlines; its probability is the link weight. Links with weight >= MIN_WEIGHT
are stored as 'related', from the older story to the newer one. Run it again after app.group.
Naming: the LLM judge labels a link same_story / follow_up / same_actor / same_topic / unrelated and
gives a one-line reason, stored as evidence. The cut-offs are provisional (D-027).
"""

import argparse
import logging
import time
from collections import Counter

import httpx
import numpy as np

from app import models, ollama
from app.db import connect_with_vectors
from app.judge import judge

MIN_ARTICLES = 2
LINK_K = 5
FLOOR = 0.5         # tower cosine between story centroids
WINDOW_DAYS = 30    # largest gap in time between two linked stories
MIN_WEIGHT = 0.2    # cross-encoder probability needed to keep a link
HEADLINES = 3

STORIES_SQL = """
    SELECT i.id, i.centroid, extract(epoch FROM i.first_seen), extract(epoch FROM i.last_seen),
           ARRAY(SELECT a.title FROM article_issues ai JOIN articles a ON a.id = ai.article_id
                 WHERE ai.issue_id = i.id
                 ORDER BY coalesce(a.published_at, a.fetched_at) DESC LIMIT %s) AS headlines
    FROM issues i WHERE i.article_count >= %s
    ORDER BY i.first_seen, i.id
"""
UPSERT_SQL = """
    INSERT INTO issue_links (from_issue, to_issue, weight, model) VALUES (%s, %s, %s, %s)
    ON CONFLICT (from_issue, to_issue) DO UPDATE SET weight = EXCLUDED.weight, model = EXCLUDED.model
"""
TO_NAME_SQL = """
    SELECT l.from_issue, l.to_issue,
           a.label, a.first_seen, a.last_seen, a.article_count,
           b.label, b.first_seen, b.last_seen, b.article_count
    FROM issue_links l JOIN issues a ON a.id = l.from_issue JOIN issues b ON b.id = l.to_issue
    WHERE l.link_type = 'related'
    ORDER BY l.weight DESC
    LIMIT %s
"""

log = logging.getLogger("links")


def candidate_pairs(vectors: np.ndarray, first: np.ndarray, last: np.ndarray) -> set[tuple[int, int]]:
    """(older, newer) row pairs: each story with its LINK_K closest stories that pass FLOOR and WINDOW_DAYS."""
    pairs = set()
    window = WINDOW_DAYS * 86400
    for start in range(0, len(vectors), 1024):
        sims = vectors[start:start + 1024] @ vectors.T
        for row, i in enumerate(range(start, min(start + 1024, len(vectors)))):
            gap = np.maximum(first - last[i], first[i] - last)  # <= 0 when the two overlap in time
            ok = (sims[row] >= FLOOR) & (gap <= window)
            ok[i] = False
            for j in np.flatnonzero(ok)[np.argsort(-sims[row][ok])][:LINK_K]:
                pairs.add((min(i, int(j)), max(i, int(j))))  # rows are ordered by first_seen
    return pairs


def weigh(conn) -> None:
    rows = conn.execute(STORIES_SQL, (HEADLINES, MIN_ARTICLES)).fetchall()
    log.info("%d stories with at least %d articles", len(rows), MIN_ARTICLES)
    if len(rows) < 2:
        return
    ids = [r[0] for r in rows]
    vectors = np.vstack([r[1].to_numpy() for r in rows]).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    first, last = np.array([float(r[2]) for r in rows]), np.array([float(r[3]) for r in rows])
    texts = [" | ".join(r[4]) for r in rows]  # latest headline first

    pairs = sorted(candidate_pairs(vectors, first, last))
    log.info("%d candidate links; weighing them with %s on %s", len(pairs), models.CROSS_ENCODER, models.DEVICE)
    cross_encoder = models.CrossEncoder()
    started, kept = time.time(), 0
    for start in range(0, len(pairs), 2000):
        chunk = pairs[start:start + 2000]
        weights = cross_encoder.score([(texts[i], texts[j]) for i, j in chunk])
        with conn.cursor() as cur:
            strong = [(ids[i], ids[j], float(w), cross_encoder.name) for (i, j), w in zip(chunk, weights) if w >= MIN_WEIGHT]
            cur.executemany(UPSERT_SQL, strong)
            # A link that got weaker than MIN_WEIGHT goes, unless the LLM has already named it.
            cur.executemany("DELETE FROM issue_links WHERE from_issue = %s AND to_issue = %s AND link_type = 'related'",
                            [(ids[i], ids[j]) for (i, j), w in zip(chunk, weights) if w < MIN_WEIGHT])
        conn.commit()
        kept += len(strong)
        log.info("  %d / %d weighed, %d kept, %.0f pairs/s", start + len(chunk), len(pairs), kept,
                 (start + len(chunk)) / (time.time() - started))


def describe(label: str, first_seen, last_seen, count: int) -> str:
    return f"{label} ({first_seen:%Y-%m-%d} to {last_seen:%Y-%m-%d}, {count} articles)"


def name_types(conn, limit: int) -> None:
    links = conn.execute(TO_NAME_SQL, (limit,)).fetchall()
    log.info("Naming %d links with %s", len(links), ollama.MODEL)
    named = Counter()
    with httpx.Client(timeout=600) as client:
        for n, (from_id, to_id, *stories) in enumerate(links, 1):
            label, reason = judge(client, describe(*stories[:4]), describe(*stories[4:]))
            if label is None:
                log.warning("  link %d-%d: unreadable answer, left as 'related'", from_id, to_id)
                continue
            conn.execute("""
                UPDATE issue_links SET link_type = %s, evidence = %s, typed_by = %s
                WHERE from_issue = %s AND to_issue = %s
            """, (label, reason, ollama.MODEL, from_id, to_id))
            conn.commit()
            named[label] += 1
            if n % 20 == 0:
                log.info("  %d / %d named: %s", n, len(links), dict(named))
    log.info("Named: %s", dict(named))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--types", type=int, metavar="N", help="name the N strongest unnamed links with the LLM")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

    with connect_with_vectors() as conn:
        if args.types:
            name_types(conn, args.types)
        else:
            weigh(conn)


if __name__ == "__main__":
    main()
