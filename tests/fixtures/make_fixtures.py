"""Generate the offline demo/test data in tests/fixtures/raw/.

SYNTHETIC DATA in the exact file formats of the real sources (FRED graph CSV,
Treasury daily par yield curve CSV, ECB SDMX csvdata). The numbers are made
up and deterministic (seeded). Each series is shaped to exercise specific rules:

  SP500       ~12% below its 52-week high      -> drawdown WATCH
  NASDAQCOM   ~22% below its 52-week high      -> drawdown ALERT
  DJIA        one +15% spike day               -> jump WARNING (max_jump 12%)
  VIXCLS      rises to ~28; one negative value -> level WATCH; out_of_range ERROR (value excluded)
  DGS10       +27 bp in the last week          -> weekly-move WATCH
  T10Y2Y      = DGS10 - DGS2, matches the Treasury curve (consistency check passes)
  BAMLH0A0HYM2 +60 bp in the last month        -> spread-widening WATCH
  DCOILBRENTEU last value 13 business days old -> stale WARNING (limit 10; Brent lags in reality too)
  DCOILWTICO  10-business-day hole; empty and '.' missing markers; a duplicate date -> gap WARNING, duplicates INFO
  Curve       2s10s positive today, inverted a year ago; 2025 file has no "1.5 Month" column
  ECB         USD, GBP, JPY, CHF, CNY per EUR; some TARGET holidays missing

Run: python tests/fixtures/make_fixtures.py
"""
from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).parent / "raw"
AS_OF = date(2026, 11, 25)
LAST = date(2026, 11, 24)
START = AS_OF - timedelta(days=800)


def business_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = business_days(START, LAST)
N = len(DAYS)
HOLIDAYS = {date(2025, 1, 1), date(2025, 7, 4), date(2025, 12, 25), date(2026, 1, 1), date(2026, 7, 3), date(2026, 11, 26)}


def walk(seed: int, start: float, vol: float, drift: float = 0.0, log: bool = True) -> list[float]:
    rnd = random.Random(seed)
    v, out = start, []
    for _ in range(N):
        out.append(v)
        step = rnd.gauss(drift, vol)
        v = v * math.exp(step) if log else v + step
    return out


def shape_tail(values: list[float], days: int, total_pct: float) -> list[float]:
    """Make the last `days` observations fall/rise smoothly by total_pct from the running peak."""
    peak_i = N - days - 1
    peak = max(values[: peak_i + 1])
    values[peak_i] = peak * 1.001
    for k in range(1, days + 1):
        values[peak_i + k] = values[peak_i] * (1 + total_pct / 100 * k / days) * (1 + 0.002 * math.sin(k))
    return values


def fred_csv(series_id: str, rows: list[tuple[date, str]]) -> str:
    lines = [f"observation_date,{series_id}"] + [f"{d.isoformat()},{v}" for d, v in rows]
    return "\n".join(lines) + "\n"


