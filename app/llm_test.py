"""Compare local LLMs (via Ollama) on event extraction from CJP articles.

Run with:  python -m app.llm_test
           python -m app.llm_test --limit 10 --models qwen3.5:4b

For each sampled article: fetch the full text (kept in memory only, never stored),
ask each model for structured events, and measure JSON validity, whether each quote
appears verbatim in the text, seconds per article, and how much of the model is on GPU.
Results go to logs/llm_test_<date>.jsonl; a summary table is printed at the end.
"""

import argparse
import json
import logging
import re
from datetime import date
from pathlib import Path

import httpx
import trafilatura

from app import ollama
from app.db import connect

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "logs" / "llm_test.log"

DEFAULT_MODELS = [ollama.MODEL]  # qwen3.5:4b dropped: does not fit in 4 GB VRAM
USER_AGENT = "Mozilla/5.0 (compatible; smriti-news-archive/0.1)"
MAX_TEXT_CHARS = 6000   # keeps prompt + output inside the context window on a 4 GB GPU
NUM_CTX = 4096
MAX_EVENTS = 5          # output length is the main cost (~38 tok/s); minor events are mostly noise

ACTION_TYPES = ["protest", "arrest_detention", "statement", "court", "policy_decision",
                "police_action", "election", "violence", "announcement", "demand", "warning", "other"]

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "maxItems": MAX_EVENTS,
            "items": {
                "type": "object",
                "properties": {
                    "who": {"type": "array", "items": {"type": "string"}},
                    "what": {"type": "string"},
                    "when": {"type": ["string", "null"]},
                    "where": {"type": ["string", "null"]},
                    "action_type": {"type": "string", "enum": ACTION_TYPES},
                    "quote": {"type": "string"},
                },
                "required": ["who", "what", "when", "where", "action_type", "quote"],
            },
        }
    },
    "required": ["events"],
}

SYSTEM_PROMPT = """You extract news events from one article. Report only what the article states; do not add conclusions.
List at most """ + str(MAX_EVENTS) + """ events: the most important distinct events in the article, skipping background and minor details.
Rules:
- Only events that happened or were actually said. Something that "could", "may" or "is planned to" happen is not an event, unless it is someone's statement (then action_type is statement or warning).
- Each event once. Do not list the same event twice with different wording.
For each event give:
- who: names of people and organizations involved, exactly as written in the article. Never expand an acronym unless the article itself expands it. No descriptions ("his brother"), objects or systems.
- what: one short sentence describing what happened, attributed (e.g. "Police detained ...", "X said ...")
- when: date or time of the event as stated in the article, else null
- where: place as stated, else null
- action_type: one of """ + ", ".join(ACTION_TYPES) + """
- quote: one sentence copied word for word from the article that supports the event. Never combine or reword sentences.
Return JSON only."""

# Sample spread across days, deterministic (md5 order instead of random).
SAMPLE_SQL = """
    SELECT id, url, title, snippet, published_at FROM (
        SELECT *, row_number() OVER (PARTITION BY published_at::date ORDER BY md5(url)) AS rn
        FROM articles
        WHERE title ILIKE ANY (ARRAY['%%CJP%%', '%%Jantar Mantar%%'])
    ) t
    ORDER BY rn, published_at
    LIMIT %s
"""

log = logging.getLogger("llm_test")


def setup_logging() -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
    )


def fetch_text(client: httpx.Client, url: str) -> str | None:
    """Main article text, or None if the page can't be fetched or parsed."""
    try:
        resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("fetch failed %s: %s", url, e)
        return None
    text = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
    return text or None


def normalize(s: str) -> str:
    """Loose form for the verbatim-quote check: unify quotes/dashes, collapse whitespace."""
    s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}))
    return re.sub(r"\s+", " ", s).strip().lower()


def gpu_share(client: httpx.Client, model: str) -> float | None:
    """Fraction of the loaded model in VRAM (1.0 = fully on GPU), from /api/ps."""
    for m in client.get(f"{ollama.OLLAMA_URL}/api/ps").json().get("models", []):
        if m["name"] == model and m.get("size"):
            return m.get("size_vram", 0) / m["size"]
    return None


