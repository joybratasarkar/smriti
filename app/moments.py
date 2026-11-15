"""Key moments of a story, the dots on its timeline path (D-030).

Run with:  python -m app.moments --label 200   (the LLM writes short labels for the moments of the 200 biggest stories)

A story's articles are cut into at most MAX_MOMENTS moments: start with one moment per day (Indian time) and keep
merging the two most alike neighbours, penalised for quiet days between them and for size. Moments are computed when
a story is requested, so they follow the grouping as it changes. Only the labels are stored (moment_labels), keyed by
the moment's articles: when a moment gains or loses articles its old label no longer applies and the trimmed central
headline is shown until it is labelled again.

A label is 4 to 7 plain words written by the LLM from the moment's own headlines. Every name and number in it must
appear in those headlines, and the LLM as referee must find that the headlines back what it claims (I-022),
otherwise the trimmed headline is used (the LLM gets names wrong, I-002, and can change a fact).
"""

import argparse
import hashlib
import json
import logging
import re
from zoneinfo import ZoneInfo

import httpx
import numpy as np
from psycopg.rows import tuple_row

from app import ollama
from app.db import connect_with_vectors

MAX_MOMENTS = 7
MIN_PATH = 4       # stories with fewer articles show a plain list
HEADS = 40         # headlines sent per moment
QUIET_PENALTY = 0.02
SIZE_PENALTY = 0.5
TINY = 0.04        # a moment under this share of the story merges first
LABEL_HEADLINES = 6
IST = ZoneInfo("Asia/Kolkata")

SYSTEM = ("You write labels for a news timeline read by people of every age. Given headlines about one moment "
          "of a news story, write ONE plain English label of 4 to 7 words saying what happened. Use only facts "
          "in the headlines. Keep names exactly as written. No quotes, no opinion, no outlet names, no 'live'.")
SCHEMA = {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}

ARTICLES_SQL = """
    SELECT a.id, a.title, a.url, a.source_name, a.source_domain, coalesce(a.published_at, a.fetched_at), e.embedding
    FROM article_issues ai JOIN articles a ON a.id = ai.article_id JOIN article_embeddings e ON e.article_id = a.id
    WHERE ai.issue_id = %s AND btrim(a.title) <> ''
    ORDER BY 6, a.id
"""

log = logging.getLogger("moments")


def rows(conn, sql: str, params=()) -> list[tuple]:
    """Plain tuples whatever the connection's row factory (the API's is dict_row)."""
    return conn.cursor(row_factory=tuple_row).execute(sql, params).fetchall()


def checked(conn):
    """When the news the stories cover was fetched: the newest article that is already in a story. While a refresh
    runs, newer articles are fetched but not grouped yet; "today" and "no reports since" follow the stories."""
    return rows(conn, "SELECT max(a.fetched_at) FROM articles a JOIN article_issues ai ON ai.article_id = a.id")[0][0]


def outlet_names(conn) -> dict[str, str]:
    """Site -> the feed's name for it, so a GDELT row ('hindustantimes.com') reads like an RSS one (I-020)."""
    names = {}
    for domain, name in rows(conn, "SELECT DISTINCT source_domain, source_name FROM articles ORDER BY 1, 2"):
        if name != domain:
            names.setdefault(domain, name)
    return names


def split(articles: list[dict]) -> list[list[dict]]:
    groups = []
    for a in articles:
        if groups and groups[-1][-1]["day"] == a["day"]:
            groups[-1].append(a)
        else:
            groups.append([a])

    def centre(group):
        v = np.sum([a["vec"] for a in group], axis=0)
        return v / np.linalg.norm(v)

    total = len(articles)
    while len(groups) > MAX_MOMENTS:
        def score(k):
            a, b = groups[k], groups[k + 1]
            quiet = (b[0]["day"] - a[-1]["day"]).days - 1
            tiny = 0.15 if min(len(a), len(b)) < TINY * total else 0.0
            return float(centre(a) @ centre(b)) - QUIET_PENALTY * quiet - SIZE_PENALTY * (len(a) + len(b)) / total + tiny
        k = max(range(len(groups) - 1), key=score)
        groups[k:k + 2] = [groups[k] + groups[k + 1]]
    return groups


