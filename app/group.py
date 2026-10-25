"""Assign embedded articles to stories ("issues"): the towers find candidates, the cross-encoder decides (D-024).

Run with:  python -m app.group            (assign new articles, then merge split stories)
           python -m app.group --reset    (delete all issues and links, regroup from scratch)

Each unassigned article, oldest first:
  1. Towers: cosine between the article's bge-m3 vector and the centroid of every story active in the
     last WINDOW_DAYS days. The TOP_K best with cosine >= FLOOR are candidates; none means a new story.
  2. A near-duplicate (best cosine >= SURE) joins that story without asking the cross-encoder.
  3. In between, the fine-tuned cross-encoder (app/train.py) reads the article together with each candidate's
     CLOSEST member headlines (the ones nearest the article), one pair at a time as in training, and gives
     P(same story) as their mean. The best candidate at or above JOIN gets the article; below it, a new story.
     Until 2026-10-24 it read the story's latest headlines instead, which split one event into parallel stories
     when the matching headline had just dropped out of the window (I-016). Until 2026-10-25 it read the closest
     headlines joined into one text, where one shared name let a new event into an old story (I-023: the Tiger
     Shroff shooting joined the FDA ad-notice story).
Articles with a blank title, and second copies of an article (same site, headline and snippet within a day,
I-019), are left out. Progress is saved every CHUNK articles.
Then split stories are merged: stories whose centres are closer than MERGE_COSINE and at most WINDOW_DAYS
apart are compared on their MERGE_PAIRS closest article pairs, and merge into the older one when the
cross-encoder gives each of those pairs at least JOIN. Assigned articles otherwise never move, so issue ids stay stable.
The cut-offs are provisional (D-027): set on 200 known same-story pairs (CJP protest) against 200 random
same-day pairs, until the gold set measures them (G-3). The cross-encoder only sees the uncertain band
because it costs ~0.1 s per article on the GTX 1650.
"""

import argparse
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import torch

from app import models
from app.db import connect_with_vectors

WINDOW_DAYS = 30
TOP_K = 3
FLOOR = 0.40            # tower cosine below this: never the same story (74% of same-story pairs are above)
SURE = 0.92             # near-duplicates join directly; below this, look-alikes are often different
                        # stories (daily horoscopes, two El Nino articles), which the cross-encoder separates
JOIN = 0.5              # fine-tuned cross-encoder probability needed to join, in the band between
CLOSEST = 3             # a story is shown to the cross-encoder as its members closest to the article
MERGE_COSINE = 0.88     # story centres this close are checked for a split (633 pairs on 2026-10-20)
MERGE_PAIRS = 3         # closest article pairs the cross-encoder reads per story pair
CHUNK = 2000

log = logging.getLogger("group")


@dataclass
class Story:
    id: int | None          # None until saved
    total: np.ndarray       # sum of member vectors; the centroid is total / count
    count: int
    first_seen: datetime
    last_seen: datetime
    label: str
    titles: list[str] = field(default_factory=list)       # member headlines, in the order they joined
    members: np.ndarray | None = None                      # member vectors (float16), same order

    def add_member(self, title: str, vector: np.ndarray) -> None:
        self.titles.append(title)
        row = vector.astype(np.float16)[None, :]
        self.members = row if self.members is None else np.vstack([self.members, row])

    def closest(self, vector: np.ndarray) -> list[str]:
        """The CLOSEST distinct member headlines nearest `vector`, closest first."""
        order = np.argsort(-(self.members.astype(np.float32) @ vector))
        picked = []
        for k in order:
            if self.titles[k] not in picked:
                picked.append(self.titles[k])
            if len(picked) == CLOSEST:
                break
        return picked


