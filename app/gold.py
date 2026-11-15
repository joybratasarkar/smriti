"""Gold set for the grouping model (G-2): article pairs labelled by hand, used only to measure models.

Run with:  python -m app.gold                 (progress: labels per stratum)
           python -m app.gold --sample 200    (add 200 new pairs)
           python -m app.gold --label         (label pairs in the terminal; stop any time, resume later)
           python -m app.gold --stories       (how the stories in the database score on the gold set)
           python -m app.gold --export data/gold_pairs.csv   (labelled pairs as URLs, to share without the database)
           python -m app.gold --import data/gold_pairs.csv   (add them to this database, where both URLs are stored)

Pairs come in four equal strata, so the set holds both easy and hard cases:
  nearest an article and its most similar article from within 3 days (cosine 0.4-0.95): the decision
          grouping makes, and where most same-story pairs are
  high    cosine 0.6-0.95: mostly the same topic, sometimes the same story (near-duplicates left out)
  middle  cosine 0.4-0.6: the band where cosine can't decide
  low     cosine < 0.4 but sharing a rare word ("CJP", "Baliyan"): same story worded differently, or coincidence
A fifth stratum is only used for training pairs (app/teach.py --names):
  name    cosine 0.4-0.95 and sharing a rare capitalised title word ("Shroff", "Mundhe"): often the same person
          in two different events, which the cross-encoder took for one story (I-023)
The two articles are at most 30 days apart. Cosine is the bge-m3 embedding from app.embed
(random same-day pairs: median 0.31, 95% below 0.44; CJP protest pairs: median 0.44).
"""

import argparse
import csv
import random
import re
import textwrap
from collections import Counter, defaultdict

import numpy as np

from app.db import connect_with_vectors

LABELS = {"1": "same_story", "2": "follow_up", "3": "same_actor", "4": "same_topic", "5": "unrelated", "u": "unsure"}
# Also the LLM judge's instructions (app.compare), so people and the model label by the same rules.
# "One story" follows D-013.
MEANINGS = {
    "same_story": "the same ongoing issue: same core dispute or demand, same main people/orgs, at any stage "
                  "(CJP demand, protest, detentions, trains cancelled, government response = one story)",
    "follow_up": "a different issue that grew out of the other one, with its own new dispute "
                 "(e.g. a separate court case over the police action at the protest)",
    "same_actor": "same main person or organisation, unrelated issue",
    "same_topic": "same kind of event or subject, different actors (two different protests)",
    "unrelated": "none of the above",
    "unsure": "can't tell from title and snippet (left out of scoring)",
}
# Where the teacher LLM and the student went wrong on the gold set (I-023, D-035). The examples are made up,
# not gold pairs, so the gold set stays an honest test.
HARD_CASES = [
    "Same kind of event but a different case (another victim, accused, court case, accident, raid or building), "
    "even in the same place or the same court: same_topic, not same_story. Two dowry murders in one district "
    "are two stories.",
    "A new development in the same dispute (a reaction, reply, notice, march, arrest, probe or court step "
    "between the same main parties) is same_story, not follow_up. follow_up needs a separate new dispute.",
    "Same main person or organisation in a different matter: same_actor, not same_story. An actor's film release "
    "and an attack on that actor are two stories; a company sued over prices and sued over a data leak are two.",
    "An explainer, analysis, opinion piece, editorial, review or feature about one specific event or issue is "
    "same_story with the news reports of it: 'Why the dam burst' and 'Dam bursts in Kerala, 12 dead' are one story.",
    "Routine repeating reports (daily gold or fuel prices, weekly forex data, market wraps, horoscopes, quote of "
    "the day) are a new story each day or edition: same_topic. One company's IPO from opening to allotment to "
    "listing is one story.",
]
DEFINITIONS = "Pick the FIRST label that fits:\n" + "\n".join(
    textwrap.fill(MEANINGS[label], 100, initial_indent=f"  {key} {label:<11} ", subsequent_indent=" " * 16)
    for key, label in LABELS.items()
) + "\nHard cases:\n" + "\n".join(
    textwrap.fill(case, 100, initial_indent="  - ", subsequent_indent="    ") for case in HARD_CASES
) + "\n  s skip for now, q quit, anything else shows this help"

MAX_DAYS_APART = 30
NEAR_DUPLICATE, HIGH, LOW = 0.95, 0.6, 0.4   # bge-m3 cosine band edges
RARE_SHARE = 0.005                           # a rare word is in at most 0.5% of titles
NEAREST_DAYS = 3
MAX_TRIES = 2000                             # per pair, before giving up on a stratum

