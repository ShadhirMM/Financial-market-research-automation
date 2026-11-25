import json
import os
import time

import pytest
from openpyxl import load_workbook

from market_research import cli
from market_research.config import load_config
from market_research.http_client import HttpClient, ReplaySession
from market_research.ops import RunLock, post_status, status_text
from market_research.runner import collect, prune, read_manifest, write_manifest, write_outputs

from conftest import AS_OF, RAW

SHEETS = ["README", "Dashboard", "Signals", "Curve", "Equities", "Rates", "Volatility & Credit", "Commodities", "FX",
          "Data_Quality", "Run_Log"]


def rows(ws):
    data = list(ws.iter_rows(values_only=True))
    return [dict(zip(data[0], r)) for r in data[1:]]


@pytest.fixture
def cfg(tmp_config_file):
    return load_config(tmp_config_file, env={})


def replay_client(failures=None, archive=None, directory=RAW):
    return HttpClient("test", session=ReplaySession(directory, failures), sleep=lambda s: None, archive_dir=archive)


def test_demo_end_to_end(tmp_config_file, cfg):
    assert cli.main(["--config", str(tmp_config_file), "demo"]) == 0  # WARNING (data findings) -> exit 0
    wb = load_workbook(cfg.reports_dir / "latest_DEMO.xlsx")
    assert wb.sheetnames == SHEETS
    assert "DEMO DATA" in wb["README"]["A2"].value
    charts = {ws.title: len(ws._charts) for ws in wb.worksheets}
    assert all(charts[s] == 1 for s in ("Curve", "Equities", "Rates", "Volatility & Credit", "Commodities", "FX"))

    sig = {r["Check"]: r["Status"] for r in rows(wb["Signals"])}
    assert sig == {"Nasdaq drawdown": "ALERT", "S&P 500 drawdown": "WATCH", "Equity volatility": "WATCH",
                   "10-year yield weekly move": "WATCH", "High-yield spread widening": "WATCH",
                   "Brent oil monthly move": sig["Brent oil monthly move"], "Yield curve 2s10s": "OK",
                   "EUR/USD weekly move": "OK", "USD/JPY weekly move": "OK"}
    dq = {(r["Series"], r["Rule"]) for r in rows(wb["Data_Quality"])}
    assert dq == {("VIXCLS", "out_of_range"), ("DCOILBRENTEU", "stale"), ("DCOILWTICO", "gap"), ("DJIA", "jump"),
                  ("DCOILWTICO", "duplicates")}
    curve = list(wb["Curve"].iter_rows(values_only=True))
    assert curve[-1][0] == "2s10s (bp)" and curve[-1][1] > 0 and curve[-1][3] < 0  # inverted a year ago
    fx = wb["FX"]
    assert fx["H1"].value == "EURUSD (rebased = 100)" and fx["H2"].value == pytest.approx(100.0)

    summary = json.loads(next((cfg.logs_dir / "runs").glob("run_*_DEMO.json")).read_text())
    assert summary["status"] == "WARNING" and summary["series_collected"] == 16
    assert summary["http"]["retries"] == 1 and summary["signals"]["ALERT"] == 1
    assert summary["report"].endswith("_DEMO.xlsx") and ":" not in summary["report"]  # no absolute paths


def test_live_style_run_then_rebuild_gives_identical_numbers(tmp_config_file, cfg, tmp_path):
    archive = cfg.raw_dir / "20261125T060000Z"
    write_manifest(archive, "20261125T060000Z", AS_OF)
    first = collect(cfg, replay_client(archive=archive), as_of=AS_OF, run_id="20261125T060000Z")
    assert {p.name for p in archive.iterdir()} >= {"fred_SP500.csv", "ecb_EXR.csv", "treasury_2026.csv", "treasury_2025.csv",
                                                   "manifest.json"}
    assert read_manifest(archive) == AS_OF
    assert cli.main(["--config", str(tmp_config_file), "rebuild", "--raw", str(archive)]) == 0
    wb = load_workbook(sorted(cfg.reports_dir.glob("market_research_*.xlsx"))[-1])
    dash = list(wb["Dashboard"].iter_rows(values_only=True))
    latest = {r[0]: r[2] for r in dash if r and r[0] and isinstance(r[2], (int, float))}
    for s in first["summaries"]:
        assert latest[s["label"]] == pytest.approx(s["latest"])


