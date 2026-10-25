"""Compute an embedding for every article that doesn't have one yet (the "towers" of D-024).

Run with:  python -m app.embed

Embeds title + snippet (we don't store full text) with bge-m3 on the GPU. Safe to run repeatedly:
articles embedded by another model are embedded again.
"""

import logging
import time

import numpy as np

from app import models
from app.db import connect_with_vectors

CHUNK = 1024  # articles per commit

log = logging.getLogger("embed")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    with connect_with_vectors() as conn:
        rows = conn.execute("""
            SELECT a.id, a.title, a.snippet
            FROM articles a
            LEFT JOIN article_embeddings e ON e.article_id = a.id
            WHERE e.article_id IS NULL OR e.model <> %s
            ORDER BY a.id
        """, (models.EMBEDDER,)).fetchall()
        if not rows:
            log.info("All articles already have embeddings.")
            return

        log.info("Embedding %d articles with %s on %s (first run downloads the model)",
                 len(rows), models.EMBEDDER, models.DEVICE)
        embedder = models.Embedder()
        started = time.time()
        for i in range(0, len(rows), CHUNK):
            batch = rows[i:i + CHUNK]
            vectors = embedder.encode([models.article_text(title, snippet) for _, title, snippet in batch])
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO article_embeddings (article_id, model, embedding)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (article_id) DO UPDATE
                        SET model = EXCLUDED.model, embedding = EXCLUDED.embedding, created_at = now()
                """, [(article_id, models.EMBEDDER, vec.astype(np.float32))
                      for (article_id, _, _), vec in zip(batch, vectors)])
            conn.commit()
            log.info("  %d / %d", min(i + CHUNK, len(rows)), len(rows))
        log.info("Done in %.0f s", time.time() - started)


if __name__ == "__main__":
    main()
