"""Refresh the data: the whole pipeline in order, for the twice-daily cron job (D-032) or by hand.

Run with:  python -m app.refresh

Steps, each in its own process so GPU memory is freed between them, stopping at the first that fails:
fetch (RSS for 2 days and the GDELT files not read yet) -> embed -> group -> categories (classifier) -> links
(changed stories only) -> categories of the front-page stories (LLM) -> link names -> dot labels -> front-page
titles and summaries. app.check then writes the health report, also after a failure.
Each step's output goes to logs/refresh/<start time>/<step>.out. A lock file stops a second run from starting
while one is still going (a long catch-up can reach the next cron time).
"""

import fcntl
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

from app import ollama

ROOT = Path(__file__).resolve().parent.parent
STEPS = [
    ("fetch", ["app.fetch", "--days", "2", "--gdelt"]),
    ("embed", ["app.embed"]),
    ("group", ["app.group"]),
    ("categories", ["app.categories"]),
    ("links", ["app.links"]),
    ("front-categories", ["app.categories", "--stories"]),
    ("link-names", ["app.links", "--types", "100"]),
    ("labels", ["app.moments", "--label", "300"]),
    ("titles", ["app.front", "--titles", "60"]),
]

log = logging.getLogger("refresh")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    (ROOT / "logs").mkdir(exist_ok=True)
    lock = open(ROOT / "logs" / "refresh.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info("A refresh is already running; not starting another.")
        return

    started = datetime.now().astimezone()
    out_dir = ROOT / "logs" / "refresh" / f"{started:%Y-%m-%d_%H%M}"
    out_dir.mkdir(parents=True, exist_ok=True)
    # The GPU steps come first; the local LLM may still be loaded from another job.
    with httpx.Client(timeout=60) as client:
        ollama.unload(client, ollama.MODEL)

    failed = None
    for name, module in STEPS:
        log.info("%s ...", name)
        with open(out_dir / f"{name}.out", "w") as out:
            code = subprocess.run([sys.executable, "-m", *module], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT).returncode
        if code:
            failed = name
            log.error("%s failed (exit %d); see %s", name, code, out_dir / f"{name}.out")
            break

    check = [sys.executable, "-m", "app.check", "--since", started.isoformat()] + (["--failed", failed] if failed else [])
    report = subprocess.run(check, cwd=ROOT, capture_output=True, text=True)
    (out_dir / "check.out").write_text(report.stdout + report.stderr)
    print(report.stdout + report.stderr, end="")
    log.info("Done in %.0f min%s", (datetime.now().astimezone() - started).total_seconds() / 60,
             f", stopped at {failed}" if failed else "")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