class Stories:
    """All stories in memory, with their normalized centroids in one GPU matrix for fast cosine."""

    def __init__(self, stories: list[Story]):
        self.items: list[Story] = []
        self.vectors = torch.zeros((max(1024, 2 * len(stories)), models.DIMENSIONS),
                                   dtype=torch.float32, device=models.DEVICE)
        self.last_seen = torch.zeros(len(self.vectors), dtype=torch.float64, device=models.DEVICE)
        for story in stories:
            self.add(story)

    def add(self, story: Story) -> int:
        if len(self.items) == len(self.vectors):  # full: double the capacity
            self.vectors = torch.cat([self.vectors, torch.zeros_like(self.vectors)])
            self.last_seen = torch.cat([self.last_seen, torch.zeros_like(self.last_seen)])
        self.items.append(story)
        self._refresh(len(self.items) - 1)
        return len(self.items) - 1

    def join(self, idx: int, vector: np.ndarray, when: datetime, title: str) -> None:
        story = self.items[idx]
        story.total += vector
        story.count += 1
        story.first_seen = min(story.first_seen, when)
        story.last_seen = max(story.last_seen, when)
        story.add_member(title, vector)
        self._refresh(idx)

    def _refresh(self, idx: int) -> None:
        story = self.items[idx]
        self.vectors[idx] = torch.from_numpy(story.total / np.linalg.norm(story.total)).to(self.vectors)
        self.last_seen[idx] = story.last_seen.timestamp()

    def candidates(self, vector: np.ndarray, when: datetime) -> list[tuple[int, float]]:
        """(index, cosine) of the TOP_K stories closest to `vector`, active around `when`, cosine >= FLOOR."""
        n = len(self.items)
        if not n:
            return []
        sims = (self.vectors[:n] @ torch.from_numpy(vector).to(self.vectors)).float()
        sims[self.last_seen[:n] < (when - timedelta(days=WINDOW_DAYS)).timestamp()] = -1
        values, indexes = torch.topk(sims, min(TOP_K, n))
        return [(i, v) for v, i in zip(values.tolist(), indexes.tolist()) if v >= FLOOR]


def assign(stories: Stories, articles, cross_encoder: models.CrossEncoder, counts: dict) -> list[tuple]:
    """Group articles (id, title, snippet, when, vector) into stories, updating `stories` in place.

    Returns (article_id, story index, cosine, probability or None, model or None) per article.
    """
    assignments = []
    for article_id, title, snippet, when, vector in articles:
        found = stories.candidates(vector, when)
        idx, cosine, probability, model = -1, 1.0, None, None
        if found and found[0][1] >= SURE:
            idx, cosine = found[0]
            counts["joined_by_towers"] += 1
        elif found:
            text = models.article_text(title, snippet)
            batch, owner = [], []
            for n, (i, _) in enumerate(found):
                for headline in stories.items[i].closest(vector):
                    batch.append((text, headline))
                    owner.append(n)
            # Mean over the closest headlines, each read on its own as in training: one shared name with a
            # single member no longer carries a new event into an old story (I-023).
            probs = np.bincount(owner, cross_encoder.score(batch), len(found)) / np.bincount(owner, None, len(found))
            best = int(np.argmax(probs))
            counts["cross_encoder_calls"] += 1
            if probs[best] >= JOIN:
                idx, cosine = found[best]
                probability, model = float(probs[best]), cross_encoder.name
                counts["joined_by_cross_encoder"] += 1
        if idx >= 0:
            stories.join(idx, vector, when, title)
        else:
            story = Story(None, vector.astype(np.float64), 1, when, when, title)
            story.add_member(title, vector)
            idx = stories.add(story)
            counts["new_stories"] += 1
        assignments.append((article_id, idx, cosine, probability, model))
    return assignments


def load_unassigned(conn, limit: int):
    rows = conn.execute("""
        SELECT a.id, a.title, a.snippet, coalesce(a.published_at, a.fetched_at) AS ts, e.embedding
        FROM articles a
        JOIN article_embeddings e ON e.article_id = a.id
        LEFT JOIN article_issues ai ON ai.article_id = a.id
        WHERE ai.article_id IS NULL AND btrim(a.title) <> ''
          AND NOT EXISTS (SELECT 1 FROM articles d
                          WHERE d.source_domain = a.source_domain AND d.content_hash = a.content_hash AND d.id < a.id
                            AND abs(extract(epoch FROM coalesce(d.published_at, d.fetched_at)
                                                      - coalesce(a.published_at, a.fetched_at))) < 86400)
        ORDER BY ts, a.id
        LIMIT %s
    """, (limit,)).fetchall()
    return [(article_id, title, snippet, ts, vec.to_numpy().astype(np.float32))
            for article_id, title, snippet, ts, vec in rows]


