"""Compute an embedding for every article that doesn't have one yet.

Run with:  python -m app.embed

Embeds title + snippet (we don't store full text). Safe to run repeatedly.
"""

import logging
import time

import numpy as np
from fastembed import TextEmbedding

from app.db import connect_with_vectors

# Multilingual, so Hindi and English headlines about the same event land close together.
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
BATCH_SIZE = 256

log = logging.getLogger("embed")


def article_text(title: str, snippet: str | None) -> str:
    return f"{title}. {snippet}" if snippet else title


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    with connect_with_vectors() as conn:
        rows = conn.execute("""
            SELECT a.id, a.title, a.snippet
            FROM articles a
            LEFT JOIN article_embeddings e ON e.article_id = a.id
            WHERE e.article_id IS NULL OR e.model <> %s
            ORDER BY a.id
        """, (MODEL,)).fetchall()
        if not rows:
            log.info("All articles already have embeddings.")
            return

        log.info("Embedding %d articles with %s (first run downloads the model)", len(rows), MODEL)
        model = TextEmbedding(MODEL)
        started = time.time()
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            vectors = np.array(list(model.embed([article_text(title, snippet) for _, title, snippet in batch])))
            vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)  # normalize so dot product = cosine
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO article_embeddings (article_id, model, embedding)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (article_id) DO UPDATE
                        SET model = EXCLUDED.model, embedding = EXCLUDED.embedding, created_at = now()
                """, [(article_id, MODEL, vec.astype(np.float32)) for (article_id, _, _), vec in zip(batch, vectors)])
            conn.commit()
            log.info("  %d / %d", min(i + BATCH_SIZE, len(rows)), len(rows))
        log.info("Done in %.0f s", time.time() - started)


if __name__ == "__main__":
    main()
