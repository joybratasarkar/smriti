"""Fetch recent news from RSS feeds and GDELT and store it in Postgres.

Run with:  python -m app.fetch            (RSS feeds, last 7 days)
           python -m app.fetch --days 3
           python -m app.fetch --gdelt    (also backfill from GDELT; experimental, see below)

GDELT is off by default: during testing (Oct 2026) it rate-limited us (HTTP 429)
even with 90 s between requests, and accepted requests returned no articles.

Safe to run repeatedly: articles are deduplicated by URL.
"""

import argparse
import calendar
import hashlib
import html
import logging
import re
import time
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

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERY = "sourcecountry:IN"   # articles from Indian outlets, any language
GDELT_WINDOW = timedelta(hours=1)  # one request per window
GDELT_MAX_RECORDS = 250            # GDELT's hard cap per request
GDELT_PAUSE_SECONDS = 60           # documented limit is 5 s, but in practice it throttles far harder

# GDELT returns language names; map the common ones to ISO 639-1 codes.
GDELT_LANGUAGES = {
    "English": "en", "Hindi": "hi", "Bengali": "bn", "Tamil": "ta", "Telugu": "te",
    "Marathi": "mr", "Gujarati": "gu", "Kannada": "kn", "Malayalam": "ml",
    "Punjabi": "pa", "Urdu": "ur", "Oriya": "or", "Nepali": "ne",
}

TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}

INSERT_SQL = """
    INSERT INTO articles
        (url, title, snippet, source_name, source_domain, language,
         published_at, content_hash, provider)
    VALUES
        (%(url)s, %(title)s, %(snippet)s, %(source_name)s, %(source_domain)s, %(language)s,
         %(published_at)s, %(content_hash)s, %(provider)s)
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

def gdelt_start(conn, cutoff: datetime) -> datetime:
    """Resume from the newest GDELT article we have, but never go back further than the cutoff."""
    row = conn.execute("SELECT max(published_at) FROM articles WHERE provider = 'gdelt'").fetchone()
    newest = row[0]
    return max(newest, cutoff) if newest else cutoff


def gdelt_request(client: httpx.Client, start: datetime, end: datetime) -> list[dict] | None:
    params = {
        "query": GDELT_QUERY,
        "mode": "artlist",
        "format": "json",
        "sort": "datedesc",
        "maxrecords": GDELT_MAX_RECORDS,
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end.strftime("%Y%m%d%H%M%S"),
    }
    for attempt in range(1, MAX_ATTEMPTS + 1):
        resp = get_with_retries(client, GDELT_URL, params)
        if resp is None:
            return None
        # GDELT reports rate limiting as a plain-text message rather than an error code.
        if resp.text.startswith("Please limit requests"):
            log.warning("GDELT rate limit hit, waiting (attempt %d/%d)", attempt, MAX_ATTEMPTS)
            time.sleep(GDELT_PAUSE_SECONDS * 2 * attempt)
            continue
        if not resp.text.strip():
            return []  # GDELT returns an empty body when nothing matches
        try:
            return resp.json().get("articles", [])
        except ValueError:
            log.error("GDELT returned invalid JSON for %s - %s: %r", start, end, resp.text[:200])
            return None
    return None


def fetch_gdelt(conn, client: httpx.Client, cutoff: datetime) -> dict:
    stats = {"windows": 0, "windows_failed": 0, "windows_capped": 0, "seen": 0, "inserted": 0}
    now = datetime.now(timezone.utc)
    start = gdelt_start(conn, cutoff)
    total_windows = max(1, int((now - start) / GDELT_WINDOW) + 1)
    log.info("GDELT: fetching %s to %s in %d windows (about %d min)",
             start.strftime("%Y-%m-%d %H:%M"), now.strftime("%Y-%m-%d %H:%M"),
             total_windows, total_windows * GDELT_PAUSE_SECONDS // 60)

    while start < now:
        end = min(start + GDELT_WINDOW, now)
        stats["windows"] += 1
        items = gdelt_request(client, start, end)
        if items is None:
            stats["windows_failed"] += 1
        else:
            if len(items) >= GDELT_MAX_RECORDS:
                stats["windows_capped"] += 1
            articles = [
                make_article(
                    url=item["url"],
                    title=item.get("title") or "",
                    snippet=None,
                    source_name=item.get("domain") or domain_of(item["url"]),
                    language=GDELT_LANGUAGES.get(item.get("language"), (item.get("language") or "").lower() or None),
                    published_at=datetime.strptime(item["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc),
                    provider="gdelt",
                )
                for item in items
                if item.get("url") and item.get("title") and item.get("seendate")
            ]
            inserted = save(conn, articles)
            stats["seen"] += len(articles)
            stats["inserted"] += inserted
            log.info("GDELT %s  %3d articles, %3d new%s", start.strftime("%Y-%m-%d %H:%M"),
                     len(articles), inserted, "  (hit 250 cap)" if len(items) >= GDELT_MAX_RECORDS else "")
        start = end
        if start < now:
            time.sleep(GDELT_PAUSE_SECONDS)
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
    parser.add_argument("--gdelt", action="store_true", help="also backfill from GDELT (slow, experimental)")
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
            stats = fetch_gdelt(conn, client, cutoff)
            log.info("GDELT done: %s", stats)
            if stats["windows_capped"]:
                log.warning("%d GDELT windows hit the 250-article cap, so some articles in those hours were missed",
                            stats["windows_capped"])
    log.info("Fetch finished")


if __name__ == "__main__":
    main()