def quote_verified(quote: str | None, haystack: str) -> bool:
    """True if every piece of the quote is in the (normalized) article text.

    Pieces are split at ellipses and [editorial brackets], which publishers add inside quotes.
    """
    if not quote:
        return False
    pieces = [p.strip(" .,") for p in re.split(r"…|\.\.\.|\[[^\]]*\]", normalize(quote))]
    pieces = [p for p in pieces if p]
    return bool(pieces) and all(p in haystack for p in pieces)


def check(raw: str, text: str) -> dict:
    """JSON validity and verified-quote counts for one model output.

    Each event gets quote_verified. In the real extraction an unverified quote is dropped and the
    event is kept but marked unverified (not used as merge evidence); here the quote is kept for review.
    """
    try:
        events = json.loads(raw)["events"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return {"json_ok": False, "events": [], "quotes_found": 0, "quotes_total": 0}
    haystack = normalize(text)
    for e in events:
        e["quote_verified"] = quote_verified(e.get("quote"), haystack)
    found = sum(e["quote_verified"] for e in events)
    return {"json_ok": True, "events": events, "quotes_found": found, "quotes_total": len(events)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=30, help="number of articles (default 30)")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = parser.parse_args()
    setup_logging()

    with connect() as conn:
        articles = conn.execute(SAMPLE_SQL, (args.limit,)).fetchall()
    log.info("sampled %d articles", len(articles))

    # Full text lives only in this dict, for this run.
    texts = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True) as web:
        for art_id, url, title, snippet, _ in articles:
            full = fetch_text(web, url)
            texts[art_id] = (full or f"{title}\n\n{snippet or ''}")[:MAX_TEXT_CHARS], full is not None
    log.info("full text for %d/%d articles (rest use title + snippet)",
             sum(ok for _, ok in texts.values()), len(texts))

    out_file = ROOT / "logs" / f"llm_test_{date.today()}.jsonl"
    stats = {m: {"n": 0, "json_ok": 0, "quotes_found": 0, "quotes_total": 0, "seconds": [], "gpu": None, "errors": 0}
             for m in args.models}

    with httpx.Client(timeout=600) as client, out_file.open("w") as out:
        for model in args.models:
            log.info("model %s", model)
            secs_first = None
            for i, (art_id, url, title, _, published_at) in enumerate(articles):
                text, full_text = texts[art_id]
                s = stats[model]
                s["n"] += 1
                try:
                    raw, secs = ollama.chat(client, model, SYSTEM_PROMPT, text, EVENT_SCHEMA, NUM_CTX)
                except httpx.HTTPError as e:
                    log.error("%s article %d: %s", model, art_id, e)
                    s["errors"] += 1
                    continue
                if secs_first is None:
                    secs_first = secs  # includes model load time; excluded from the average
                else:
                    s["seconds"].append(secs)
                if s["gpu"] is None:
                    s["gpu"] = gpu_share(client, model)
                result = check(raw, text)
                s["json_ok"] += result["json_ok"]
                s["quotes_found"] += result["quotes_found"]
                s["quotes_total"] += result["quotes_total"]
                log.info("  [%d/%d] %.1fs json=%s quotes=%d/%d  %s", i + 1, len(articles), secs,
                         result["json_ok"], result["quotes_found"], result["quotes_total"], title[:60])
                out.write(json.dumps({
                    "model": model, "article_id": art_id, "source_url": url, "title": title,
                    "published_at": str(published_at), "full_text": full_text, "seconds": round(secs, 1),
                    **result, "raw": None if result["json_ok"] else raw,
                }, ensure_ascii=False) + "\n")
            if secs_first is not None:
                log.info("  first call (with model load): %.1fs", secs_first)

    print(f"\nResults: {out_file}\n")
    print(f"{'model':34} {'json ok':>8} {'quotes verified':>16} {'s/article':>10} {'on GPU':>7} {'errors':>7}")
    for model, s in stats.items():
        avg = sum(s["seconds"]) / len(s["seconds"]) if s["seconds"] else 0
        quotes = f"{s['quotes_found']}/{s['quotes_total']}"
        gpu = f"{s['gpu']:.0%}" if s["gpu"] is not None else "?"
        print(f"{model:34} {s['json_ok']:>4}/{s['n']:<3} {quotes:>16} {avg:>10.1f} {gpu:>7} {s['errors']:>7}")


if __name__ == "__main__":
    main()
