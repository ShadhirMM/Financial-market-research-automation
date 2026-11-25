"""Command line.

  python -m market_research run                         download live and build the report
  python -m market_research rebuild --raw data/raw/<run> re-create a report from archived downloads (no network)
  python -m market_research demo                        offline demo with synthetic data (tests/fixtures/raw)
  python -m market_research check                       validate the config only

Exit codes (for Task Scheduler / launchd): 0 = OK or WARNING, 1 = ALERT (a source
or series failed), 2 = fatal (bad config, lock held, crash).
Market signals (WATCH/ALERT) do not change the exit code: they are research
findings, not failures.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from .config import DEFAULT_CONFIG, PROJECT_ROOT, ConfigError, load_config, load_dotenv
from .http_client import HttpClient, ReplaySession
from .ops import RunLock, post_status, setup_logging
from .runner import collect, display_path, prune, read_manifest, write_manifest, write_outputs

DEMO_DIR = PROJECT_ROOT / "tests" / "fixtures" / "raw"


def main(argv: list[str] | None = None, *, ai_client=None) -> int:
    parser = argparse.ArgumentParser(prog="market_research", description="Official market data → clean Excel research pack")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="download live and build the report")
    p_rebuild = sub.add_parser("rebuild", help="re-create a report from archived downloads (offline)")
    p_rebuild.add_argument("--raw", type=Path, required=True, help="folder data/raw/<run_id>")
    sub.add_parser("demo", help="offline demo with synthetic data")
    sub.add_parser("check", help="validate the config")
    args = parser.parse_args(argv)

    load_dotenv()
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    setup_logging(config.logs_dir, args.verbose)
    log = logging.getLogger("market_research")

    if args.command == "check":
        log.info("Config OK: %d series, %d checks, %d curve tenors, AI summary %s", len(config.series), len(config.checks),
                 len(config.tenors), "on" if config.ai_enabled and config.anthropic_key_set else "off")
        return 0

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    demo = args.command == "demo"
    sleep = time.sleep
    if args.command == "run":
        session, archive, as_of = None, config.raw_dir / run_id, datetime.now(timezone.utc).date()
        write_manifest(archive, run_id, as_of)
    else:
        raw = DEMO_DIR if demo else args.raw
        if not raw.is_dir() or not (raw / "manifest.json").exists():
            log.error("Raw folder not found or has no manifest.json: %s", raw)
            return 2
        failures = {"fred_DCOILWTICO.csv": [503]} if demo else None  # demo shows one retried request
        session, archive, as_of = ReplaySession(raw, failures), None, read_manifest(raw)
        sleep = lambda s: None  # noqa: E731  (no real waiting offline)
        log.info("%s from %s (no network), data as of %s", "Demo" if demo else "Rebuilding", display_path(raw), as_of)

    client = HttpClient(config.user_agent, requests_per_second=config.requests_per_second, timeout=config.timeout_seconds,
                        max_retries=config.max_retries, backoff=config.backoff_seconds, session=session,
                        archive_dir=archive, sleep=sleep)
    try:
        with RunLock(config.logs_dir / ".research.lock"):
            ds = collect(config, client, as_of=as_of, run_id=run_id, demo=demo, ai_client=ai_client)
            paths = write_outputs(ds, config)
            if args.command == "run":
                for p in prune(config, as_of):
                    log.info("Pruned %s", display_path(p))
    except RuntimeError as exc:  # lock held
        log.error("%s", exc)
        return 2
    except Exception:  # last line of defence: never die silently
        log.exception("Run failed unexpectedly")
        post_status(config.status_webhook, {"status": "ALERT", "run_id": run_id, "as_of": str(as_of),
                                            "failures": [{"source": "run", "error": "crash: see logs/errors.log"}]}, None)
        return 2

    run = ds["run"]
    log.info("Report: %s", display_path(paths["report"]))
    if not demo:
        post_status(config.status_webhook, run, paths["report"].name)
    return 1 if run["status"] == "ALERT" else 0


if __name__ == "__main__":
    sys.exit(main())