LOAD_SQL = """
    SELECT a.id, extract(epoch FROM a.published_at), a.title, e.embedding
    FROM articles a JOIN article_embeddings e ON e.article_id = a.id
    WHERE a.published_at IS NOT NULL
"""
# A pair is never in both the gold set and the training set (app/teach.py), so the gold set stays unseen.
INSERT_SQL = """
    INSERT INTO {table} (article_a, article_b, stratum, cosine)
    SELECT %(a)s, %(b)s, %(stratum)s, %(cosine)s
    WHERE NOT EXISTS (SELECT 1 FROM {other} WHERE article_a = %(a)s AND article_b = %(b)s)
    ON CONFLICT DO NOTHING
"""
# Shuffled (md5) so strata are mixed while labelling.
TO_LABEL_SQL = """
    SELECT g.id, a.published_at, a.source_name, a.title, a.snippet, a.url,
           b.published_at, b.source_name, b.title, b.snippet, b.url
    FROM gold_pairs g JOIN articles a ON a.id = g.article_a JOIN articles b ON b.id = g.article_b
    WHERE g.label IS NULL
    ORDER BY md5(g.id::text)
"""


def band_pair(rng: random.Random, vectors: np.ndarray, times: np.ndarray, lo: float, hi: float):
    """Random article and a random partner with cosine in [lo, hi). (i, j, cosine) or None."""
    for _ in range(MAX_TRIES):
        i = rng.randrange(len(vectors))
        sims = vectors @ vectors[i]
        ok = (sims >= lo) & (sims < hi) & (np.abs(times - times[i]) <= MAX_DAYS_APART * 86400)
        ok[i] = False
        partners = np.flatnonzero(ok)
        if len(partners):
            j = int(rng.choice(partners))
            return i, j, float(sims[j])
    return None


def nearest_pair(rng: random.Random, vectors: np.ndarray, times: np.ndarray):
    """Random article and its most similar article within NEAREST_DAYS (not a near-duplicate). (i, j, cosine) or None."""
    for _ in range(MAX_TRIES):
        i = rng.randrange(len(vectors))
        sims = vectors @ vectors[i]
        sims[(np.abs(times - times[i]) > NEAREST_DAYS * 86400) | (sims >= NEAR_DUPLICATE)] = -1
        sims[i] = -1
        j = int(np.argmax(sims))
        if sims[j] >= LOW:
            return i, j, float(sims[j])
    return None


def rare_word_pair(rng: random.Random, vectors: np.ndarray, times: np.ndarray, rare: dict[str, list[int]]):
    """Two articles sharing a rare title word, with cosine below LOW. (i, j, cosine) or None."""
    words = list(rare)
    for _ in range(MAX_TRIES):
        i, j = rng.sample(rare[rng.choice(words)], 2)
        cosine = float(vectors[i] @ vectors[j])
        if cosine < LOW and abs(times[i] - times[j]) <= MAX_DAYS_APART * 86400:
            return i, j, cosine
    return None


def name_pair(rng: random.Random, vectors: np.ndarray, times: np.ndarray, names: dict[str, list[int]]):
    """Two articles sharing a rare capitalised word, with cosine in [LOW, NEAR_DUPLICATE). (i, j, cosine) or None."""
    words = list(names)
    for _ in range(MAX_TRIES):
        i, j = rng.sample(names[rng.choice(words)], 2)
        cosine = float(vectors[i] @ vectors[j])
        if LOW <= cosine < NEAR_DUPLICATE and abs(times[i] - times[j]) <= MAX_DAYS_APART * 86400:
            return i, j, cosine
    return None


def rare_words(titles: list[str], capitalised: bool = False) -> dict[str, list[int]]:
    """Word -> rows whose title has it, for words in 2 to RARE_SHARE of all titles.
    With `capitalised`, only words written with a capital letter (mostly names; Title Case headlines add a few others)."""
    index = defaultdict(list)
    for row, title in enumerate(titles):
        words = re.findall(r"[A-Z][a-z]{2,}", title) if capitalised else re.findall(r"[a-z]{3,}", title.lower())
        for word in set(words):
            index[word].append(row)
    max_count = max(2, int(RARE_SHARE * len(titles)))
    return {w: rows for w, rows in index.items() if 2 <= len(rows) <= max_count}


