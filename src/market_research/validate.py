"""Data validation. Findings are reported in the Data_Quality sheet and set a
per-series quality flag; they never silently change the numbers (except that
out-of-range values are excluded from analytics, and reported).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .analytics import CleanResult, business_days_between, last_year
from .config import Config, SeriesDef

ERROR, WARNING, INFO = "ERROR", "WARNING", "INFO"
RANK = {ERROR: 3, WARNING: 2, INFO: 1}


@dataclass(frozen=True)
class Issue:
    severity: str
    series: str
    rule: str
    message: str
    date: str = ""

    def as_row(self) -> dict:
        return {"severity": self.severity, "series": self.series, "date": self.date, "rule": self.rule, "message": self.message}


def validate_series(sd: SeriesDef, result: CleanResult, as_of_date: date, config: Config) -> list[Issue]:
    issues: list[Issue] = []
    s = result.series
    if not s:
        return [Issue(ERROR, sd.id, "no_data", "No valid observations.")]

    if result.out_of_range:
        d, v = result.out_of_range[-1]
        issues.append(Issue(ERROR, sd.id, "out_of_range",
                            f"{len(result.out_of_range)} value(s) outside {sd.valid_min:g}…{sd.valid_max:g} excluded "
                            f"(latest: {v:g} on {d}).", d.isoformat()))
    if result.duplicates:
        issues.append(Issue(INFO, sd.id, "duplicates", f"{result.duplicates} duplicate date(s); the last value was kept."))

    lag = business_days_between(s[-1][0], as_of_date)
    limit = sd.stale_business_days if sd.stale_business_days is not None else config.stale_business_days
    if lag > limit:
        issues.append(Issue(WARNING, sd.id, "stale", f"Last observation {s[-1][0]} is {lag} business days old (limit {limit}).",
                            s[-1][0].isoformat()))

    yr = last_year(s)
    for (d1, _), (d2, _) in zip(yr, yr[1:]):
        gap = business_days_between(d1, d2)
        if gap > config.max_gap_business_days:
            issues.append(Issue(WARNING, sd.id, "gap", f"No data between {d1} and {d2} ({gap} business days).", d2.isoformat()))

    for (d1, v1), (d2, v2) in zip(yr, yr[1:]):
        if sd.change == "pct":
            move = abs(v2 / v1 - 1) * 100 if v1 else 0
            unit = "%"
        else:
            move = abs(v2 - v1) * 100
            unit = " bp"
        if move > sd.max_jump:
            issues.append(Issue(WARNING, sd.id, "jump", f"Moved {move:.1f}{unit} from {d1} to {d2} "
                                                         f"(limit {sd.max_jump:g}{unit}); check the source.", d2.isoformat()))
    return issues


def validate_curve(curve: dict, tenors: tuple[str, ...], fred_2s10s: list | None, as_of_date: date, config: Config) -> list[Issue]:
    if not curve:
        return [Issue(ERROR, "CURVE", "no_data", "No Treasury yield curve data.")]
    issues: list[Issue] = []
    latest = max(curve)
    today = curve[latest]
    missing = [t for t in tenors if t not in today]
    if missing:
        issues.append(Issue(WARNING, "CURVE", "tenor_missing", f"Missing tenors on {latest}: {', '.join(missing)}.", latest.isoformat()))
    bad = {t: v for t, v in today.items() if not -1 <= v <= 25}
    if bad:
        issues.append(Issue(ERROR, "CURVE", "out_of_range", f"Implausible yields on {latest}: {bad}.", latest.isoformat()))
    lag = business_days_between(latest, as_of_date)
    if lag > config.stale_business_days:
        issues.append(Issue(WARNING, "CURVE", "stale", f"Latest curve {latest} is {lag} business days old.", latest.isoformat()))
    if fred_2s10s and "2 Yr" in today and "10 Yr" in today:
        fred = dict(fred_2s10s)
        if latest in fred:
            ours = (today["10 Yr"] - today["2 Yr"]) * 100
            theirs = fred[latest] * 100
            if abs(ours - theirs) > config.curve_consistency_bps:
                issues.append(Issue(WARNING, "CURVE", "inconsistent_2s10s",
                                    f"Treasury 2s10s {ours:.0f} bp vs FRED T10Y2Y {theirs:.0f} bp on {latest}.", latest.isoformat()))
    return issues


def quality(series_id: str, issues: list[Issue]) -> str:
    worst = max((RANK[i.severity] for i in issues if i.series == series_id and i.severity != INFO), default=0)
    return {3: ERROR, 2: WARNING}.get(worst, "OK")
