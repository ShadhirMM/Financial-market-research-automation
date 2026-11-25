import math
import statistics
from datetime import date

import pytest

from market_research.analytics import (as_of, business_days_between, change, clean, curve_snapshot, max_drawdown,
                                       minus_months, summarise, volatility, window_start)
from market_research.sources import ecb_crosses, parse_ecb_csv, parse_fred_csv, parse_treasury_csv

from conftest import sd

D = date


# ---------- parsers ----------

def test_fred_parser_handles_blank_and_dot_missing_values_and_bom():
    text = "﻿observation_date,DGS10\n2026-11-10,4.98\n2026-11-11,\n2026-11-12,.\n2026-11-13,5.15\n\n"
    assert parse_fred_csv(text, "DGS10") == [(D(2026, 11, 10), 4.98), (D(2026, 11, 11), None), (D(2026, 11, 12), None),
                                             (D(2026, 11, 13), 5.15)]


def test_fred_parser_rejects_wrong_series_or_shape():
    with pytest.raises(ValueError, match="unexpected header"):
        parse_fred_csv("observation_date,DGS2\n2026-01-02,4\n", "DGS10")
    with pytest.raises(ValueError, match="malformed"):
        parse_fred_csv("", "DGS10")
    with pytest.raises(ValueError):
        parse_fred_csv("observation_date,DGS10\n2026-01-02,abc\n", "DGS10")


def test_treasury_parser_matches_columns_by_name():
    text = 'Date,"1 Mo","1.5 Month","2 Yr","10 Yr"\n11/24/2026,4.21,4.27,4.63,4.91\n11/21/2026,4.20,,4.60,\n'
    out = parse_treasury_csv(text)
    assert out[D(2026, 11, 24)] == {"1 Mo": 4.21, "1.5 Month": 4.27, "2 Yr": 4.63, "10 Yr": 4.91}
    assert out[D(2026, 11, 21)] == {"1 Mo": 4.20, "2 Yr": 4.60}
    with pytest.raises(ValueError, match="Date"):
        parse_treasury_csv("When,1 Mo\n")


def test_ecb_parser_and_usd_crosses_hand_computed():
    text = ("KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
            "k,D,USD,EUR,SP00,A,2026-11-24,1.1000\n"
            "k,D,GBP,EUR,SP00,A,2026-11-24,0.8800\n"
            "k,D,JPY,EUR,SP00,A,2026-11-24,165.00\n"
            "k,D,CHF,EUR,SP00,A,2026-11-24,0.9350\n"
            "k,D,CNY,EUR,SP00,A,2026-11-24,7.9200\n"
            "k,D,JPY,EUR,SP00,A,2026-11-25,166.00\n")  # no USD that day -> no USDJPY
    x = ecb_crosses(parse_ecb_csv(text))
    day = D(2026, 11, 24)
    assert x["EURUSD"] == [(day, 1.1)]
    assert x["GBPUSD"] == [(day, pytest.approx(1.25))]       # 1.10 / 0.88
    assert x["USDJPY"] == [(day, pytest.approx(150.0))]      # 165 / 1.10
    assert x["USDCHF"] == [(day, pytest.approx(0.85))]       # 0.935 / 1.10
    assert x["USDCNY"] == [(day, pytest.approx(7.2))]        # 7.92 / 1.10
    with pytest.raises(ValueError, match="missing columns"):
        parse_ecb_csv("TIME_PERIOD,OBS_VALUE\n")


# ---------- cleaning ----------

def test_clean_keeps_last_duplicate_drops_missing_and_out_of_range():
    obs = [(D(2026, 1, 3), 3.0), (D(2026, 1, 1), 1.0), (D(2026, 1, 2), None), (D(2026, 1, 1), 1.5), (D(2026, 1, 4), -7.0)]
    r = clean(obs, sd(vmin=0, vmax=100))
    assert r.series == [(D(2026, 1, 1), 1.5), (D(2026, 1, 3), 3.0)]
    assert (r.duplicates, r.missing, r.out_of_range) == (1, 1, [(D(2026, 1, 4), -7.0)])


# ---------- dates ----------

def test_month_arithmetic_and_windows():
    assert minus_months(D(2026, 3, 31), 1) == D(2026, 2, 28)
    assert minus_months(D(2028, 3, 31), 1) == D(2028, 2, 29)
    assert minus_months(D(2026, 1, 15), 3) == D(2025, 10, 15)
    assert minus_months(D(2026, 11, 24), 12) == D(2025, 11, 24)
    assert window_start(D(2026, 11, 24), "1W") == D(2026, 11, 17)
    assert window_start(D(2026, 11, 24), "YTD") == D(2025, 12, 31)
    with pytest.raises(ValueError):
        window_start(D(2026, 1, 1), "2W")