def headlines(group: list[dict]) -> list[dict]:
    """Distinct headlines, most central first; copies of one headline are folded into its outlets."""
    v = np.sum([a["vec"] for a in group], axis=0)
    v /= np.linalg.norm(v)
    out, seen = [], {}
    for a in sorted(group, key=lambda a: -float(a["vec"] @ v)):
        key = a["title"].strip().lower()
        if key not in seen:
            seen[key] = {"title": a["title"], "time": a["time"], "outlets": []}
            out.append(seen[key])
        seen[key]["outlets"].append({"name": a["source"], "url": a["url"]})
    return out


def trim(title: str) -> str:
    t = re.sub(r"\s*\|.*$", "", title).strip()
    t = re.sub(r"^(breaking news live updates|live updates?|live)\s*[:|-]\s*", "", t, flags=re.I)
    return t if len(t) <= 70 else t[:66].rsplit(" ", 1)[0].rstrip(",:;") + "…"


def safe(label: str, titles: list[str]) -> bool:
    """4 to 7 words (a little slack), and every capitalised word or number is in the headlines."""
    return 3 <= len(label.split()) <= 9 and grounded(label, titles)


def grounded(text: str, titles: list[str]) -> bool:
    """Every capitalised word and number of `text` appears in the headlines (commas in numbers ignored)."""
    heads = re.sub(r"(?<=\d),(?=\d)", "", " ".join(titles).lower())
    for w in text.split():
        w = re.sub(r"[^\w'-]", "", w.replace(",", "")).strip("'")
        if w and (any(c.isupper() for c in w) or any(c.isdigit() for c in w)) and w.lower() not in heads:
            return False
    return True


REFEREE = ("You check a short news title against the headlines it was written from. A title may summarise several "
           "headlines, use other words and leave details out: that is fine. It is wrong only when it states a fact "
           "the headlines contradict or never say, for example 'shot' when the headlines say 'shot at' or 'firing', "
           "'killed' when they say 'threatened' or 'injured', a different number, a plan or threat stated as done, "
           "the wrong person doing something. First copy the headline that best backs the title, then give the "
           "verdict. Return JSON only.")
REFEREE_SCHEMA = {"type": "object", "properties": {"evidence": {"type": "string"},
                                                   "verdict": {"type": "string", "enum": ["fine", "wrong"]}},
                  "required": ["evidence", "verdict"]}


def supported(client: httpx.Client, text: str, titles: list[str]) -> bool:
    """The LLM as referee (I-022): do the headlines back what this label or title claims? safe() only checks that
    its names and numbers appear in them, which let "Tiger Shroff shot in Juhu" through (he was shot at).
    On the 53 front-page titles of 2026-10-26 plus 4 planted false ones it rejected both Tiger Shroff titles, 2 of
    the 4 planted ones (safe() catches a third, a changed number) and 3 others, 1 of them a false alarm."""
    out, _ = ollama.chat(client, ollama.MODEL, REFEREE,
                         f"Title: {text}\nHeadlines:\n" + "\n".join(f"- {t}" for t in titles), REFEREE_SCHEMA, 2048)
    try:
        return json.loads(out)["verdict"] == "fine"
    except (json.JSONDecodeError, KeyError, TypeError):
        return False  # an unreadable verdict is not a yes


def key_of(group: list[dict]) -> str:
    return hashlib.md5(",".join(str(a["id"]) for a in sorted(group, key=lambda a: a["id"])).encode()).hexdigest()