def sample(conn, sizes: dict[str, int], table: str = "gold_pairs", other: str = "train_pairs") -> None:
    """Add pairs to `table` (gold_pairs or train_pairs): sizes[stratum] per stratum, none that are in `other`."""
    rows = conn.execute(LOAD_SQL).fetchall()
    if len(rows) < 2:
        print("No embedded articles. Run python -m app.embed first.")
        return
    ids = [r[0] for r in rows]
    times = np.array([float(r[1]) for r in rows])
    vectors = np.vstack([r[3].to_numpy() for r in rows])  # L2-normalized, so dot product = cosine
    rare = rare_words([r[2] for r in rows])
    names = rare_words([r[2] for r in rows], capitalised=True)
    print(f"{len(rows)} embedded articles, {len(rare)} rare words")

    rng = random.Random()
    strata = {
        "nearest": lambda: nearest_pair(rng, vectors, times),
        "high": lambda: band_pair(rng, vectors, times, HIGH, NEAR_DUPLICATE),
        "middle": lambda: band_pair(rng, vectors, times, LOW, HIGH),
        "low": lambda: rare_word_pair(rng, vectors, times, rare),
        "name": lambda: name_pair(rng, vectors, times, names),
    }
    insert = INSERT_SQL.format(table=table, other=other)
    for stratum, size in sizes.items():
        find, added = strata[stratum], 0
        for _ in range(size * 5):  # some draws are pairs we already have
            if added == size:
                break
            pair = find()
            if pair is None:
                break
            i, j, cosine = pair
            a, b = sorted((ids[i], ids[j]))
            added += conn.execute(insert, {"a": a, "b": b, "stratum": stratum, "cosine": cosine}).rowcount
        conn.commit()
        print(f"{stratum:7} {added}/{size} pairs added")


def show(name: str, published_at, source: str, title: str, snippet: str | None, url: str) -> None:
    print(f"\n{name}  {published_at:%Y-%m-%d}  {source}")
    print(textwrap.indent(textwrap.fill(title, 100), "   "))
    if snippet:
        print(textwrap.indent(textwrap.fill(textwrap.shorten(snippet, 300), 100), "   "))
    print(f"   {url}")


def label(conn) -> None:
    pairs = conn.execute(TO_LABEL_SQL).fetchall()
    print(DEFINITIONS)
    for n, (pair_id, *articles) in enumerate(pairs, 1):
        print(f"\n{'=' * 100}\nPair {n} of {len(pairs)} to label")
        show("A", *articles[:5])
        show("B", *articles[5:])
        while True:
            try:
                key = input("\n1 same_story  2 follow_up  3 same_actor  4 same_topic  5 unrelated  u  s  q > ")
            except EOFError:
                return
            key = key.strip().lower()
            if key in LABELS:
                conn.execute("UPDATE gold_pairs SET label = %s, labeled_at = now() WHERE id = %s",
                             (LABELS[key], pair_id))
                conn.commit()
                break
            if key == "s":
                break
            if key == "q":
                return
            print(DEFINITIONS)


def progress(conn) -> None:
    rows = conn.execute("""
        SELECT stratum, coalesce(label, '(not yet)'), count(*) FROM gold_pairs GROUP BY 1, 2
    """).fetchall()
    if not rows:
        print("No gold pairs yet. Run python -m app.gold --sample 200")
        return
    counts = defaultdict(dict)
    for stratum, lab, count in rows:
        counts[stratum][lab] = count
    columns = list(LABELS.values()) + ["(not yet)"]
    print(f"{'stratum':8}" + "".join(f"{c:>12}" for c in columns) + f"{'total':>8}")
    for stratum in ("nearest", "high", "middle", "low", "name"):
        c = counts.get(stratum, {})
        print(f"{stratum:8}" + "".join(f"{c.get(col, 0):>12}" for col in columns) + f"{sum(c.values()):>8}")


def scores(rows, predict) -> str:
    """Confusion counts and precision / recall of `predict` against the same_story label (row[2])."""
    c = Counter((r[2] == "same_story", bool(predict(r))) for r in rows)
    tp, fp, fn, tn = c[(True, True)], c[(False, True)], c[(True, False)], c[(False, False)]
    p = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
    return f"TP {tp:3} FP {fp:3} FN {fn:3} TN {tn:3} | precision {p:.2f} recall {rc:.2f} F1 {f1:.2f} " \
           f"accuracy {(tp + tn) / len(rows):.2f}"


