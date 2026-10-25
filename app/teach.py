"""Teacher labels for fine-tuning (G-4): the local LLM labels article pairs by the gold-set rules.

Run with:  python -m app.teach                 (progress: labels per stratum)
           python -m app.teach --sample 3000   (add pairs: 40% nearest, 10% high, 40% middle, 10% low cosine)
           python -m app.teach --label         (the LLM labels the unlabelled pairs; stop any time, resume later)

Pairs come from the same strata as the gold set (app/gold.py) but are never gold pairs, so the gold set
stays an honest test. Most are "nearest" pairs (where same-story pairs are) and middle-band pairs (where
grouping needs the cross-encoder).
"""

import argparse
import logging
import time
from collections import defaultdict

import httpx

from app import ollama
from app.db import connect_with_vectors
from app.gold import sample
from app.judge import LABELS, judge
from app.models import article_text

TO_LABEL_SQL = """
    SELECT t.id, a.title, a.snippet, a.source_name, a.published_at,
           b.title, b.snippet, b.source_name, b.published_at
    FROM train_pairs t JOIN articles a ON a.id = t.article_a JOIN articles b ON b.id = t.article_b
    WHERE t.label IS NULL
    ORDER BY t.id
"""

log = logging.getLogger("teach")


def describe(title: str, snippet: str | None, source: str, published_at) -> str:
    return f"{article_text(title, snippet)} ({source}, {published_at:%Y-%m-%d})"


def label(conn) -> None:
    pairs = conn.execute(TO_LABEL_SQL).fetchall()
    log.info("Labelling %d pairs with %s", len(pairs), ollama.MODEL)
    started, unreadable = time.time(), 0
    with httpx.Client(timeout=600) as client:
        for n, (pair_id, *articles) in enumerate(pairs, 1):
            result, _ = judge(client, describe(*articles[:4]), describe(*articles[4:]), reason=False)
            if result is None:
                unreadable += 1  # left unlabelled; the next run tries again
            else:
                conn.execute("UPDATE train_pairs SET label = %s, labeled_by = %s, labeled_at = now() WHERE id = %s",
                             (result, ollama.MODEL, pair_id))
                conn.commit()
            if n % 100 == 0 or n == len(pairs):
                log.info("  %d / %d, %.1f s per pair, %d unreadable", n, len(pairs), (time.time() - started) / n, unreadable)


def progress(conn) -> None:
    counts = defaultdict(dict)
    for stratum, lab, count in conn.execute(
            "SELECT stratum, coalesce(label, '(not yet)'), count(*) FROM train_pairs GROUP BY 1, 2"):
        counts[stratum][lab] = count
    columns = LABELS + ["(not yet)"]
    print(f"{'stratum':8}" + "".join(f"{c:>12}" for c in columns) + f"{'total':>8}")
    for stratum in ("nearest", "high", "middle", "low"):
        c = counts.get(stratum, {})
        print(f"{stratum:8}" + "".join(f"{c.get(col, 0):>12}" for col in columns) + f"{sum(c.values()):>8}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", type=int, metavar="N", help="add N new pairs")
    parser.add_argument("--label", action="store_true", help="label the unlabelled pairs with the LLM")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    with connect_with_vectors() as conn:
        if args.sample:
            n = args.sample
            sample(conn, {"nearest": 4 * n // 10, "high": n // 10, "middle": n - 6 * n // 10, "low": n // 10},
                   "train_pairs", "gold_pairs")
        if args.label:
            label(conn)
        progress(conn)


if __name__ == "__main__":
    main()
