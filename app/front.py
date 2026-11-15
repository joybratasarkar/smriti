"""The front page, "Today's stories" (D-032).

Run with:  python -m app.front --titles 60   (the LLM writes clean titles and summaries for the 60 top stories)

The front page shows the stories most reported in the 48 hours before the last fetch, ranked by how many different
outlets reported them, then by reports. Stories with fewer than MIN_REPORTS reports and repeating columns (horoscopes,
"gold rate today", paid content) are left out; search still finds them. Each story sits under its category tab
and its region (India / World), both from app.categories (D-036).

A title is 5 to 9 plain words written by the LLM from the story's main headlines, with the same check as the dot
labels (every name and number must be in the headlines, and the LLM referee must find that the headlines back
it, I-022), else the trimmed central headline. Titles are keyed by the story's newest moment, so a story gets a
new title only when it gets a new newest dot.

A summary is 2 short sentences (D-042): what the story is about, then the latest. It is written from the story's
main headlines and its newest dot's headlines, and each sentence gets the title's two checks; a summary that fails
is not shown. Keyed like the titles.
"""

import argparse
import json
import logging
import re
from collections import Counter
from datetime import timedelta
from urllib.parse import urlparse

import httpx

from app import moments, ollama
from app.categories import CATEGORIES
from app.db import connect_with_vectors

WINDOW = timedelta(hours=48)
MIN_REPORTS = 4
MIN_TAB = 3        # tabs with fewer stories are hidden
MAIN_HEADLINES = 6
TABS = list(CATEGORIES)

# Link path words that mark repeating columns and paid content.
JUNK_SECTIONS = {"astrology", "horoscope", "brandhub", "pr-release", "trending", "trending-news"}
JUNK_TITLE = re.compile(r"horoscope|rashifal|quote of the day|sensex today|nifty today|gold (rate|price)s? today|"
                        r"silver (rate|price)s? today|petrol.*price.*today|lottery result|wishes|greetings", re.I)

SYSTEM = ("You write headlines for a news front page read by people of every age. Given the main headlines of one "
          "news story, write ONE plain English title of 5 to 9 words saying what the story is about. Use only facts "
          "in the headlines. Keep names exactly as written. No quotes, no opinion, no outlet names, no 'live'.")
SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}

SUMMARY_SYSTEM = ("You write a short summary for a news front page read by people of every age. Given the main "
                  "headlines of one news story and its newest headlines, write exactly 2 short plain English "
                  "sentences: first what the story is about, then the latest development. At most 40 words in all. "
                  "Use only facts in the headlines; when one gives what someone said, say who said it. Keep names exactly as "
                  "written. No opinion, no outlet names, no 'live'.")
SUMMARY_SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}
SUMMARY_WORDS = 45
NEWEST_HEADLINES = 3

CANDIDATES_SQL = """
    WITH recent AS (
        SELECT ai.issue_id, count(DISTINCT a.source_domain) AS outlets, count(*) AS recent
        FROM articles a JOIN article_issues ai ON ai.article_id = a.id
        WHERE a.published_at >= %(since)s AND btrim(a.title) <> ''
        GROUP BY ai.issue_id
    )
    SELECT r.issue_id, r.outlets, r.recent, i.article_count, i.first_seen, i.last_seen, i.category, i.region
    FROM recent r JOIN issues i ON i.id = r.issue_id
    WHERE i.article_count >= %(min)s
    ORDER BY r.outlets DESC, r.recent DESC, i.id
"""

log = logging.getLogger("front")


def junk_section(url: str) -> bool:
    """True when one of the first 3 parts of a link's path names a repeating column or paid content."""
    return any(p in JUNK_SECTIONS for p in urlparse(url).path.lower().split("/")[:4])


def pool(conn) -> tuple:
    """(checked, since, stories): the front-page stories in rank order, junk left out."""
    checked = moments.rows(conn, "SELECT max(fetched_at) FROM articles")[0][0]
    since = checked - WINDOW
    found = moments.rows(conn, CANDIDATES_SQL, {"since": since, "min": MIN_REPORTS})
    links: dict[int, list[tuple]] = {}
    for issue_id, url, title in moments.rows(conn, "SELECT ai.issue_id, a.url, a.title FROM article_issues ai "
                                                   "JOIN articles a ON a.id = ai.article_id WHERE ai.issue_id = ANY(%s)",
                                             ([r[0] for r in found],)):
        links.setdefault(issue_id, []).append((url, title))
    stories = []
    for issue_id, outlets, recent, count, first, last, category, region in found:
        arts = links[issue_id]
        if 2 * sum(junk_section(u) or bool(JUNK_TITLE.search(t)) for u, t in arts) > len(arts):
            continue
        stories.append({"id": issue_id, "category": category or "Society", "region": region or "India",
                        "outlets": outlets, "recent": recent, "reports": count, "first_seen": first, "last_seen": last})
    return checked, since, stories


