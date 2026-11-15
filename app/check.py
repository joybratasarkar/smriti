"""Health report after a refresh (read-only): is the news fresh, did every feed bring news, did a story suddenly
grow huge (I-001), did the AI text checks reject much (I-022), did grouping get worse on the gold set.

Run with:  python -m app.check                                 (what came in during the last 12 hours)
           python -m app.check --since "2026-11-15 13:00+05:30"   (app.refresh passes its start time)

Prints the report and appends its numbers to logs/checks.jsonl, so the next report can compare with this one.
It never changes data. Warnings start with "!".
"""

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import front, gold, moments
from app.db import connect_with_vectors

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "logs" / "checks.jsonl"
STALE_HOURS = 24     # the last fetch is older than this: the automatic refresh isn't running
GROWTH = 300         # new articles in one story in one run
HUGE = 1000          # a story this big that is still growing may be several issues chained together (I-001)
FRONT_TOP = 60       # app.refresh writes titles and summaries for this many front-page stories
AI_TEXT_MIN = 0.6    # share of them that should have passed the checks
GOLD_DROP = 0.03     # precision or recall on the gold set fell by more than this since the last report


def feed_names() -> list[str]:
    lines = (ROOT / "feeds.txt").read_text().splitlines()
    return [l.split("|")[0].strip() for l in lines if l.strip() and not l.startswith("#")]


def previous() -> dict | None:
    try:
        lines = HISTORY.read_text().splitlines()
    except FileNotFoundError:
        return None
    return json.loads(lines[-1]) if lines else None


def check(conn, since: datetime, failed: str | None) -> tuple[list[str], dict]:
    now = datetime.now(timezone.utc)
    report, warn, m = [], [], {"time": now.isoformat(), "since": since.isoformat(), "failed": failed}
    if failed:
        warn.append(f"the refresh stopped at step '{failed}'; later steps did not run")

    last_fetch, newest = conn.execute("SELECT max(fetched_at), max(published_at) FROM articles").fetchone()
    m["last_fetch"] = last_fetch.isoformat()
    report.append(f"News: last fetch {last_fetch:%Y-%m-%d %H:%M %Z}, newest article {newest:%Y-%m-%d %H:%M %Z}")
    if now - last_fetch > timedelta(hours=STALE_HOURS):
        warn.append(f"the last fetch is {(now - last_fetch).days} days old")

    counts = dict(conn.execute("SELECT source_name, count(*) FROM articles WHERE fetched_at >= %s GROUP BY 1",
                               (since,)).fetchall())
    feeds = feed_names()
    m["new_articles"] = sum(counts.values())
    m["empty_feeds"] = [f for f in feeds if not counts.get(f)]
    report.append(f"New articles: {m['new_articles']} ({sum(counts.get(f, 0) for f in feeds)} from the "
                  f"{len(feeds)} RSS feeds, the rest from GDELT)")
    if m["empty_feeds"]:
        warn.append(f"no new articles from {len(m['empty_feeds'])} feed(s): {', '.join(m['empty_feeds'])}")

    grown = conn.execute("""
        SELECT i.id, count(*), i.article_count, i.label FROM article_issues ai JOIN issues i ON i.id = ai.issue_id
        WHERE ai.assigned_at >= %s GROUP BY i.id ORDER BY 2 DESC LIMIT 5
    """, (since,)).fetchall()
    m["top_growth"] = [{"id": i, "added": n, "size": size} for i, n, size, _ in grown]
    report.append("Stories that grew most: " + ("; ".join(f"#{i} +{n} ({size}) {label[:50]}"
                                                         for i, n, size, label in grown) or "none"))
    for i, n, size, label in grown:
        if n > GROWTH or size > HUGE:
            warn.append(f"story #{i} grew by {n} to {size} articles; check it is still one issue: {label[:60]}")

    names = moments.outlet_names(conn)
    top = front.pool(conn)[2][:FRONT_TOP]
    keys = [moments.key_of(moments.compute(conn, s["id"], names)[1][-1]) for s in top]
    titled, summarised = (conn.execute(f"SELECT count(*) FROM {table} WHERE moment_key = ANY(%s)", (keys,)).fetchone()[0]
                          for table in ("story_titles", "story_summaries"))
    m["front_stories"], m["ai_titles"], m["ai_summaries"] = len(top), titled, summarised
    report.append(f"Front page: {len(top)} top stories, {titled} with an AI title, {summarised} with a summary")
    if not top:
        warn.append("the front page is empty: no story with 4+ reports in the 48 hours before the last fetch")
    elif min(titled, summarised) < AI_TEXT_MIN * len(top):
        warn.append("many front-page stories have no AI title or summary (failed the checks, or the step did not run)")

    rows = gold.story_rows(conn)
    if rows:
        *_, m["gold_precision"], m["gold_recall"] = gold.confusion(rows, lambda r: r[3])
        report.append(f"Gold set: precision {m['gold_precision']:.2f}, recall {m['gold_recall']:.2f} ({len(rows)} pairs)")
        last = previous()
        for key in ("gold_precision", "gold_recall"):
            if last and last.get(key) is not None and m[key] < last[key] - GOLD_DROP:
                warn.append(f"{key.replace('_', ' ')} fell from {last[key]:.2f} to {m[key]:.2f}")

    m["warnings"] = warn
    return report + [f"! {w}" for w in warn] + ([] if warn else ["No warnings."]), m


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", type=datetime.fromisoformat, help="start of the run (default: 12 hours ago)")
    parser.add_argument("--failed", metavar="STEP", help="the refresh step that failed, if any")
    args = parser.parse_args()
    since = args.since or datetime.now(timezone.utc) - timedelta(hours=12)
    if since.tzinfo is None:
        since = since.astimezone()
    with connect_with_vectors() as conn:
        lines, metrics = check(conn, since, args.failed)
    print("\n".join(lines))
    HISTORY.parent.mkdir(exist_ok=True)
    with HISTORY.open("a") as f:
        f.write(json.dumps(metrics) + "\n")


if __name__ == "__main__":
    main()
