"""Fetch recent news from RSS feeds and GDELT and store it in Postgres.

Run with:  python -m app.fetch            (RSS feeds, last 7 days)
           python -m app.fetch --days 3
           python -m app.fetch --gdelt --days 60   (also backfill from GDELT bulk files)

GDELT is opt-in because it is a large download: one GKG file (~4 MB) per 15 minutes,
about 24 GB for 60 days. Only rows from the Indian outlets in GDELT_DOMAINS are kept.
The GDELT search API is not used: it answers HTTP 429 even to the first request (Oct 2026).

Safe to run repeatedly: articles are deduplicated by URL.
"""

import argparse
import calendar
import hashlib
import html
import io
import logging
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx

from app.db import connect, init_schema

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = ROOT / "feeds.txt"
LOG_FILE = ROOT / "logs" / "fetch.log"

USER_AGENT = "Mozilla/5.0 (compatible; smriti-news-archive/0.1)"
MAX_ATTEMPTS = 3
SNIPPET_MAX_CHARS = 500

GDELT_FILE_URL = "https://data.gdeltproject.org/gdeltv2/{stamp}.gkg.csv.zip"
GDELT_STEP = timedelta(minutes=15)  # GDELT publishes one GKG file every 15 minutes
GDELT_LAG = timedelta(minutes=30)   # the newest file appears a few minutes after its timestamp
# The Indian outlets we also read by RSS. GDELT's GKG files cover English-language news only.
GDELT_DOMAINS = {
    "thehindu.com", "indianexpress.com", "hindustantimes.com", "indiatoday.in", "livemint.com",
    "news18.com", "timesofindia.indiatimes.com", "economictimes.indiatimes.com", "ndtv.com", "scroll.in",
}
# Columns of a GKG 2.1 row (tab-separated)
GKG_DATE, GKG_URL, GKG_EXTRAS = 1, 4, 26

TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}

# Outlets publish one article under several section paths, so a URL can be new while the article isn't (I-019):
# the same site, headline and snippet within a day is the same article.
INSERT_SQL = """
    INSERT INTO articles
        (url, title, snippet, source_name, source_domain, language,
         published_at, content_hash, provider)
    SELECT %(url)s, %(title)s, %(snippet)s, %(source_name)s, %(source_domain)s, %(language)s,
           %(published_at)s::timestamptz, %(content_hash)s, %(provider)s
    WHERE NOT EXISTS (
        SELECT 1 FROM articles d
        WHERE d.source_domain = %(source_domain)s AND d.content_hash = %(content_hash)s
          AND abs(extract(epoch FROM coalesce(d.published_at, d.fetched_at) - coalesce(%(published_at)s::timestamptz, now()))) < 86400)
    ON CONFLICT (url) DO NOTHING
"""

log = logging.getLogger("fetch")


# ---------- small helpers ----------

def normalize_url(url: str) -> str:
    """Lowercase the host, drop the #fragment and tracking parameters."""
    parts = urlsplit(url.strip())
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), ""))


