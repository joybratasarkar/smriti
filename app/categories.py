"""News categories (D-036): every story gets a subject (Politics, Crime, ...) and a region (India or World).

Run with:  python -m app.categories --label 1500   (the LLM labels 1500 more articles, one per story; resumable)
           python -m app.categories                (fit the classifier, print its held-out accuracy, label all stories)
           python -m app.categories --stories      (the LLM labels the front-page stories from their main headlines)

Teacher and student again, as for grouping (D-028): the local LLM labels a sample of articles once; a linear
classifier learns those labels from the articles' bge-m3 vectors and labels every story from its centroid, so
it covers all stories in seconds and is simply rerun after each `app.group`. Labels are kept per article, so they
survive a regroup. Articles with id % 10 == 0 are held out to report how often the classifier agrees with the LLM.
The classifier agrees with the LLM on only ~70% of held-out articles (2026-10-26, 5-fold: 12 Sports examples are
too few), so the stories people see, the front page's, are labelled by the LLM itself (`--stories`, after
`app.group`; category_by = 'llm', never overwritten by the classifier).
"""

import argparse
import json
import logging
import time

import httpx
import numpy as np
import torch

from app import ollama
from app.db import connect_with_vectors
from app.models import article_text

CATEGORIES = {
    "Politics": "government, ministers, politicians and what they say, elections, parties, parliament, policy, "
                "diplomacy, war and conflict between countries",
    "Crime & Justice": "crime, police, arrests, scams, terrorism, killings, courts and legal cases",
    "Business": "companies, markets, the economy, jobs, prices, trade, personal finance",
    "Sports": "sport of any kind, players, matches, tournaments, medals",
    "Entertainment": "films, TV, OTT, music, celebrities, box office",
    "Tech & Science": "technology, gadgets, AI, the internet, space, scientific research, cars",
    "Health": "health, medicine, hospitals, diseases, births, nutrition, food safety and adulteration",
    "Environment & Disasters": "weather, climate, drought, pollution, wildlife and nature, floods, earthquakes, "
                               "fires, road, rail and air crashes, collapses and other accidents",
    "Society": "education and exams, religion, festivals, caste, culture, lifestyle, astrology, human interest",
}
REGIONS = ["India", "World"]

# "about" comes first: saying what the article is mainly about before choosing helps the 4B model. On 80 articles
# checked by Claude (2026-10-26) the teacher was right on 71 without it, 74 with it, and 69 to 70 with a list of
# hard-case rules instead (the small model over-applied them), so the hard cases live in the descriptions above.
SYSTEM = (
    "You sort news articles for an Indian news app.\n"
    "about: first say in 3 to 6 words what the article is mainly about.\n"
    "region: India when the news happens in India or is mainly about Indian people, companies, prices or "
    "government, even abroad. World when it is about other countries.\n"
    "category: the ONE that fits what the article is mainly about:\n"
    + "\n".join(f"- {name}: {meaning}" for name, meaning in CATEGORIES.items())
    + "\nUse only what the text says. Return JSON only."
)
SCHEMA = {
    "type": "object",
    "properties": {"about": {"type": "string"},
                   "region": {"type": "string", "enum": REGIONS},
                   "category": {"type": "string", "enum": list(CATEGORIES)}},
    "required": ["about", "region", "category"],
}

# One random member of each of `limit` random stories (2+ articles) that has no labelled article yet.
SAMPLE_SQL = """
    SELECT DISTINCT ON (ai.issue_id) a.id, a.title, a.snippet
    FROM article_issues ai JOIN articles a ON a.id = ai.article_id JOIN issues i ON i.id = ai.issue_id
    WHERE i.article_count >= 2
      AND NOT EXISTS (SELECT 1 FROM article_issues l JOIN article_categories c ON c.article_id = l.article_id
                      WHERE l.issue_id = ai.issue_id)
    ORDER BY ai.issue_id, random()
"""

log = logging.getLogger("categories")


def label(conn, limit: int) -> None:
    articles = conn.execute(f"SELECT * FROM ({SAMPLE_SQL}) s ORDER BY random() LIMIT %s", (limit,)).fetchall()
    log.info("Labelling %d articles with %s", len(articles), ollama.MODEL)
    started, unreadable = time.time(), 0
    with httpx.Client(timeout=600) as client:
        for n, (article_id, title, snippet) in enumerate(articles, 1):
            out, _ = ollama.chat(client, ollama.MODEL, SYSTEM, article_text(title, snippet), SCHEMA, 2048)
            try:
                answer = json.loads(out)
                category, region = answer["category"], answer["region"]
            except (json.JSONDecodeError, KeyError, TypeError):
                unreadable += 1  # left unlabelled; a later run samples again
                continue
            conn.execute("INSERT INTO article_categories (article_id, category, region, model) VALUES (%s, %s, %s, %s) "
                         "ON CONFLICT (article_id) DO NOTHING", (article_id, category, region, ollama.MODEL))
            conn.commit()
            if n % 100 == 0 or n == len(articles):
                log.info("  %d / %d, %.1f s per article, %d unreadable",
                         n, len(articles), (time.time() - started) / n, unreadable)


