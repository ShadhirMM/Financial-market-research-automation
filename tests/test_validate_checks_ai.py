from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from market_research import ai_summary
from market_research.analytics import CleanResult
from market_research.checks import evaluate, run_checks
from market_research.config import CheckDef
from market_research.validate import ERROR, INFO, WARNING, quality, validate_curve, validate_series

from conftest import AS_OF, sd

D = date


def weekdays(n, end=D(2026, 11, 24)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def rules(issues):
    return sorted((i.severity, i.rule) for i in issues)


# ---------- validation ----------

def test_clean_series_has_no_findings(config):
    s = [(d, 100.0 + i * 0.1) for i, d in enumerate(weekdays(300))]
    assert validate_series(sd(jump=5), CleanResult(s), AS_OF, config) == []


def test_each_series_rule(config):
    days = weekdays(300)
    s = [(d, 100.0) for d in days]
    s[150] = (days[150], 120.0)  # +20% then -16.7%
    del s[200:212]               # 12-business-day hole
    s = s[:-10]                  # last 10 days missing -> stale
    r = CleanResult(s, duplicates=2, out_of_range=[(days[5], -3.0)])
    found = validate_series(sd(jump=10), r, AS_OF, config)
    assert rules(found) == [(ERROR, "out_of_range"), (INFO, "duplicates"), (WARNING, "gap"), (WARNING, "jump"),
                            (WARNING, "jump"), (WARNING, "stale")]
    assert quality("X", found) == ERROR
    assert validate_series(sd(), CleanResult([]), AS_OF, config)[0].rule == "no_data"


def test_bps_jumps_and_per_series_staleness(config):
    days = weekdays(30)
    s = [(d, 4.0) for d in days]
    s[-1] = (days[-1], 4.6)  # +60 bp
    assert rules(validate_series(sd(change="bps", jump=50), CleanResult(s), AS_OF, config)) == [(WARNING, "jump")]
    old = [(d, 4.0) for d in days[:-8]]  # 9 business days old on AS_OF
    assert rules(validate_series(sd(change="bps"), CleanResult(old), AS_OF, config)) == [(WARNING, "stale")]
    assert validate_series(sd(change="bps", stale=10), CleanResult(old), AS_OF, config) == []


def test_curve_rules(config):
    good = {D(2026, 11, 24): {t: 4.5 for t in config.tenors}}
    assert validate_curve(good, config.tenors, [(D(2026, 11, 24), 0.0)], AS_OF, config) == []
    bad = {D(2026, 11, 24): {"2 Yr": 4.5, "10 Yr": 31.0}}
    found = validate_curve(bad, config.tenors, None, AS_OF, config)
    assert rules(found) == [(ERROR, "out_of_range"), (WARNING, "tenor_missing")]
    inc = {D(2026, 11, 24): {**{t: 4.5 for t in config.tenors}, "10 Yr": 4.9}}  # ours +40 bp
    assert rules(validate_curve(inc, config.tenors, [(D(2026, 11, 24), 0.10)], AS_OF, config)) == [(WARNING, "inconsistent_2s10s")]
    assert validate_curve({}, config.tenors, None, AS_OF, config)[0].rule == "no_data"


# ---------- research checks ----------

def chk(type_="level", direction="above", watch=25, alert=35, window=None, series="X"):
    return CheckDef(name="c", series=series, type=type_, direction=direction, watch=watch, alert=alert, why="Because.", window=window)


SUMM = {"X": {"label": "Thing", "latest": 30.0, "change_kind": "pct", "chg_1W": -3.0, "from_high": -12.0},
        "R": {"label": "Rate", "latest": 4.0, "change_kind": "bps", "chg_1W": 22.0}}


@pytest.mark.parametrize("check,status", [
    (chk(), "WATCH"),
    (chk(watch=20, alert=30), "ALERT"),            # boundary: exactly at alert
    (chk(watch=31, alert=40), "OK"),
    (chk("drawdown", "below", -10, -20), "WATCH"),
    (chk("drawdown", "below", -15, -20), "OK"),
    (chk("change", "abs", 2, 4, "1W"), "WATCH"),    # |-3%|
    (chk("change", "above", 2, 4, "1W"), "OK"),     # -3% is not above
    (chk("change", "abs", 20, 35, "1W", series="R"), "WATCH"),
])
def test_check_levels(check, status):
    assert evaluate(check, SUMM, None, {})["status"] == status


def test_check_explanations_and_units():
    g = evaluate(chk("change", "abs", 20, 35, "1W", series="R"), SUMM, None, {})
    assert g["unit"] == "bp" and "Rate over 1W is +22 bp, past the WATCH level of 20 bp. Because." == g["explanation"]
    ok = evaluate(chk(watch=31, alert=40), SUMM, None, {})
    assert ok["explanation"].startswith("Thing is 30.00: inside the normal range")


def test_curve_check_and_not_evaluated_cases():
    curve = {"spread_2s10s_bps": {"today": -60.0}}
    g = evaluate(chk("curve", "below", 0, -50, series="curve"), SUMM, curve, {})
    assert g["status"] == "ALERT" and "-60 bp" in g["explanation"]
    assert evaluate(chk(series="MISSING"), SUMM, None, {})["status"] == "N/A"
    assert evaluate(chk("change", "abs", 1, 2, "1Y"), SUMM, None, {})["status"] == "N/A"  # no 1Y history
    flagged = evaluate(chk(), SUMM, None, {"X": "ERROR"})
    assert flagged["status"] == "WATCH" and "Data issue" in flagged["why"]


def test_signals_sorted_alert_first():
    rows = run_checks([chk(watch=40, alert=50), chk(watch=20, alert=30), chk(watch=25, alert=35)], SUMM, None, {})
    assert [r["status"] for r in rows] == ["ALERT", "WATCH", "OK"]


# ---------- AI summary: never invents numbers ----------

SUMMARIES = [{"id": "SP500", "label": "S&P 500", "latest": 7201.09, "date": D(2026, 11, 24), "change_kind": "pct",
              "chg_1W": -1.234, "chg_1M": 2.0, "chg_YTD": 12.5, "chg_1Y": None}]
SIGNALS = [{"status": "WATCH", "check": "Equity volatility", "explanation": "VIX is 26.36, past the WATCH level of 25."}]


def test_facts_text_lists_rounded_figures():
    facts = ai_summary.facts_text(SUMMARIES, SIGNALS, {"spread_2s10s_bps": {"today": 28.0, "1Y ago": -40.0}})
    assert "S&P 500 (SP500): latest 7,201.09 on 2026-11-24; 1W -1.2%; 1M +2.0%; YTD +12.5%" in facts
    assert "2s10s spread: +28 bp today, -40 bp one year ago" in facts
    assert "[WATCH] Equity volatility" in facts


def test_number_check_accepts_only_numbers_from_the_facts():
    facts = ai_summary.facts_text(SUMMARIES, SIGNALS, None)
    ok = {"headline": "S&P 500 slipped 1.2% on the week", "points": [{"text": "VIX at 26.36 is above 25."}]}
    assert ai_summary.verify_numbers(ok, facts) == []
    bad = {"headline": "S&P 500 fell 1.5%", "points": [{"text": "Target 8,000 by year end."}]}
    assert ai_summary.verify_numbers(bad, facts) == [1.5, 8000.0]


class FakeClient:
    def __init__(self, text, stop="end_turn"):
        self.sent = None
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self.text, self.stop = text, stop

    def _create(self, **kw):
        self.sent = kw
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="thinking", thinking=""),
                                                               SimpleNamespace(type="text", text=self.text)])