@pytest.mark.parametrize("failures,source,lost", [
    ({"ecb_EXR.csv": [404]}, "ECB FX", {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCNY"}),
    ({"fred_VIXCLS.csv": [503, 503, 503, 503]}, "FRED VIXCLS", {"VIXCLS"}),
    ({"treasury_2026.csv": [403], "treasury_2025.csv": [403]}, "Treasury 2026", set()),
])
def test_one_source_failing_does_not_stop_the_others(cfg, failures, source, lost):
    ds = collect(cfg, replay_client(failures), as_of=AS_OF, run_id="r")
    assert ds["run"]["status"] == "ALERT"
    assert any(f["source"] == source for f in ds["run"]["failures"])
    got = {s["id"] for s in ds["summaries"] if s["latest"] is not None}
    assert got == {s.id for s in cfg.series} - lost
    if source.startswith("Treasury"):
        assert ds["curve"] is None
        assert next(g for g in ds["signals"] if g["check"] == "Yield curve 2s10s")["status"] == "N/A"
    if lost:
        sid = next(iter(lost))
        assert next(s for s in ds["summaries"] if s["id"] == sid)["quality"] == "ERROR"


def test_unexpected_format_is_caught(cfg, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for f in RAW.iterdir():
        (raw / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    (raw / "fred_SP500.csv").write_text("DATE,SOMETHING_ELSE\n2026-11-24,1\n", encoding="utf-8")
    ds = collect(cfg, replay_client(directory=raw), as_of=AS_OF, run_id="r")
    assert ds["run"]["failures"][0]["source"] == "FRED SP500" and "unexpected header" in ds["run"]["failures"][0]["error"]


def test_nothing_collected_never_replaces_latest(cfg):
    everything = {f.name: [404] for f in RAW.iterdir()}
    ds = collect(cfg, replay_client(everything), as_of=AS_OF, run_id="r")
    assert ds["run"]["series_collected"] == 0 and ds["run"]["status"] == "ALERT"
    paths = write_outputs(ds, cfg)
    assert paths["report"].exists() and "latest" not in paths


def test_ai_summary_off_by_default_added_when_enabled_rejected_when_invented(cfg):
    from dataclasses import replace
    from types import SimpleNamespace

    good = '{"headline": "Nasdaq Composite is the weak spot", "points": [{"text": "Signals: 1 ALERT."}]}'

    class Client:
        def __init__(self, text):
            self.calls = 0
            self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))
            self.text = text

        def create(self, **kw):
            self.calls += 1
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=self.text)])

    off = Client(good)
    assert collect(cfg, replay_client(), as_of=AS_OF, run_id="r", ai_client=off)["ai_summary"] is None  # disabled in config
    assert off.calls == 0
    on_cfg = replace(cfg, ai_enabled=True)
    ok = Client(good)
    ds = collect(on_cfg, replay_client(), as_of=AS_OF, run_id="r", ai_client=ok)
    assert ds["ai_summary"]["headline"].startswith("Nasdaq") and ds["run"]["ai_summary"] is True
    path = write_outputs(ds, on_cfg)["report"]
    assert any("Nasdaq Composite is the weak spot" == r[0] for r in load_workbook(path)["Dashboard"].iter_rows(values_only=True))
    invented = Client('{"headline": "Stocks will rise 15.7% next year", "points": []}')
    ds = collect(on_cfg, replay_client(), as_of=AS_OF, run_id="r", ai_client=invented)
    assert ds["ai_summary"] is None and ds["run"]["status"] == "WARNING"  # rejected, run unaffected
    assert any("AI summary skipped" in r["message"] for r in ds["run_log"])


def test_bad_config_and_missing_raw_folder_exit_2(tmp_path, tmp_config_file):
    bad = tmp_path / "bad.toml"
    bad.write_text("[run]\nhistory_days = 1\n", encoding="utf-8")
    assert cli.main(["--config", str(bad), "demo"]) == 2
    assert cli.main(["--config", str(tmp_config_file), "rebuild", "--raw", str(tmp_path / "nope")]) == 2
    assert cli.main(["--config", str(tmp_config_file), "check"]) == 0


def test_lock(tmp_config_file, cfg, tmp_path):
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    with RunLock(cfg.logs_dir / ".research.lock"):
        assert cli.main(["--config", str(tmp_config_file), "demo"]) == 2
    stale = tmp_path / ".lock"
    stale.write_text("{}")
    old = time.time() - 3 * 3600
    os.utime(stale, (old, old))
    with RunLock(stale):
        pass
    assert not stale.exists()


def test_webhook(monkeypatch):
    sent = {}

    class R:
        def raise_for_status(self):
            pass

    monkeypatch.setattr("market_research.ops.requests.post", lambda url, json, timeout: sent.update(json=json) or R())
    run = {"status": "ALERT", "run_id": "r1", "as_of": "2026-11-25", "series_collected": 11, "series_requested": 16,
           "errors": 1, "warnings": 2, "signals": {"ALERT": 1, "WATCH": 2},
           "top_signals": [{"status": "ALERT", "check": "Nasdaq drawdown", "explanation": "Nasdaq is -22.4%."}],
           "failures": [{"source": "ECB FX", "error": "HTTP 404"}]}
    assert post_status("https://hooks.example/x", run, "r.xlsx") is True
    text = sent["json"]["text"]
    assert text.startswith("[ALERT] Market research pack r1 (data as of 2026-11-25): 11/16 series")
    assert "[ALERT] Nasdaq drawdown" in text and "ECB FX (HTTP 404)" in text
    assert post_status(None, run, None) is False
    assert status_text({"status": "ALERT", "run_id": "x"}).startswith("[ALERT]")

    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr("market_research.ops.requests.post", boom)
    assert post_status("https://hooks.example/x", run, None) is False


def test_prune(cfg):
    for name in ("20260101T000000Z", "20261120T000000Z"):
        (cfg.raw_dir / name).mkdir(parents=True)
    cfg.reports_dir.mkdir(parents=True)
    for i in range(60):
        (cfg.reports_dir / f"market_research_2026{i:04d}.xlsx").write_text("x")
    removed = prune(cfg, AS_OF)
    assert not (cfg.raw_dir / "20260101T000000Z").exists() and (cfg.raw_dir / "20261120T000000Z").exists()
    assert len(list(cfg.reports_dir.glob("market_research_*.xlsx"))) == cfg.keep_reports
    assert len(removed) == 1 + 60 - cfg.keep_reports