def fit(x: np.ndarray, y: np.ndarray, classes: int) -> torch.nn.Linear:
    """Softmax regression on unit vectors: one linear layer, full batch, light weight decay."""
    torch.manual_seed(0)
    layer = torch.nn.Linear(x.shape[1], classes)
    optimizer = torch.optim.Adam(layer.parameters(), lr=0.01, weight_decay=1e-4)
    xs, ys = torch.from_numpy(x), torch.from_numpy(y)
    for _ in range(300):
        optimizer.zero_grad()
        torch.nn.functional.cross_entropy(layer(xs), ys).backward()
        optimizer.step()
    return layer


def predict(layer: torch.nn.Linear, x: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        return layer(torch.from_numpy(x)).argmax(1).numpy()


def unit(rows) -> np.ndarray:
    x = np.vstack([v.to_numpy() for v in rows]).astype(np.float32)
    return x / np.linalg.norm(x, axis=1, keepdims=True)


def label_stories(conn) -> None:
    """The LLM labels the front-page stories that it hasn't labelled yet, from their main headlines."""
    from app import front, moments  # imported here: app.front imports CATEGORIES from this module
    names = moments.outlet_names(conn)
    ids = [s["id"] for s in front.pool(conn)[2]]
    todo = [r[0] for r in conn.execute("SELECT id FROM issues WHERE id = ANY(%s) AND category_by IS DISTINCT FROM 'llm'",
                                       (ids,)).fetchall()]
    log.info("Labelling %d front-page stories with %s (%d already done)", len(todo), ollama.MODEL, len(ids) - len(todo))
    unreadable = 0
    with httpx.Client(timeout=600) as client:
        for n, issue_id in enumerate(todo, 1):
            articles, _ = moments.compute(conn, issue_id, names)
            heads = [h["title"] for h in moments.headlines(articles)[:front.MAIN_HEADLINES]]
            out, _ = ollama.chat(client, ollama.MODEL, SYSTEM,
                                 "Headlines of one news story:\n" + "\n".join(f"- {t}" for t in heads), SCHEMA, 2048)
            try:
                answer = json.loads(out)
                category, region = answer["category"], answer["region"]
            except (json.JSONDecodeError, KeyError, TypeError):
                unreadable += 1  # keeps the classifier's label; the next run tries again
                continue
            conn.execute("UPDATE issues SET category = %s, region = %s, category_by = 'llm' WHERE id = %s",
                         (category, region, issue_id))
            conn.commit()
            if n % 100 == 0 or n == len(todo):
                log.info("  %d / %d, %d unreadable", n, len(todo), unreadable)
        ollama.unload(client, ollama.MODEL)


def classify(conn) -> None:
    rows = conn.execute("""
        SELECT c.article_id, c.category, c.region, e.embedding
        FROM article_categories c JOIN article_embeddings e ON e.article_id = c.article_id
    """).fetchall()
    if len(rows) < 100:
        raise SystemExit(f"Only {len(rows)} labelled articles. Run python -m app.categories --label 1500 first.")
    names = list(CATEGORIES)
    x = unit([r[3] for r in rows])
    held = np.array([r[0] % 10 == 0 for r in rows])
    targets = {"category": (np.array([names.index(r[1]) for r in rows]), names),
               "region": (np.array([REGIONS.index(r[2]) for r in rows]), REGIONS)}

    for what, (y, classes) in targets.items():
        right = predict(fit(x[~held], y[~held], len(classes)), x[held]) == y[held]
        per = ", ".join(f"{c} {right[y[held] == k].mean():.0%} ({(y[held] == k).sum()})"
                        for k, c in enumerate(classes) if (y[held] == k).any())
        log.info("%s: %d labelled, held out %d, agrees with the LLM %.1f%% [%s]",
                 what, len(rows), held.sum(), 100 * right.mean(), per)

    stories = conn.execute("SELECT id, centroid FROM issues WHERE category_by IS DISTINCT FROM 'llm'").fetchall()
    centres = unit([r[1] for r in stories])
    found = {what: [classes[k] for k in predict(fit(x, y, len(classes)), centres)]
             for what, (y, classes) in targets.items()}
    conn.execute("""
        UPDATE issues SET category = u.category, region = u.region, category_by = 'classifier'
        FROM unnest(%s::bigint[], %s::text[], %s::text[]) AS u(id, category, region)
        WHERE issues.id = u.id
    """, ([r[0] for r in stories], found["category"], found["region"]))
    conn.commit()
    counts = {c: found["category"].count(c) for c in names}
    log.info("Classifier labelled %d stories: %s; India %d, World %d", len(stories), counts,
             found["region"].count("India"), found["region"].count("World"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", type=int, metavar="N", help="the LLM labels N more articles, one per story")
    parser.add_argument("--stories", action="store_true", help="the LLM labels the front-page stories")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with connect_with_vectors() as conn:
        if args.label:
            label(conn, args.label)
        elif args.stories:
            label_stories(conn)
        else:
            classify(conn)


if __name__ == "__main__":
    main()
