"""One run: download → clean → validate → analytics → research checks → (AI summary) → Excel.

Each source and each series is isolated: a failure is logged and the run carries
on with the rest. Run status (about the data pipeline, not the market):
OK (no findings) · WARNING (data-quality findings) · ALERT (a source or series
could not be collected, or nothing was collected).
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import ai_summary
from .analytics import clean, curve_snapshot, summarise
from .checks import run_checks
from .config import PROJECT_ROOT, Config
from .excel_report import build_workbook
from .http_client import FetchError, HttpClient
from .sources import (ECB_CURRENCIES, ECB_URL, FRED_URL, TREASURY_URL, ecb_crosses, parse_ecb_csv, parse_fred_csv,
                      parse_treasury_csv)
from .validate import ERROR, INFO, WARNING, quality, validate_curve, validate_series

log = logging.getLogger("market_research")


class RunLog(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.rows: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.rows.append({"time": datetime.fromtimestamp(record.created, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                          "level": record.levelname, "message": record.getMessage()})


def collect(config: Config, client: HttpClient, *, as_of: date, run_id: str, demo: bool = False,
            ai_client=None) -> dict:
    started = datetime.now(timezone.utc)
    run_log = RunLog()
    log.addHandler(run_log)
    start = (as_of - timedelta(days=config.history_days)).isoformat()
    failures: list[dict] = []
    raw_obs: dict[str, list] = {}
    curve: dict = {}
    try:
        log.info("Run %s started: data as of %s, %d series", run_id, as_of, len(config.series))

        for sd in (s for s in config.series if s.source == "fred"):
            try:
                raw_obs[sd.id] = parse_fred_csv(client.get_text(FRED_URL.format(id=sd.id, start=start)), sd.id)
            except (FetchError, ValueError) as exc:
                log.error("FRED %s not collected: %s", sd.id, exc)
                failures.append({"source": f"FRED {sd.id}", "error": str(exc)})

        if any(s.source == "ecb" for s in config.series):
            try:
                text = client.get_text(ECB_URL.format(ccys="+".join(ECB_CURRENCIES), start=start))
                raw_obs.update(ecb_crosses(parse_ecb_csv(text)))
            except (FetchError, ValueError) as exc:
                log.error("ECB FX rates not collected: %s", exc)
                failures.append({"source": "ECB FX", "error": str(exc)})

        for year in (as_of.year - 1, as_of.year):
            try:
                curve.update(parse_treasury_csv(client.get_text(TREASURY_URL.format(year=year))))
            except (FetchError, ValueError) as exc:
                log.error("Treasury curve %d not collected: %s", year, exc)
                failures.append({"source": f"Treasury {year}", "error": str(exc)})
        curve = {d: v for d, v in curve.items() if d <= as_of}

        cleaned, issues, summaries = {}, [], []
        for sd in config.series:
            obs = [(d, v) for d, v in raw_obs.get(sd.id, []) if d <= as_of]
            result = clean(obs, sd)
            cleaned[sd.id] = result.series
            # A series whose download failed is already in `failures`; it gets quality ERROR below.
            found = validate_series(sd, result, as_of, config) if sd.id in raw_obs else []
            issues.extend(found)
            row = summarise(sd, result.series)
            row["quality"] = quality(sd.id, found) if sd.id in raw_obs else "ERROR"
            summaries.append(row)
            if sd.id in raw_obs:
                log.info("%s: %d observations, latest %s, quality %s", sd.id, len(result.series),
                         row["date"], row["quality"])

        snapshot = curve_snapshot(curve, config.tenors)
        issues.extend(validate_curve(curve, config.tenors, cleaned.get("T10Y2Y"), as_of, config))
        qualities = {s["id"]: s["quality"] for s in summaries}
        signals = run_checks(config.checks, {s["id"]: s for s in summaries}, snapshot, qualities)

        summary_ai = None
        if config.ai_enabled and (config.anthropic_key_set or ai_client is not None):
            facts = ai_summary.facts_text(summaries, signals, snapshot)
            try:
                summary_ai = ai_summary.summarise(facts, config.ai_model, config.ai_effort, client=ai_client)
                log.info("AI summary added (all figures verified against the facts)")
            except Exception as exc:  # optional feature: never fails the run
                log.warning("AI summary skipped: %s", exc)

        collected = sum(1 for s in config.series if cleaned.get(s.id))
        errors = sum(i.severity == ERROR for i in issues)
        warnings = sum(i.severity == WARNING for i in issues)
        status = "ALERT" if failures or collected == 0 else "WARNING" if errors or warnings else "OK"
        counts = {k: sum(1 for g in signals if g["status"] == k) for k in ("ALERT", "WATCH", "OK", "N/A")}
        log.log(logging.WARNING if status != "OK" else logging.INFO,
                "Run %s finished: %s | %d/%d series | %d error(s) | %d warning(s) | signals %d ALERT, %d WATCH | "
                "%d request(s), %d retry(ies)", run_id, status, collected, len(config.series), errors, warnings,
                counts["ALERT"], counts["WATCH"], client.stats["requests"], client.stats["retries"])
        run = {
            "run_id": run_id, "status": status, "as_of": as_of.isoformat(),
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "series_requested": len(config.series), "series_collected": collected,
            "curve_dates": len(curve), "errors": errors, "warnings": warnings, "failures": failures,
            "signals": counts, "top_signals": [g for g in signals if g["status"] in ("ALERT", "WATCH")],
            "http": dict(client.stats), "ai_summary": summary_ai is not None,
        }
    finally:
        log.removeHandler(run_log)

    order = {ERROR: 0, WARNING: 1, INFO: 2}
    return {
        "title": "Market & macro research pack" + (" (DEMO DATA)" if demo else ""), "demo": demo, "run": run,
        "summaries": summaries, "signals": signals, "curve": snapshot,
        "issues": sorted((i.as_row() for i in issues), key=lambda r: (order[r["severity"]], r["series"], r["date"])),
        "clean": cleaned, "series_defs": list(config.series), "chart_days": config.chart_days,
        "run_log": run_log.rows, "ai_summary": summary_ai,
    }


def display_path(path: Path) -> str:
    """Project-relative path for logs and summaries (no user or machine folder names)."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