def test_summarise_request_shape_and_success():
    facts = ai_summary.facts_text(SUMMARIES, SIGNALS, None)
    fc = FakeClient('{"headline": "S&P 500 up 2.0% on the month", "points": [{"text": "VIX 26.36 is above 25."}]}')
    out = ai_summary.summarise(facts, "claude-opus-5-5", "low", client=fc)
    assert out["headline"].startswith("S&P 500")
    kw = fc.sent
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default" and kw["betas"] == [ai_summary.FALLBACK_BETA]
    assert kw["output_config"]["format"]["type"] == "json_schema" and kw["output_config"]["effort"] == "low"
    assert kw["messages"] == [{"role": "user", "content": facts}]
    assert "temperature" not in kw


@pytest.mark.parametrize("text,stop,msg", [
    ('{"headline": "Up 9.9%", "points": []}', "end_turn", "not in the facts"),
    ("not json", "end_turn", "not valid JSON"),
    ("", "refusal", "stop_reason=refusal"),
    ('{"headline": "x"', "max_tokens", "stop_reason=max_tokens"),
])
def test_summarise_rejections(text, stop, msg):
    with pytest.raises(RuntimeError, match=msg):
        ai_summary.summarise("facts 1.0", "claude-opus-5-5", "low", client=FakeClient(text, stop))