def compute(conn, issue_id: int, names: dict[str, str]) -> tuple[list[dict], list[list[dict]]]:
    """(articles, groups): the story's articles in time order and its moments."""
    articles = []
    for aid, title, url, name, domain, when, vec in rows(conn, ARTICLES_SQL, (issue_id,)):
        local = when.astimezone(IST)
        v = vec.to_numpy().astype(np.float32)
        articles.append({"id": aid, "title": title, "url": url, "source": names.get(domain, name) if name == domain else name,
                         "time": local.isoformat(), "day": local.date(), "vec": v / np.linalg.norm(v)})
    if len(articles) < MIN_PATH:
        return articles, [articles] if articles else []
    return articles, split(articles)


def story_moments(conn, issue_id: int, names: dict[str, str]) -> dict:
    """What the API returns: mode 'path' (with moments) or 'list'."""
    articles, groups = compute(conn, issue_id, names)
    keys = [key_of(g) for g in groups]
    labels = dict(rows(conn, "SELECT moment_key, label FROM moment_labels WHERE moment_key = ANY(%s)", (keys,)))
    moments = []
    for g, k in zip(groups, keys):
        heads = headlines(g)
        moments.append({"start": str(g[0]["day"]), "end": str(g[-1]["day"]), "last": g[-1]["time"], "count": len(g),
                        "outlets": len({a["source"] for a in g}),  # source strength (D-042)
                        "label": labels.get(k) or trim(heads[0]["title"]), "labelled": k in labels,
                        "heads": heads[:HEADS], "more": max(0, len(heads) - HEADS)})
    summary = rows(conn, "SELECT summary FROM story_summaries WHERE moment_key = %s", (keys[-1],)) if keys else []
    return {"mode": "path" if len(articles) >= MIN_PATH else "list", "moments": moments,
            "summary": summary[0][0] if summary else None}


def label_moment(conn, client: httpx.Client, issue_id: int, group: list[dict]) -> str:
    """Label one moment unless it already has a label: 'kept', 'written' or 'fallback' (failed the check)."""
    k = key_of(group)
    if conn.execute("SELECT 1 FROM moment_labels WHERE moment_key = %s", (k,)).fetchone():
        return "kept"
    titles = [h["title"] for h in headlines(group)[:LABEL_HEADLINES]]
    out, _ = ollama.chat(client, ollama.MODEL, SYSTEM, "Headlines:\n" + "\n".join(f"- {t}" for t in titles), SCHEMA, 2048)
    try:
        label = json.loads(out).get("label", "").strip().rstrip(".")
    except (json.JSONDecodeError, AttributeError):  # an empty or broken answer: show the headline, as for a failed check
        return "fallback"
    if not (safe(label, titles) and supported(client, label, titles)):
        return "fallback"
    conn.execute("INSERT INTO moment_labels (moment_key, issue_id, label, model) VALUES (%s, %s, %s, %s) "
                 "ON CONFLICT (moment_key) DO NOTHING", (k, issue_id, label, ollama.MODEL))
    conn.commit()
    return "written"


def label_stories(conn, limit: int) -> None:
    names = outlet_names(conn)
    ids = [r[0] for r in conn.execute("SELECT id FROM issues WHERE article_count >= %s ORDER BY article_count DESC LIMIT %s",
                                      (MIN_PATH, limit)).fetchall()]
    log.info("Labelling the moments of %d stories with %s", len(ids), ollama.MODEL)
    done = {"written": 0, "fallback": 0, "kept": 0}
    with httpx.Client(timeout=600) as client:
        for n, issue_id in enumerate(ids, 1):
            _, groups = compute(conn, issue_id, names)
            for g in groups:
                done[label_moment(conn, client, issue_id, g)] += 1
            if n % 20 == 0:
                log.info("  %d / %d stories: %d labels written, %d failed the check, %d already there", n, len(ids),
                         done["written"], done["fallback"], done["kept"])
    log.info("Done: %d labels written, %d failed the check (trimmed headline shown), %d already there",
             done["written"], done["fallback"], done["kept"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", type=int, metavar="N", required=True, help="label the moments of the N biggest stories")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with connect_with_vectors() as conn:
        label_stories(conn, args.label)


if __name__ == "__main__":
    main()