def fmt(v: float, nd: int) -> str:
    return f"{v:.{nd}f}"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    def simple(series_id, values, nd, drop_holidays=True, extra=None):
        rows = [(d, "" if (drop_holidays and d in HOLIDAYS) else fmt(v, nd)) for d, v in zip(DAYS, values)]
        if extra:
            rows = extra(rows)
        files[f"fred_{series_id}.csv"] = fred_csv(series_id, rows)

    sp = shape_tail(walk(1, 5600, 0.008, 0.0006), 35, -12.5)
    simple("SP500", sp, 2)
    nq = shape_tail(walk(2, 17500, 0.011, 0.0008), 45, -22.5)
    simple("NASDAQCOM", nq, 3)
    dj = walk(3, 42000, 0.007, 0.0004)
    dj[N - 120] = dj[N - 121] * 1.15  # spike day
    simple("DJIA", dj, 2)

    vix = [max(11.0, 16 + 3 * math.sin(i / 30) + random.Random(4 + i).gauss(0, 1.2)) for i in range(N)]
    for k in range(20):
        vix[N - 20 + k] = 18 + k * 0.5
    vix[N - 200] = -3.0  # impossible value: must be excluded and reported
    simple("VIXCLS", vix, 2)

    dff = [5.33 if i < N * 0.3 else 4.83 if i < N * 0.55 else 4.33 if i < N * 0.8 else 3.88 for i in range(N)]
    files["fred_DFF.csv"] = fred_csv("DFF", [(d, fmt(v, 2)) for d, v in zip(DAYS, dff)])

    two = walk(5, 4.30, 0.035, log=False)
    ten = [t - 0.6 + (1.0 * i / N) + random.Random(60 + i).gauss(0, 0.02) for i, t in enumerate(two)]
    for k in range(1, 6):  # last week: 10Y up ~27 bp
        ten[N - 6 + k] = ten[N - 6] + 0.055 * k
    two_r = [round(v, 2) for v in two]
    ten_r = [round(v, 2) for v in ten]
    simple("DGS2", two_r, 2)
    simple("DGS10", ten_r, 2)
    simple("T10Y2Y", [round(a - b, 2) for a, b in zip(ten_r, two_r)], 2)

    hy = walk(7, 3.40, 0.02, log=False)
    for k in range(1, 22):
        hy[N - 22 + k] = hy[N - 22] + 0.6 * k / 21
    simple("BAMLH0A0HYM2", hy, 2)

    brent = walk(8, 82, 0.017)
    brent_rows = [(d, fmt(v, 2)) for d, v in zip(DAYS, brent)][:-12]  # stale: last 12 business days missing (limit 10)
    files["fred_DCOILBRENTEU.csv"] = fred_csv("DCOILBRENTEU", brent_rows)

    wti = walk(9, 78, 0.019)

    def wti_extra(rows):
        hole = set(DAYS[N - 160: N - 150])  # 10 business days missing
        rows = [r for r in rows if r[0] not in hole]
        rows = [(d, "." if d == DAYS[N - 60] else v) for d, v in rows]  # old FRED missing marker
        dup_i = next(i for i, r in enumerate(rows) if r[0] == DAYS[N - 40])
        rows.insert(dup_i + 1, (rows[dup_i][0], fmt(float(rows[dup_i][1]) + 0.5, 2)))  # duplicate date, revised value
        return rows
    simple("DCOILWTICO", wti, 2, extra=wti_extra)

    # Treasury: one file per year, newest first, MM/DD/YYYY, columns differ by year.
    tenor_offsets = {"1 Mo": 0.25, "1.5 Month": 0.24, "2 Mo": 0.22, "3 Mo": 0.2, "4 Mo": 0.17, "6 Mo": 0.12, "1 Yr": 0.05,
                     "2 Yr": None, "3 Yr": None, "5 Yr": None, "7 Yr": None, "10 Yr": None, "20 Yr": None, "30 Yr": None}
    by_year: dict[int, list[str]] = {}
    for d, a, b in zip(DAYS, two_r, ten_r):
        if d in HOLIDAYS or d.year < AS_OF.year - 1:
            continue
        vals = {}
        for t, off in tenor_offsets.items():
            if t == "2 Yr":
                vals[t] = a
            elif t == "10 Yr":
                vals[t] = b
            elif off is not None:
                vals[t] = a + off
            else:
                w = {"3 Yr": 0.125, "5 Yr": 0.375, "7 Yr": 0.625, "20 Yr": 1.4, "30 Yr": 1.35}[t]
                vals[t] = a + (b - a) * w
        cols = [t for t in tenor_offsets if not (d.year < 2026 and t == "1.5 Month")]
        by_year.setdefault(d.year, []).append((d, cols, vals))
    for year, rows in by_year.items():
        cols = rows[0][1]
        lines = ["Date," + ",".join(f'"{c}"' for c in cols)]
        for d, _, vals in sorted(rows, reverse=True):
            lines.append(d.strftime("%m/%d/%Y") + "," + ",".join(f"{vals[c]:.2f}" for c in cols))
        files[f"treasury_{year}.csv"] = "\n".join(lines) + "\n"

    # ECB: units per EUR.
    eurusd = walk(11, 1.08, 0.004)
    rates = {"USD": eurusd, "GBP": walk(12, 0.86, 0.003), "JPY": walk(13, 160, 0.006), "CHF": walk(14, 0.95, 0.004),
             "CNY": [u * 7.2 * (1 + 0.0003 * math.sin(i / 9)) for i, u in enumerate(eurusd)]}
    head = "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_CONF,TITLE"
    lines = [head]
    for ccy, vals in rates.items():
        for d, v in zip(DAYS, vals):
            if d in HOLIDAYS:
                continue
            lines.append(f"EXR.D.{ccy}.EUR.SP00.A,D,{ccy},EUR,SP00,A,{d.isoformat()},{v:.4f},A,F,{ccy}/Euro ECB reference exchange rate")
    files["ecb_EXR.csv"] = "\n".join(lines) + "\n"

    files["manifest.json"] = json.dumps({"run_id": "DEMO", "as_of": AS_OF.isoformat(), "note": "synthetic demo data"}) + "\n"
    for name, text in files.items():
        (OUT / name).write_text(text, encoding="utf-8")
        print("wrote", name)


if __name__ == "__main__":
    main()
