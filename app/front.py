"""The front page, "Today's stories" (D-032).

Run with:  python -m app.front --titles 60   (the LLM writes clean titles for the 60 top front-page stories)

The front page shows the stories most reported in the 48 hours before the last fetch, ranked by how many different
outlets reported them, then by reports. Stories with fewer than MIN_REPORTS reports and repeating columns (horoscopes,
"gold rate today", paid content) are left out; search still finds them. A story's topic tab is the most common
section in its articles' links (/world/, /business/, ...); stories whose links only say /news/ go under More.

A title is 5 to 9 plain words written by the LLM from the story's main headlines, with the same check as the dot
labels (every name and number must be in the headlines), else the trimmed central headline. Titles are keyed by the
story's newest moment, so a story gets a new title only when it gets a new newest dot.
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
from app.db import connect_with_vectors

WINDOW = timedelta(hours=48)
MIN_REPORTS = 4
MIN_TAB = 3        # tabs with fewer stories are hidden
MAIN_HEADLINES = 6
TABS = ["India", "World", "Business", "Sports", "Entertainment", "Tech", "More"]

# Link path words -> topic. "junk" marks repeating columns and paid content.
SECTIONS = {
    "World": {"world", "world-news", "international", "us-news", "australia-news", "global", "nri", "us", "europe"},
    "India": {"india", "india-news", "national", "city", "cities", "politics-and-nation", "delhi-news", "states"},
    "Business": {"business", "markets", "market", "money", "industry", "companies", "economy", "wealth", "small-biz",
                 "real-estate", "stocks", "personal-finance", "india-business", "banking"},
    "Sports": {"sports", "sport", "cricket", "football", "tennis", "hockey"},
    "Entertainment": {"entertainment", "movies", "tv", "bollywood", "etimes", "htcity", "celebrities", "music", "web-series"},
    "Tech": {"technology", "tech", "gadgets-and-appliances", "gadgets", "ai", "sci-tech", "science", "auto-news", "auto"},
    "junk": {"astrology", "horoscope", "brandhub", "pr-release", "trending", "trending-news"},
}
JUNK_TITLE = re.compile(r"horoscope|rashifal|quote of the day|sensex today|nifty today|gold (rate|price)s? today|"
                        r"silver (rate|price)s? today|petrol.*price.*today|lottery result|wishes|greetings", re.I)

SYSTEM = ("You write headlines for a news front page read by people of every age. Given the main headlines of one "
          "news story, write ONE plain English title of 5 to 9 words saying what the story is about. Use only facts "
          "in the headlines. Keep names exactly as written. No quotes, no opinion, no outlet names, no 'live'.")
SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}

CANDIDATES_SQL = """
    WITH recent AS (
        SELECT ai.issue_id, count(DISTINCT a.source_domain) AS outlets, count(*) AS recent
        FROM articles a JOIN article_issues ai ON ai.article_id = a.id
        WHERE a.published_at >= %(since)s AND btrim(a.title) <> ''
        GROUP BY ai.issue_id
    )
    SELECT r.issue_id, r.outlets, r.recent, i.article_count, i.first_seen, i.last_seen
    FROM recent r JOIN issues i ON i.id = r.issue_id
    WHERE i.article_count >= %(min)s
    ORDER BY r.outlets DESC, r.recent DESC, i.id
"""

log = logging.getLogger("front")


def section(url: str) -> str | None:
    """The topic named by the first 3 parts of a link's path, or None when it only says /news/ or /article/."""
    for part in [p for p in urlparse(url).path.lower().split("/") if p][:3]:
        for topic, words in SECTIONS.items():
            if part in words:
                return topic
    return None


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
    for issue_id, outlets, recent, count, first, last in found:
        arts = links[issue_id]
        topics = Counter(t for t in (section(u) for u, _ in arts) if t)
        topic = topics.most_common(1)[0][0] if topics else "More"
        if topic == "junk" or 2 * sum(bool(JUNK_TITLE.search(t)) for _, t in arts) > len(arts):
            continue
        stories.append({"id": issue_id, "topic": topic, "outlets": outlets, "recent": recent, "reports": count,
                        "first_seen": first, "last_seen": last})
    return checked, since, stories


def card(conn, story: dict, names: dict[str, str], checked, since) -> dict:
    """A story as the front page shows it: title, mini dot-path, latest moment, New / Developing tag."""
    articles, groups = moments.compute(conn, story["id"], names)
    keys = [moments.key_of(g) for g in groups]
    title = moments.rows(conn, "SELECT title FROM story_titles WHERE moment_key = %s", (keys[-1],))
    newest = moments.headlines(groups[-1])
    label = moments.rows(conn, "SELECT label FROM moment_labels WHERE moment_key = %s", (keys[-1],))
    first_day = story["first_seen"].astimezone(moments.IST).date()
    return {**story,
            "title": title[0][0] if title else moments.trim(moments.headlines(articles)[0]["title"]),
            "title_ai": bool(title),
            "new": story["first_seen"] >= since,
            "day": (checked.astimezone(moments.IST).date() - first_day).days + 1,
            "latest": label[0][0] if label else moments.trim(newest[0]["title"]),
            "latest_ai": bool(label),
            "latest_heads": [h["title"] for h in newest[:2]],
            "dots": [len(g) for g in groups]}


def front(conn, names: dict[str, str], topic: str, offset: int, limit: int) -> dict:
    checked, since, stories = pool(conn)
    counts = Counter(s["topic"] for s in stories)
    tabs = [{"name": t, "count": counts[t]} for t in TABS if counts[t] >= MIN_TAB]
    chosen = stories if topic == "Top" else [s for s in stories if s["topic"] == topic]
    return {"checked": checked, "since": since, "tabs": tabs, "total": len(chosen),
            "stories": [card(conn, s, names, checked, since) for s in chosen[offset:offset + limit]]}


def write_titles(conn, limit: int) -> None:
    """Titles, and the newest dot's label, for the top `limit` front-page stories that need them."""
    names = moments.outlet_names(conn)
    stories = pool(conn)[2][:limit]
    log.info("Writing titles for the top %d front-page stories with %s", len(stories), ollama.MODEL)
    done = Counter()
    with httpx.Client(timeout=600) as client:
        for s in stories:
            articles, groups = moments.compute(conn, s["id"], names)
            done["label " + moments.label_moment(conn, client, s["id"], groups[-1])] += 1
            key = moments.key_of(groups[-1])
            if conn.execute("SELECT 1 FROM story_titles WHERE moment_key = %s", (key,)).fetchone():
                done["title kept"] += 1
                continue
            heads = [h["title"] for h in moments.headlines(articles)[:MAIN_HEADLINES]]
            out, _ = ollama.chat(client, ollama.MODEL, SYSTEM, "Headlines:\n" + "\n".join(f"- {t}" for t in heads), SCHEMA, 2048)
            title = json.loads(out).get("title", "").strip().rstrip(".")
            if not (4 <= len(title.split()) <= 10 and moments.safe(title, heads)):
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
    parser.add_argument("--titles", type=int, metavar="N", required=True, help="write titles for the N top stories")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with connect_with_vectors() as conn:
        write_titles(conn, args.titles)


if __name__ == "__main__":
    main()