def domain_of(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.")


def clean_text(text: str | None) -> str:
    """Strip HTML tags and entities, collapse whitespace."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def make_snippet(summary: str | None) -> str | None:
    text = clean_text(summary)
    if len(text) > SNIPPET_MAX_CHARS:
        text = text[:SNIPPET_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return text or None


def content_hash(title: str, snippet: str | None) -> str:
    normalized = (title.lower().strip() + "\n" + (snippet or "").lower().strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def iso_language(code: str | None) -> str | None:
    """'en-US' -> 'en'."""
    if not code:
        return None
    return code.split("-")[0].split("_")[0].lower() or None


def make_article(*, url, title, snippet, source_name, language, published_at, provider) -> dict:
    url = normalize_url(url)
    title = clean_text(title)
    return {
        "url": url,
        "title": title,
        "snippet": snippet,
        "source_name": source_name,
        "source_domain": domain_of(url),
        "language": language,
        "published_at": published_at,
        "content_hash": content_hash(title, snippet),
        "provider": provider,
    }


def get_with_retries(client: httpx.Client, url: str, params: dict | None = None) -> httpx.Response | None:
    """GET with retries on network errors, 429 and 5xx. Returns None if it never succeeds."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        wait = 2 ** attempt * 2  # 4s, 8s, 16s
        try:
            resp = client.get(url, params=params)
        except httpx.HTTPError as e:
            log.warning("Request failed (%s) for %s, attempt %d/%d", type(e).__name__, url, attempt, MAX_ATTEMPTS)
        else:
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    wait = min(int(retry_after), 120)
                log.warning("HTTP %d from %s, attempt %d/%d", resp.status_code, url, attempt, MAX_ATTEMPTS)
            else:
                log.error("HTTP %d from %s, not retrying", resp.status_code, url)
                return None
        if attempt < MAX_ATTEMPTS:
            time.sleep(wait)
    log.error("Giving up on %s after %d attempts", url, MAX_ATTEMPTS)
    return None


def save(conn, articles: list[dict]) -> int:
    """Insert articles, skipping URLs we already have. Returns how many were new."""
    inserted = 0
    with conn.cursor() as cur:
        for article in articles:
            cur.execute(INSERT_SQL, article)
            inserted += cur.rowcount
    conn.commit()
    return inserted


# ---------- RSS ----------

def read_feeds_file() -> list[tuple[str, str]]:
    feeds = []
    for line in FEEDS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" not in line:
            log.warning("Skipping malformed line in feeds.txt: %r", line)
            continue
        name, url = (part.strip() for part in line.split("|", 1))
        feeds.append((name, url))
    return feeds


def parse_feed(name: str, body: bytes, cutoff: datetime) -> tuple[list[dict], int]:
    """Turn a feed into article dicts. Returns (articles, number skipped as too old)."""
    parsed = feedparser.parse(body)
    language = iso_language(parsed.feed.get("language"))
    articles, too_old = [], 0
    for entry in parsed.entries:
        link, title = entry.get("link"), entry.get("title")
        if not link or not title:
            continue
        struct = entry.get("published_parsed") or entry.get("updated_parsed")
        published_at = datetime.fromtimestamp(calendar.timegm(struct), timezone.utc) if struct else None
        if published_at and published_at < cutoff:
            too_old += 1
            continue
        articles.append(make_article(
            url=link,
            title=title,
            snippet=make_snippet(entry.get("summary")),
            source_name=name,
            language=iso_language(entry.get("language")) or language,
            published_at=published_at,
            provider="rss",
        ))
    if parsed.bozo and not parsed.entries:
        log.warning("%s: feed could not be parsed (%s)", name, parsed.get("bozo_exception"))
    return articles, too_old


def fetch_rss(conn, client: httpx.Client, cutoff: datetime) -> dict:
    stats = {"feeds_ok": 0, "feeds_failed": 0, "seen": 0, "inserted": 0}
    for name, url in read_feeds_file():
        resp = get_with_retries(client, url)
        if resp is None:
            stats["feeds_failed"] += 1
            continue
        articles, too_old = parse_feed(name, resp.content, cutoff)
        if not articles:
            log.warning("%s: no articles in the last window (%d older entries skipped) - %s", name, too_old, url)
        inserted = save(conn, articles)
        log.info("RSS  %-22s %3d entries, %3d new, %3d too old", name, len(articles), inserted, too_old)
        stats["feeds_ok"] += 1
        stats["seen"] += len(articles)
        stats["inserted"] += inserted
    return stats


# ---------- GDELT ----------

def gdelt_stamps(conn, cutoff: datetime, last: datetime) -> list[datetime]:
    """15-minute file timestamps from the cutoff to `last` that we haven't read yet."""
    stamp = cutoff.replace(minute=cutoff.minute - cutoff.minute % 15, second=0, microsecond=0)
    done = {row[0] for row in conn.execute("SELECT stamp FROM gdelt_files WHERE stamp >= %s", (stamp,))}
    stamps = []
    while stamp <= last:
        if stamp not in done:
            stamps.append(stamp)
        stamp += GDELT_STEP
    return stamps


def gdelt_file(client: httpx.Client, stamp: datetime) -> list[dict] | None:
    """Articles from our outlets in one GKG file. None if the file can't be fetched or read."""
    url = GDELT_FILE_URL.format(stamp=stamp.strftime("%Y%m%d%H%M%S"))
    resp = get_with_retries(client, url)
    if resp is None:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            text = z.read(z.namelist()[0]).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, IndexError) as e:
        log.error("GDELT file %s could not be read: %s", url, e)
        return None

    articles = []
    for line in text.splitlines():
        row = line.split("\t")
        if len(row) <= GKG_EXTRAS or domain_of(row[GKG_URL]) not in GDELT_DOMAINS:
            continue
        title = re.search(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", row[GKG_EXTRAS])
        if not title or not clean_text(title.group(1)):  # an empty tag gave 64 blank titles (I-017)
            continue
        articles.append(make_article(
            url=row[GKG_URL],
            title=title.group(1),
            snippet=None,
            source_name=domain_of(row[GKG_URL]),
            language="en",
            published_at=datetime.strptime(row[GKG_DATE], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc),
            provider="gdelt",
        ))
    return articles


def fetch_gdelt(conn, client: httpx.Client, cutoff: datetime) -> dict:
    stats = {"files": 0, "files_failed": 0, "seen": 0, "inserted": 0}
    stamps = gdelt_stamps(conn, cutoff, datetime.now(timezone.utc) - GDELT_LAG)
    if not stamps:
        log.info("GDELT: nothing new to read")
        return stats
    log.info("GDELT: %d files of ~4 MB from %s to %s", len(stamps),
             stamps[0].strftime("%Y-%m-%d %H:%M"), stamps[-1].strftime("%Y-%m-%d %H:%M"))

    day = {"seen": 0, "inserted": 0, "failed": 0}
    for i, stamp in enumerate(stamps):
        articles = gdelt_file(client, stamp)
        stats["files"] += 1
        if articles is None:
            stats["files_failed"] += 1  # not recorded in gdelt_files, so the next run retries it
            day["failed"] += 1
        else:
            conn.execute("INSERT INTO gdelt_files (stamp, articles) VALUES (%s, %s)", (stamp, len(articles)))
            inserted = save(conn, articles)  # commits the gdelt_files row together with the articles
            for d in (stats, day):
                d["seen"] += len(articles)
                d["inserted"] += inserted
        if i == len(stamps) - 1 or stamps[i + 1].date() != stamp.date():  # one log line per day
            log.info("GDELT %s  %4d articles, %4d new, %d files failed",
                     stamp.strftime("%Y-%m-%d"), day["seen"], day["inserted"], day["failed"])
            day = {"seen": 0, "inserted": 0, "failed": 0}
    return stats


# ---------- main ----------

def setup_logging() -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE)],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch recent news into Postgres.")
    parser.add_argument("--days", type=int, default=7, help="how far back to fetch (default 7)")
    parser.add_argument("--skip-rss", action="store_true", help="don't fetch RSS feeds")
    parser.add_argument("--gdelt", action="store_true", help="also backfill from GDELT bulk files (~24 GB for 60 days)")
    args = parser.parse_args()

    setup_logging()
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    log.info("Fetch started, keeping articles since %s", cutoff.strftime("%Y-%m-%d %H:%M UTC"))

    with connect() as conn, httpx.Client(timeout=30, follow_redirects=True,
                                         headers={"User-Agent": USER_AGENT}) as client:
        init_schema(conn)
        # RSS first: when both sources have the same URL, the RSS row (which has a snippet) wins.
        if not args.skip_rss:
            log.info("RSS done: %s", fetch_rss(conn, client, cutoff))
        if args.gdelt:
            log.info("GDELT done: %s", fetch_gdelt(conn, client, cutoff))
    log.info("Fetch finished")


if __name__ == "__main__":
    main()