def write_outputs(ds: dict, config: Config) -> dict:
    run = ds["run"]
    suffix = "_DEMO" if ds.get("demo") else ""
    report = config.reports_dir / f"market_research_{run['run_id']}{suffix}.xlsx"
    paths = {"report": build_workbook(ds, report)}
    if run["series_collected"]:
        latest = config.reports_dir / f"latest{suffix}.xlsx"
        shutil.copyfile(report, latest)
        paths["latest"] = latest
    runs = config.logs_dir / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    summary = runs / f"run_{run['run_id']}{suffix}.json"
    summary.write_text(json.dumps({**run, "report": display_path(report)}, indent=2), encoding="utf-8")
    paths["summary"] = summary
    return paths


def write_manifest(archive_dir: Path, run_id: str, as_of: date) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "manifest.json").write_text(json.dumps({"run_id": run_id, "as_of": as_of.isoformat()}), encoding="utf-8")


def read_manifest(archive_dir: Path) -> date:
    data = json.loads((archive_dir / "manifest.json").read_text(encoding="utf-8"))
    return date.fromisoformat(data["as_of"])


def prune(config: Config, today: date) -> list[Path]:
    removed: list[Path] = []
    cutoff = today - timedelta(days=config.keep_raw_days)
    if config.raw_dir.exists():
        for d in config.raw_dir.iterdir():
            try:
                day = datetime.strptime(d.name[:8], "%Y%m%d").date()
            except ValueError:
                continue
            if d.is_dir() and day < cutoff:
                shutil.rmtree(d)
                removed.append(d)
    if config.reports_dir.exists():
        reports = sorted(p for p in config.reports_dir.glob("market_research_*.xlsx") if "_DEMO" not in p.name)
        for p in reports[: max(0, len(reports) - config.keep_reports)]:
            p.unlink()
            removed.append(p)
    return removed
