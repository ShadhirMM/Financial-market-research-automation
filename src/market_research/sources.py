"""Official, keyless public data sources and their parsers.

- FRED (Federal Reserve Bank of St. Louis), graph CSV download:
    https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>&cosd=<YYYY-MM-DD>
- U.S. Treasury daily par yield curve rates, one CSV per year:
    https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/<YEAR>/all?...
- ECB euro foreign exchange reference rates (SDMX data API, CSV):
    https://data-api.ecb.europa.eu/service/data/EXR/D.USD+GBP+JPY+CHF+CNY.EUR.SP00.A?startPeriod=...&format=csvdata

Every parser returns plain Python data and raises ValueError on an unexpected
shape, so a changed source format fails loudly instead of producing bad numbers.
"""
from __future__ import annotations

import csv
import io
import math
from datetime import date, datetime

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&cosd={start}"
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                "{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
ECB_CURRENCIES = ("USD", "GBP", "JPY", "CHF", "CNY")
ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{ccys}.EUR.SP00.A?startPeriod={start}&format=csvdata"

Obs = list[tuple[date, float | None]]


def _num(text: str) -> float | None:
    """'' and '.' (FRED's old missing-value marker) mean no observation."""
    t = (text or "").strip()
    if t in ("", ".", "ND", "N/A", "NA"):
        return None
    v = float(t)  # ValueError on garbage is intended
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def parse_fred_csv(text: str, series_id: str) -> Obs:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if not rows or len(rows[0]) < 2:
        raise ValueError(f"FRED {series_id}: empty or malformed CSV")
    header = [h.strip() for h in rows[0]]
    if header[0].lower() not in ("observation_date", "date") or header[1] != series_id:
        raise ValueError(f"FRED {series_id}: unexpected header {header[:2]}")
    out: Obs = []
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        out.append((date.fromisoformat(r[0].strip()), _num(r[1] if len(r) > 1 else "")))
    return out


def parse_treasury_csv(text: str) -> dict[date, dict[str, float]]:
    """{date: {tenor: yield %}}. Column sets differ between years, so columns are matched by name."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or reader.fieldnames[0].strip() != "Date":
        raise ValueError("Treasury: expected a 'Date' first column")
    out: dict[date, dict[str, float]] = {}
    for row in reader:
        raw_date = (row.get("Date") or "").strip()
        if not raw_date:
            continue
        d = datetime.strptime(raw_date, "%m/%d/%Y").date()
        values = {}
        for k, v in row.items():
            if k is None or k.strip() == "Date":
                continue
            n = _num(v or "")
            if n is not None:
                values[k.strip()] = n
        out[d] = values
    return out


def parse_ecb_csv(text: str) -> dict[str, Obs]:
    """{currency: [(date, units per EUR)]}."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    needed = {"CURRENCY", "CURRENCY_DENOM", "TIME_PERIOD", "OBS_VALUE"}
    if not reader.fieldnames or not needed <= set(reader.fieldnames):
        raise ValueError(f"ECB: missing columns {sorted(needed - set(reader.fieldnames or []))}")
    out: dict[str, Obs] = {}
    for row in reader:
        if row["CURRENCY_DENOM"] != "EUR":
            continue
        out.setdefault(row["CURRENCY"], []).append((date.fromisoformat(row["TIME_PERIOD"]), _num(row["OBS_VALUE"])))
    return out


def ecb_crosses(per_eur: dict[str, Obs]) -> dict[str, Obs]:
    """USD-based crosses from euro reference rates (all quoted per 1 EUR on the same day).

    EURUSD = USD/EUR; GBPUSD = USD/EUR ÷ GBP/EUR; USDJPY = JPY/EUR ÷ USD/EUR (same for CHF, CNY).
    """
    usd = {d: v for d, v in per_eur.get("USD", []) if v}
    out: dict[str, Obs] = {"EURUSD": sorted(usd.items())}
    gbp = {d: v for d, v in per_eur.get("GBP", []) if v}
    out["GBPUSD"] = sorted((d, usd[d] / g) for d, g in gbp.items() if d in usd)
    for ccy in ("JPY", "CHF", "CNY"):
        per = {d: v for d, v in per_eur.get(ccy, []) if v}
        out[f"USD{ccy}"] = sorted((d, x / usd[d]) for d, x in per.items() if d in usd)
    return out