def card(conn, story: dict, names: dict[str, str], since) -> dict:
    """A story as the front page shows it: title, latest moment, New tag, and the dot-path the lead card draws."""
    articles, groups = moments.compute(conn, story["id"], names)
    keys = [moments.key_of(g) for g in groups]
    title = moments.rows(conn, "SELECT title FROM story_titles WHERE moment_key = %s", (keys[-1],))
    newest = moments.headlines(groups[-1])
    label = moments.rows(conn, "SELECT label FROM moment_labels WHERE moment_key = %s", (keys[-1],))
    summary = moments.rows(conn, "SELECT summary FROM story_summaries WHERE moment_key = %s", (keys[-1],))
    return {**story,
            "summary": summary[0][0] if summary else None,
            "title": title[0][0] if title else moments.trim(moments.headlines(articles)[0]["title"]),
            "title_ai": bool(title),
            "new": story["first_seen"] >= since,
            "latest": label[0][0] if label else moments.trim(newest[0]["title"]),
            "latest_ai": bool(label),
            "dots": [len(g) for g in groups]}


def front(conn, names: dict[str, str], topic: str, region: str, offset: int, limit: int) -> dict:
    """Stories of one category tab ("Top": all of them) and region ("All": both), most outlets first."""
    checked, since, stories = pool(conn)
    counts = Counter(s["category"] for s in stories)
    tabs = [{"name": t, "count": counts[t]} for t in TABS if counts[t] >= MIN_TAB]
    chosen = [s for s in stories if topic in ("Top", s["category"]) and region in ("All", s["region"])]
    return {"checked": checked, "since": since, "tabs": tabs, "total": len(chosen),
            "stories": [card(conn, s, names, since) for s in chosen[offset:offset + limit]]}


def write_summary(conn, client: httpx.Client, articles: list[dict], groups: list[list[dict]]) -> str:
    """The story's 2-sentence summary unless it has one: 'kept', 'written' or 'fallback' (failed the check)."""
    key = moments.key_of(groups[-1])
    if conn.execute("SELECT 1 FROM story_summaries WHERE moment_key = %s", (key,)).fetchone():
        return "kept"
    main = [h["title"] for h in moments.headlines(articles)[:MAIN_HEADLINES]]
    newest = [h["title"] for h in moments.headlines(groups[-1])[:NEWEST_HEADLINES] if h["title"] not in main]
    prompt = ("Main headlines:\n" + "\n".join(f"- {t}" for t in main) +
              "\nNewest headlines:\n" + "\n".join(f"- {t}" for t in newest or main[:1]))
    out, _ = ollama.chat(client, ollama.MODEL, SUMMARY_SYSTEM, prompt, SUMMARY_SCHEMA, 2048)
    try:
        summary = " ".join(json.loads(out).get("summary", "").split())
    except (json.JSONDecodeError, AttributeError):
        return "fallback"
    heads = main + newest
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", summary) if s]
    if not (1 <= len(sentences) <= 2 and len(summary.split()) <= SUMMARY_WORDS
            and all(moments.grounded(s, heads) and moments.supported(client, s.rstrip("."), heads) for s in sentences)):
        log.info("  summary failed the check: %s", summary)
        return "fallback"
    conn.execute("INSERT INTO story_summaries (moment_key, summary, model) VALUES (%s, %s, %s) "
                 "ON CONFLICT (moment_key) DO NOTHING", (key, summary, ollama.MODEL))
    conn.commit()
    return "written"


def write_titles(conn, limit: int) -> None:
    """Titles, summaries and the newest dot's label for the top `limit` front-page stories that need them."""
    names = moments.outlet_names(conn)
    stories = pool(conn)[2][:limit]
    log.info("Writing titles for the top %d front-page stories with %s", len(stories), ollama.MODEL)
    done = Counter()
    with httpx.Client(timeout=600) as client:
        for s in stories:
            articles, groups = moments.compute(conn, s["id"], names)
            done["label " + moments.label_moment(conn, client, s["id"], groups[-1])] += 1
            done["summary " + write_summary(conn, client, articles, groups)] += 1
            key = moments.key_of(groups[-1])
            if conn.execute("SELECT 1 FROM story_titles WHERE moment_key = %s", (key,)).fetchone():
                done["title kept"] += 1
                continue
            heads = [h["title"] for h in moments.headlines(articles)[:MAIN_HEADLINES]]
            out, _ = ollama.chat(client, ollama.MODEL, SYSTEM, "Headlines:\n" + "\n".join(f"- {t}" for t in heads), SCHEMA, 2048)
            try:
                title = json.loads(out).get("title", "").strip().rstrip(".")
            except (json.JSONDecodeError, AttributeError):  # an empty or broken answer, as in I-024
                title = ""
            if not (4 <= len(title.split()) <= 10 and moments.safe(title, heads)
                    and moments.supported(client, title, heads)):
                log.info("  failed the check: %s", title)
                done["title fallback"] += 1
                continue
            conn.execute("INSERT INTO story_titles (moment_key, title, model) VALUES (%s, %s, %s) "
                         "ON CONFLICT (moment_key) DO NOTHING", (key, title, ollama.MODEL))
            conn.commit()
            done["title written"] += 1
        ollama.unload(client, ollama.MODEL)
    log.info("Done: %s", dict(done))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--titles", type=int, metavar="N", required=True,
                        help="write titles and summaries for the N top stories")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with connect_with_vectors() as conn:
        write_titles(conn, args.titles)


if __name__ == "__main__":
    main()