def stories(conn) -> None:
    """Score the stories in the database: a gold pair counts as grouped when both articles are in one story."""
    rows = conn.execute("""
        SELECT g.id, g.stratum, g.label, ia.issue_id = ib.issue_id,
               (SELECT l.link_type FROM issue_links l
                WHERE (l.from_issue, l.to_issue) IN ((ia.issue_id, ib.issue_id), (ib.issue_id, ia.issue_id))),
               left(a.title, 70), left(b.title, 70)
        FROM gold_pairs g
        JOIN article_issues ia ON ia.article_id = g.article_a JOIN article_issues ib ON ib.article_id = g.article_b
        JOIN articles a ON a.id = g.article_a JOIN articles b ON b.id = g.article_b
        WHERE g.label IS NOT NULL AND g.label <> 'unsure'
    """).fetchall()
    if not rows:
        print("No labelled gold pairs in stories yet.")
        return
    print(len(rows), "gold pairs,", sum(r[2] == "same_story" for r in rows), "same_story")
    print("grouped together           ", scores(rows, lambda r: r[3]))
    print("together or linked         ", scores(rows, lambda r: r[3] or r[4] not in (None, "unrelated")))
    print("together or same_story link", scores(rows, lambda r: r[3] or r[4] == "same_story"))
    for s in ("nearest", "high", "middle", "low", "name"):
        sub = [r for r in rows if r[1] == s]
        if sub:
            print(f"  {s:8} ({len(sub):2})", scores(sub, lambda r: r[3]))
    print("\nSplit: same story in gold, different stories in the app (link between them):")
    for r in rows:
        if r[2] == "same_story" and not r[3]:
            print(f"  #{r[0]:<4} [{r[4] or 'no link'}] {r[5]}  ||  {r[6]}")
    print("\nWrongly together: grouped, but gold says otherwise:")
    for r in rows:
        if r[2] != "same_story" and r[3]:
            print(f"  #{r[0]:<4} [{r[2]}] {r[5]}  ||  {r[6]}")


EXPORT_COLUMNS = ["stratum", "cosine", "label", "url_a", "url_b"]


def export(conn, path: str) -> None:
    """Labelled gold pairs as URLs and labels only: no titles or snippets, so no article text is published."""
    rows = conn.execute("""
        SELECT g.stratum, round(g.cosine::numeric, 4), g.label, a.url, b.url FROM gold_pairs g
        JOIN articles a ON a.id = g.article_a JOIN articles b ON b.id = g.article_b
        WHERE g.label IS NOT NULL ORDER BY g.id
    """).fetchall()
    with open(path, "w", newline="") as f:
        out = csv.writer(f)
        out.writerow(EXPORT_COLUMNS)
        out.writerows(rows)
    print(f"Wrote {len(rows)} labelled pairs to {path}")


def import_pairs(conn, path: str) -> None:
    """Add exported pairs whose two URLs are both in this database's articles; pairs already there are kept."""
    added = missing = 0
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            ids = conn.execute("SELECT id FROM articles WHERE url IN (%s, %s)", (row["url_a"], row["url_b"])).fetchall()
            if len(ids) != 2:
                missing += 1
                continue
            a, b = sorted(i for (i,) in ids)
            added += conn.execute("""
                INSERT INTO gold_pairs (article_a, article_b, stratum, cosine, label, labeled_at)
                SELECT %s, %s, %s, %s, %s, now()
                WHERE NOT EXISTS (SELECT 1 FROM train_pairs WHERE article_a = %s AND article_b = %s)
                ON CONFLICT (article_a, article_b) DO NOTHING
            """, (a, b, row["stratum"], float(row["cosine"]), row["label"], a, b)).rowcount
    conn.commit()
    print(f"Added {added} pairs; {missing} skipped because an article is not in this database")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", type=int, metavar="N", help="add N new pairs")
    parser.add_argument("--label", action="store_true", help="label pairs in the terminal")
    parser.add_argument("--stories", action="store_true", help="score the stories in the database on the gold set")
    parser.add_argument("--export", metavar="CSV", help="write the labelled pairs (URLs and labels) to CSV")
    parser.add_argument("--import", dest="import_csv", metavar="CSV", help="add pairs from an exported CSV")
    args = parser.parse_args()

    with connect_with_vectors() as conn:
        if args.sample:
            n = args.sample
            sample(conn, {"nearest": n // 4, "high": n // 4, "middle": n - 3 * (n // 4), "low": n // 4})
        if args.label:
            label(conn)
        if args.import_csv:
            import_pairs(conn, args.import_csv)
        if args.export:
            export(conn, args.export)
        if args.stories:
            stories(conn)
        else:
            progress(conn)


if __name__ == "__main__":
    main()
