"""Cleaning and analytics for daily time series.

Cleaning: sort by date, keep the LAST value for a duplicated date, drop missing
values (FRED '' / '.'), drop values outside the series' valid range (reported by
validation). Holidays are left as gaps; nothing is forward-filled.

Changes use "as of" lookups: the base value is the last observation on or before
the window start, so weekends and holidays never break a comparison.
"""
from __future__ import annotations

import math
import statistics
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import SeriesDef

Series = list[tuple[date, float]]
TRADING_DAYS = 252


@dataclass
class CleanResult:
    series: Series
    duplicates: int = 0
    missing: int = 0
    out_of_range: list[tuple[date, float]] = field(default_factory=list)


def clean(obs: list[tuple[date, float | None]], sd: SeriesDef | None = None) -> CleanResult:
    by_date: dict[date, float | None] = {}
    duplicates = 0
    for d, v in obs:
        if d in by_date:
            duplicates += 1
        by_date[d] = v  # last one wins (later rows are revisions)
    missing = sum(1 for v in by_date.values() if v is None)
    bad: list[tuple[date, float]] = []
    out: Series = []
    for d in sorted(by_date):
        v = by_date[d]
        if v is None:
            continue
        if sd and not sd.valid_min <= v <= sd.valid_max:
            bad.append((d, v))
            continue
        out.append((d, v))
    return CleanResult(out, duplicates, missing, bad)


def as_of(series: Series, d: date) -> tuple[date, float] | None:
    """Last observation on or before d."""
    i = bisect_right([x[0] for x in series], d)
    return series[i - 1] if i else None


def minus_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 - months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError(d)


def window_start(latest: date, window: str) -> date:
    if window == "1W":
        return latest - timedelta(days=7)
    if window == "1M":
        return minus_months(latest, 1)
    if window == "3M":
        return minus_months(latest, 3)
    if window == "1Y":
        return minus_months(latest, 12)
    if window == "YTD":
        return date(latest.year - 1, 12, 31)
    raise ValueError(f"unknown window {window}")


def change(series: Series, window: str, kind: str) -> float | None:
    """pct: % change; bps: change in basis points (values are in percent)."""
    if not series:
        return None
    last_d, last_v = series[-1]
    base = as_of(series, window_start(last_d, window))
    if base is None or base[0] == last_d:
        return None
    if kind == "bps":
        return (last_v - base[1]) * 100
    if base[1] == 0:
        return None
    return (last_v / base[1] - 1) * 100


def volatility(series: Series, kind: str, days: int = TRADING_DAYS) -> float | None:
    """Annualised volatility over the last `days` observations.
    pct series: stdev of daily log returns × √252, in %. bps series: stdev of daily changes × √252, in bp."""
    window = series[-(days + 1):]
    if kind == "pct":
        moves = [math.log(b[1] / a[1]) for a, b in zip(window, window[1:]) if a[1] > 0 and b[1] > 0]
        scale = 100
    else:
        moves = [(b[1] - a[1]) * 100 for a, b in zip(window, window[1:])]
        scale = 1
    if len(moves) < 20:
        return None
    return statistics.stdev(moves) * math.sqrt(TRADING_DAYS) * scale


def last_year(series: Series) -> Series:
    if not series:
        return []
    cutoff = minus_months(series[-1][0], 12)
    return [x for x in series if x[0] > cutoff]


def max_drawdown(series: Series) -> float | None:
    """Largest peak-to-trough fall in %, over the given observations (≤ 0)."""
    peak, worst = None, 0.0
    for _, v in series:
        if v <= 0:
            return None
        peak = v if peak is None else max(peak, v)
        worst = min(worst, (v / peak - 1) * 100)
    return worst if peak is not None else None


def summarise(sd: SeriesDef, series: Series) -> dict:
    """Key-table row for one series."""
    row = {"id": sd.id, "label": sd.label, "category": sd.category, "unit": sd.unit, "change_kind": sd.change,
           "latest": None, "date": None, "observations": len(series)}
    if not series:
        return row
    row["date"], row["latest"] = series[-1]
    for w in ("1W", "1M", "3M", "YTD", "1Y"):
        row[f"chg_{w}"] = change(series, w, sd.change)
    row["vol_1y"] = volatility(series, sd.change)
    yr = last_year(series)
    row["high_52w"] = max(v for _, v in yr)
    row["low_52w"] = min(v for _, v in yr)
    if sd.change == "pct" and row["high_52w"] > 0:
        row["from_high"] = (row["latest"] / row["high_52w"] - 1) * 100
        row["max_drawdown_1y"] = max_drawdown(yr)
    else:  # rates/spreads: distance from the high in bp
        row["from_high"] = (row["latest"] - row["high_52w"]) * 100
        row["max_drawdown_1y"] = None
    return row


# ---------------------------------------------------------------- yield curve

def curve_snapshot(curve: dict[date, dict[str, float]], tenors: tuple[str, ...]) -> dict | None:
    """Curve today, 1 month ago and 1 year ago (as-of), plus 2s10s in bp for each."""
    if not curve:
        return None
    dates = sorted(curve)
    latest = dates[-1]

    def pick(target: date) -> date | None:
        i = bisect_right(dates, target)
        return dates[i - 1] if i else None

    points = {"today": latest, "1M ago": pick(minus_months(latest, 1)), "1Y ago": pick(minus_months(latest, 12))}
    rows = []
    for tenor in tenors:
        rows.append({"tenor": tenor, **{k: (curve[d].get(tenor) if d else None) for k, d in points.items()}})
    spreads = {}
    for k, d in points.items():
        c = curve.get(d) if d else None
        spreads[k] = round((c["10 Yr"] - c["2 Yr"]) * 100, 1) if c and "10 Yr" in c and "2 Yr" in c else None
    return {"dates": points, "rows": rows, "spread_2s10s_bps": spreads}


def curve_history(curve: dict[date, dict[str, float]], tenor_a: str = "2 Yr", tenor_b: str = "10 Yr") -> Series:
    return [(d, round((c[tenor_b] - c[tenor_a]) * 100, 1)) for d, c in sorted(curve.items()) if tenor_a in c and tenor_b in c]


def business_days_between(a: date, b: date) -> int:
    """Weekdays after a up to and including b (0 if b <= a)."""
    if b <= a:
        return 0
    days = (b - a).days
    weeks, rest = divmod(days, 7)
    count = weeks * 5
    for i in range(1, rest + 1):
        if (a + timedelta(days=i)).weekday() < 5:
            count += 1
    return count
