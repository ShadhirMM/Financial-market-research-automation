"""Operational helpers: logging set-up, run lock, status webhook."""
from __future__ import annotations

import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s %(message)s"


def setup_logging(logs_dir: Path, verbose: bool = False) -> Path:
    """Console + rotating file log (logs/research.log, 1 MB × 5) + errors-only log, times in UTC."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.DEBUG)
    fmt = logging.Formatter(LOG_FORMAT, "%Y-%m-%d %H:%M:%S")
    fmt.converter = time.gmtime

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)
    main = RotatingFileHandler(logs_dir / "research.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    main.setLevel(logging.DEBUG)
    main.setFormatter(fmt)
    errors = RotatingFileHandler(logs_dir / "errors.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    errors.setLevel(logging.ERROR)
    errors.setFormatter(fmt)
    for h in (console, main, errors):
        root.addHandler(h)
    for noisy in ("urllib3", "httpx", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logs_dir / "research.log"


class RunLock:
    """Stops two scheduled runs overlapping. A lock older than `stale_after` seconds is taken over."""

    def __init__(self, path: Path, stale_after: float = 2 * 3600):
        self.path = path
        self.stale_after = stale_after

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            age = time.time() - self.path.stat().st_mtime
            if age < self.stale_after:
                raise RuntimeError(f"Another run is in progress (lock {self.path.name}, {age:.0f}s old).")
            logging.getLogger(__name__).warning("Taking over a stale lock (%.0fs old)", age)
        self.path.write_text(json.dumps({"pid": os.getpid(), "started": time.time()}), encoding="utf-8")
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)
        return False


def status_text(run: dict) -> str:
    sig = run.get("signals", {})
    text = (f"[{run['status']}] Market research pack {run['run_id']} (data as of {run.get('as_of', '?')}): "
            f"{run.get('series_collected', 0)}/{run.get('series_requested', 0)} series, "
            f"{run.get('errors', 0)} data error(s), {run.get('warnings', 0)} warning(s) | "
            f"signals: {sig.get('ALERT', 0)} ALERT, {sig.get('WATCH', 0)} WATCH")
    for s in run.get("top_signals", [])[:5]:
        text += f"\n[{s['status']}] {s['check']}: {s['explanation'][:180]}"
    if run.get("failures"):
        text += "\nFailed: " + "; ".join(f"{f['source']} ({f['error'][:80]})" for f in run["failures"][:5])
    return text


def post_status(webhook: str | None, run: dict, report_name: str | None, timeout: float = 15) -> bool:
    """Send the run status to a webhook (Slack-compatible 'text' plus structured fields). Never raises."""
    if not webhook:
        return False
    payload = {"text": status_text(run), "status": run["status"], "run": run, "report": report_name}
    try:
        r = requests.post(webhook, json=payload, timeout=timeout)
        r.raise_for_status()
        return True
    except requests.RequestException as exc:
        logging.getLogger(__name__).error("Status webhook failed: %s", exc)
        return False