def load_recent_stories(conn, since: datetime) -> list[Story]:
    stories = {issue_id: Story(issue_id, centroid.to_numpy().astype(np.float64) * count, count, first, last, label)
               for issue_id, centroid, count, first, last, label in conn.execute("""
                   SELECT id, centroid, article_count, first_seen, last_seen, label FROM issues WHERE last_seen >= %s
               """, (since,)).fetchall()}
    for issue_id, title, vec in conn.execute("""
        SELECT ai.issue_id, a.title, e.embedding
        FROM issues i JOIN article_issues ai ON ai.issue_id = i.id
        JOIN articles a ON a.id = ai.article_id JOIN article_embeddings e ON e.article_id = a.id
        WHERE i.last_seen >= %s ORDER BY coalesce(a.published_at, a.fetched_at), a.id
    """, (since,)).fetchall():
        stories[issue_id].add_member(title, vec.to_numpy().astype(np.float32))
    return list(stories.values())


def save(conn, stories: Stories, assignments, touched: set[int]) -> None:
    with conn.cursor() as cur:
        for idx in touched:
            story = stories.items[idx]
            centroid = (story.total / story.count).astype(np.float32)
            if story.id is None:
                cur.execute("""
                    INSERT INTO issues (label, centroid, article_count, first_seen, last_seen)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                """, (story.label, centroid, story.count, story.first_seen, story.last_seen))
                story.id = cur.fetchone()[0]
            else:
                cur.execute("""
                    UPDATE issues SET centroid = %s, article_count = %s, first_seen = %s, last_seen = %s
                    WHERE id = %s
                """, (centroid, story.count, story.first_seen, story.last_seen, story.id))

        cur.executemany(
            "INSERT INTO article_issues (article_id, issue_id, similarity, probability, model) "
            "VALUES (%s, %s, %s, %s, %s)",
            [(article_id, stories.items[idx].id, cosine, probability, model)
             for article_id, idx, cosine, probability, model in assignments],
        )

        # Label each changed story with the headline closest to its centroid.
        for idx in touched:
            if stories.items[idx].count > 1:
                cur.execute("""
                    UPDATE issues SET label = (
                        SELECT a.title FROM article_issues ai
                        JOIN articles a ON a.id = ai.article_id
                        JOIN article_embeddings e ON e.article_id = ai.article_id
                        WHERE ai.issue_id = issues.id
                        ORDER BY e.embedding <=> issues.centroid
                        LIMIT 1)
                    WHERE id = %s
                """, (stories.items[idx].id,))
    conn.commit()


