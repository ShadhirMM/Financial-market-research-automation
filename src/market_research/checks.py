"""Research checks: configurable rules that turn the numbers into OK / WATCH / ALERT
signals with a plain-English explanation. Rules live in config/config.toml.
"""
from __future__ import annotations

from .config import CheckDef

ORDER = {"ALERT": 0, "WATCH": 1, "N/A": 2, "OK": 3}


def _fmt(value: float, unit: str) -> str:
    if unit == "bp":
        return f"{value:+.0f} bp"
    if unit == "%chg":
        return f"{value:+.1f}%"
    if unit == "%":
        return f"{value:.1f}%"
    return f"{value:,.2f}"


def _level(check: CheckDef, value: float) -> str:
    v = abs(value) if check.direction == "abs" else value
    if check.direction == "below":
        return "ALERT" if v <= check.alert else "WATCH" if v <= check.watch else "OK"
    return "ALERT" if v >= check.alert else "WATCH" if v >= check.watch else "OK"


def evaluate(check: CheckDef, summaries: dict[str, dict], curve: dict | None, qualities: dict[str, str]) -> dict:
    row = {"check": check.name, "series": check.series, "status": "N/A", "value": None, "unit": "", "rule": "",
           "explanation": "", "why": check.why}
    label = summaries.get(check.series, {}).get("label", check.series)

    if check.type == "curve":
        value = (curve or {}).get("spread_2s10s_bps", {}).get("today")
        unit, what = "bp", "The 10-year minus 2-year Treasury spread"
        label = "2s10s"
    else:
        s = summaries.get(check.series)
        if not s or s.get("latest") is None:
            row["explanation"] = f"Not evaluated: {label} has no usable data (see Data_Quality)."
            return row
        if qualities.get(check.series) == "ERROR":
            row["why"] = f"{check.why} (Data issue on this series: see Data_Quality.)"
        if check.type == "level":
            value, unit, what = s["latest"], "", f"{label}"
        elif check.type == "drawdown":
            value, unit, what = s.get("from_high"), "%chg", f"{label} versus its 52-week high"
        else:  # change
            value = s.get(f"chg_{check.window}")
            unit = "bp" if s["change_kind"] == "bps" else "%chg"
            what = f"{label} over {check.window}"
    if value is None:
        row["explanation"] = f"Not evaluated: not enough history for {label}."
        return row

    status = _level(check, value)
    suffix = " bp" if unit == "bp" else "%" if unit == "%chg" else ""
    sign = {"above": "≥", "below": "≤", "abs": "size ≥"}[check.direction]
    rule = f"WATCH {sign} {check.watch:g}{suffix}, ALERT {sign} {check.alert:g}{suffix}"
    shown = _fmt(value, unit)
    if status == "OK":
        text = f"{what} is {shown}: inside the normal range ({rule})."
    else:
        limit = check.alert if status == "ALERT" else check.watch
        text = f"{what} is {shown}, past the {status} level of {limit:g}{suffix}. {check.why}"
    row.update(status=status, value=value, unit=unit.replace("%chg", "%"), rule=rule, explanation=text)
    return row


def run_checks(checks, summaries, curve, qualities) -> list[dict]:
    rows = [evaluate(c, summaries, curve, qualities) for c in checks]
    return sorted(rows, key=lambda r: (ORDER[r["status"]], r["check"]))