def test_business_days_between():
    assert business_days_between(D(2026, 11, 20), D(2026, 11, 23)) == 1   # Fri -> Mon
    assert business_days_between(D(2026, 11, 24), D(2026, 11, 25)) == 1
    assert business_days_between(D(2026, 11, 2), D(2026, 11, 16)) == 10
    assert business_days_between(D(2026, 11, 25), D(2026, 11, 25)) == 0


# ---------- analytics (hand-computed) ----------

S = [(D(2025, 12, 31), 100.0), (D(2026, 10, 23), 110.0), (D(2026, 11, 13), 120.0), (D(2026, 11, 17), 115.0),
     (D(2026, 11, 24), 126.5)]


def test_as_of_uses_last_observation_on_or_before():
    assert as_of(S, D(2026, 11, 20)) == (D(2026, 11, 17), 115.0)
    assert as_of(S, D(2025, 1, 1)) is None


def test_changes_pct_and_bps():
    assert change(S, "1W", "pct") == pytest.approx(10.0)       # 126.5 vs 115 (Nov 17)
    assert change(S, "1M", "pct") == pytest.approx(15.0)       # vs 110 (Oct 23, as of Oct 24)
    assert change(S, "YTD", "pct") == pytest.approx(26.5)      # vs 100 (Dec 31)
    assert change(S, "1Y", "pct") is None                      # no data a year back
    rates = [(D(2026, 11, 17), 4.62), (D(2026, 11, 24), 4.89)]
    assert change(rates, "1W", "bps") == pytest.approx(27.0)


def test_volatility_matches_hand_calculation():
    prices = [100.0]
    for i in range(30):
        prices.append(prices[-1] * (1.01 if i % 2 == 0 else 0.995))
    s = [(D.fromordinal(D(2026, 1, 1).toordinal() + i), p) for i, p in enumerate(prices)]
    rets = [math.log(b / a) for a, b in zip(prices, prices[1:])]
    assert volatility(s, "pct") == pytest.approx(statistics.stdev(rets) * math.sqrt(252) * 100)
    rates = [(x[0], 4 + (0.05 if i % 2 else 0)) for i, x in enumerate(s)]
    moves = [5.0 if i % 2 == 0 else -5.0 for i in range(30)]
    assert volatility(rates, "bps") == pytest.approx(statistics.stdev(moves) * math.sqrt(252))
    assert volatility(s[:10], "pct") is None  # too short


def test_max_drawdown_hand_computed():
    vals = [100, 120, 90, 130, 104]  # worst: 120 -> 90 = -25%
    assert max_drawdown([(D(2026, 1, i + 1), v) for i, v in enumerate(vals)]) == pytest.approx(-25.0)
    assert max_drawdown([(D(2026, 1, 1), 5.0), (D(2026, 1, 2), -1.0)]) is None


def test_summarise_row():
    row = summarise(sd(sid="IDX"), S)
    assert row["latest"] == 126.5 and row["date"] == D(2026, 11, 24)
    assert row["high_52w"] == 126.5 and row["low_52w"] == 100.0
    assert row["from_high"] == pytest.approx(0.0)
    assert row["max_drawdown_1y"] == pytest.approx((115 / 120 - 1) * 100)  # 120 -> 115
    r = summarise(sd(change="bps", sid="Y"), [(D(2026, 11, 17), 5.0), (D(2026, 11, 24), 4.5)])
    assert r["from_high"] == pytest.approx(-50.0) and r["max_drawdown_1y"] is None
    assert summarise(sd(), [])["latest"] is None


def test_curve_snapshot_today_1m_1y_and_2s10s():
    curve = {D(2025, 11, 21): {"2 Yr": 4.5, "10 Yr": 4.3}, D(2026, 10, 23): {"2 Yr": 4.4, "10 Yr": 4.6},
             D(2026, 11, 24): {"2 Yr": 4.47, "10 Yr": 5.06, "30 Yr": 5.27}}
    snap = curve_snapshot(curve, ("2 Yr", "10 Yr", "30 Yr"))
    assert snap["dates"] == {"today": D(2026, 11, 24), "1M ago": D(2026, 10, 23), "1Y ago": D(2025, 11, 21)}
    assert snap["spread_2s10s_bps"] == {"today": 59.0, "1M ago": 20.0, "1Y ago": -20.0}
    assert snap["rows"][2] == {"tenor": "30 Yr", "today": 5.27, "1M ago": None, "1Y ago": None}
    assert curve_snapshot({}, ("2 Yr",)) is None