def merge_splits(conn, cross_encoder: models.CrossEncoder) -> int:
    """Merge stories that are one event split in two (I-016). Returns how many stories were merged away."""
    rows = conn.execute("""
        SELECT id, centroid, extract(epoch FROM first_seen), extract(epoch FROM last_seen)
        FROM issues WHERE article_count >= 2 ORDER BY first_seen, id
    """).fetchall()
    if len(rows) < 2:
        return 0
    ids = [r[0] for r in rows]
    centres = np.vstack([r[1].to_numpy() for r in rows]).astype(np.float32)
    centres /= np.linalg.norm(centres, axis=1, keepdims=True)
    first, last = np.array([float(r[2]) for r in rows]), np.array([float(r[3]) for r in rows])
    pairs = []
    for start in range(0, len(ids), 2048):
        sims = centres[start:start + 2048] @ centres.T
        for row, i in enumerate(range(start, min(start + 2048, len(ids)))):
            gap = np.maximum(first - last[i], first[i] - last)  # <= 0 when they overlap in time
            close = (sims[row] >= MERGE_COSINE) & (gap <= WINDOW_DAYS * 86400)
            close[:i + 1] = False
            pairs += [(i, int(j)) for j in np.flatnonzero(close)]
    if not pairs:
        return 0

    involved = sorted({ids[k] for pair in pairs for k in pair})
    members: dict[int, tuple[list[str], list[np.ndarray]]] = {}
    for issue_id, title, snippet, vec in conn.execute("""
        SELECT ai.issue_id, a.title, a.snippet, e.embedding FROM article_issues ai
        JOIN articles a ON a.id = ai.article_id JOIN article_embeddings e ON e.article_id = a.id
        WHERE ai.issue_id = ANY(%s)
    """, (involved,)).fetchall():
        texts, vecs = members.setdefault(issue_id, ([], []))
        texts.append(models.article_text(title, snippet))
        vecs.append(vec.to_numpy().astype(np.float32))
    batch, owner = [], []
    for n, (i, j) in enumerate(pairs):
        (ta, va), (tb, vb) = members[ids[i]], members[ids[j]]
        sims = np.vstack(va) @ np.vstack(vb).T
        for flat in np.argsort(-sims, axis=None)[:MERGE_PAIRS]:
            a, b = np.unravel_index(flat, sims.shape)
            batch.append((ta[a], tb[b]))
            owner.append(n)
    probs = cross_encoder.score(batch)
    weakest = np.ones(len(pairs))  # every one of the closest article pairs must say same story
    np.minimum.at(weakest, owner, probs)

    # Union-find over the pairs that pass; rows are ordered by first_seen, so the smallest row is the oldest story.
    root = list(range(len(ids)))
    def find(k):
        while root[k] != k:
            root[k] = root[root[k]]
            k = root[k]
        return k
    for n in np.flatnonzero(weakest >= JOIN):
        a, b = find(pairs[n][0]), find(pairs[n][1])
        if a != b:
            root[max(a, b)] = min(a, b)
    groups: dict[int, list[int]] = {}
    for k in {k for pair in pairs for k in pair}:
        groups.setdefault(find(k), []).append(k)
    merged = 0
    with conn.cursor() as cur:
        for keep, rows_in in groups.items():
            gone = [ids[k] for k in rows_in if k != keep]
            if not gone:
                continue
            cur.execute("UPDATE article_issues SET issue_id = %s WHERE issue_id = ANY(%s)", (ids[keep], gone))
            cur.execute("DELETE FROM issues WHERE id = ANY(%s)", (gone,))
            cur.execute("""
                UPDATE issues SET (centroid, article_count, first_seen, last_seen) = (
                    SELECT avg(e.embedding), count(*), min(coalesce(a.published_at, a.fetched_at)),
                           max(coalesce(a.published_at, a.fetched_at))
                    FROM article_issues ai JOIN articles a ON a.id = ai.article_id
                    JOIN article_embeddings e ON e.article_id = a.id WHERE ai.issue_id = issues.id)
                WHERE id = %s
            """, (ids[keep],))
            cur.execute("""
                UPDATE issues SET label = (
                    SELECT a.title FROM article_issues ai JOIN articles a ON a.id = ai.article_id
                    JOIN article_embeddings e ON e.article_id = ai.article_id
                    WHERE ai.issue_id = issues.id ORDER BY e.embedding <=> issues.centroid LIMIT 1)
                WHERE id = %s
            """, (ids[keep],))
            merged += len(gone)
    conn.commit()
    log.info("Merge: %d close story pairs checked, %d passed, %d stories merged into older ones",
             len(pairs), int((weakest >= JOIN).sum()), merged)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Group articles into stories.")
    parser.add_argument("--reset", action="store_true", help="delete all issues and links first and regroup everything")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

    if not models.FINE_TUNED.exists():
        raise SystemExit(f"No fine-tuned cross-encoder in {models.FINE_TUNED}. Run python -m app.train first.")

    with connect_with_vectors() as conn:
        if args.reset:
            conn.execute("TRUNCATE article_issues, issue_links, moment_labels, issues RESTART IDENTITY")
            conn.commit()
            log.info("Deleted all issues and links.")

        articles = load_unassigned(conn, CHUNK)
        if not articles:
            log.info("No unassigned articles.")
            return
        stories = Stories(load_recent_stories(conn, articles[0][3] - timedelta(days=WINDOW_DAYS)))
        log.info("Loaded %d recent stories; cross-encoder %s on %s", len(stories.items),
                 models.FINE_TUNED, models.DEVICE)
        cross_encoder = models.CrossEncoder(str(models.FINE_TUNED))

        counts = {"articles": 0, "new_stories": 0, "joined_by_towers": 0,
                  "cross_encoder_calls": 0, "joined_by_cross_encoder": 0}
        started = time.time()
        while articles:
            assignments = assign(stories, articles, cross_encoder, counts)
            save(conn, stories, assignments, {idx for _, idx, *_ in assignments})
            counts["articles"] += len(assignments)
            log.info("%d articles (up to %s), %.0f/s: %s", counts["articles"], f"{articles[-1][3]:%Y-%m-%d}",
                     counts["articles"] / (time.time() - started), counts)
            articles = load_unassigned(conn, CHUNK)
        merge_splits(conn, cross_encoder)


if __name__ == "__main__":
    main()
