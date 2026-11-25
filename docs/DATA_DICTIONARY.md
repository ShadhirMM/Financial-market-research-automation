# Data dictionary

## Series

| ID | Label | Source | Unit | Changes in | Valid range | Max 1-day move | Stale after |
|---|---|---|---|---|---|---|---|
| SP500 | S&P 500 | FRED | index | % | 100–100,000 | 12% | 5 business days |
| NASDAQCOM | Nasdaq Composite | FRED | index | % | 100–200,000 | 15% | 5 |
| DJIA | Dow Jones Industrial Average | FRED | index | % | 1,000–300,000 | 12% | 5 |
| VIXCLS | CBOE Volatility Index | FRED | index | % | 5–150 | 120% | 5 |
| DFF | Fed funds effective rate | FRED | % | bp | −1–25 | 80 bp | 5 |
| DGS2 | 2-year Treasury yield | FRED | % | bp | −1–25 | 60 bp | 5 |
| DGS10 | 10-year Treasury yield | FRED | % | bp | −1–25 | 50 bp | 5 |
| T10Y2Y | 10Y minus 2Y spread | FRED | % | bp | −5–5 | 50 bp | 5 |
| BAMLH0A0HYM2 | ICE BofA US High Yield OAS | FRED | % | bp | 0–30 | 150 bp | 5 |
| DCOILBRENTEU | Brent crude (USD/bbl) | FRED (EIA) | USD | % | 5–400 | 25% | **10** (FRED lags) |
| DCOILWTICO | WTI crude (USD/bbl) | FRED (EIA) | USD | % | −50–400 | 25% | **10** |
| EURUSD | USD per EUR | ECB | rate | % | 0.5–2.5 | 5% | 5 |
| GBPUSD | USD per GBP | ECB (derived) | rate | % | 0.5–3 | 8% | 5 |
| USDJPY | JPY per USD | ECB (derived) | rate | % | 50–400 | 6% | 5 |
| USDCHF | CHF per USD | ECB (derived) | rate | % | 0.3–2 | 15% | 5 |
| USDCNY | CNY per USD | ECB (derived) | rate | % | 4–12 | 4% | 5 |
| Curve | Treasury par yields, 1M–30Y (11 tenors) | U.S. Treasury | % | bp | −1–25 | — | 5 |

All limits are in `config/config.toml`. The WTI range allows negative prices, because WTI traded below zero in April 2020.

**Derived FX:** ECB quotes every currency per 1 EUR. USD crosses use same-day rates: GBPUSD = USD/EUR ÷ GBP/EUR; USDJPY = JPY/EUR ÷ USD/EUR; USDCHF and USDCNY likewise.

## Key-figure columns (Dashboard)

| Column | Definition |
|---|---|
| Latest / As of | Last valid observation and its date |
| 1W, 1M, 3M, YTD, 1Y | Change versus the last observation on or before: date − 7 days; same day 1/3/12 calendar months earlier (month-end clamped); 31 Dec of the previous year. Levels: % change. Rates/spreads: bp change |
| Volatility 1Y (ann.) | Levels: stdev of daily log returns × √252, in %. Rates: stdev of daily bp changes × √252, in bp. Last 252 observations; blank under 20 |
| 52w high / low | Over observations in the 12 months to the latest date |
| From 52w high | Levels: % below the high. Rates/spreads: bp below the high |
| Max drawdown 1Y | Largest peak-to-trough fall over 12 months, % (levels only) |
| Quality | Worst Data_Quality finding for the series: ERROR > WARNING > OK |

## Curve sheet
Par yields for each tenor today, about 1 month ago and about 1 year ago (the last curve on or before those dates), plus 2s10s in bp for each.

## Validation rules (Data_Quality)

| Rule | Severity | Condition |
|---|---|---|
| no_data | ERROR | No valid observations (or the download failed) |
| out_of_range | ERROR | Values outside the valid range. They are **excluded** from all calculations and listed |
| stale | WARNING | Last observation older than the stale limit (business days to the run date) |
| gap | WARNING | More than 7 business days between observations in the last year |
| jump | WARNING | One-day move larger than the series' max (kept, but flagged for a check against the source) |
| duplicates | INFO | Same date twice; the later row (a revision) is kept |
| tenor_missing | WARNING | A configured curve tenor is missing on the latest curve date |
| inconsistent_2s10s | WARNING | Treasury-curve 2s10s and FRED T10Y2Y differ by more than 10 bp on the same date |

## Research checks (Signals)

| Check | Rule (WATCH / ALERT) |
|---|---|
| Equity volatility | VIX ≥ 25 / ≥ 35 |
| S&P 500 drawdown | ≤ −10% / ≤ −20% from 52w high |
| Nasdaq drawdown | ≤ −10% / ≤ −20% |
| Yield curve 2s10s | ≤ 0 bp / ≤ −50 bp |
| 10-year yield weekly move | size of 1W move ≥ 20 bp / ≥ 35 bp |
| High-yield spread widening | 1M change ≥ +50 bp / ≥ +100 bp |
| Brent oil monthly move | size of 1M move ≥ 10% / ≥ 20% |
| EUR/USD weekly move | size ≥ 2% / ≥ 4% |
| USD/JPY weekly move | size ≥ 2.5% / ≥ 5% |

A check is N/A when its series has no usable data or not enough history. Add a rule with a new `[[checks]]` block (types: level, change, drawdown, curve; directions: above, below, abs).

## Sources and licensing

| Source | What | Terms (summary; check the source before redistributing) |
|---|---|---|
| U.S. Department of the Treasury | Daily par yield curve | U.S. government work, public domain |
| Federal Reserve (via FRED) | DFF, DGS2, DGS10, T10Y2Y | Public domain; cite FRED / Federal Reserve |
| U.S. EIA (via FRED) | DCOILBRENTEU, DCOILWTICO | Public domain; cite EIA |
| European Central Bank | Euro reference rates | Reuse permitted with source attribution (ECB) |
| S&P Dow Jones Indices (via FRED) | SP500, DJIA | **Copyrighted; reproduction needs the owner's permission.** Internal research use only |
| Nasdaq (via FRED) | NASDAQCOM | **Owner's terms apply.** Internal use only |
| Cboe (via FRED) | VIXCLS | **Owner's terms apply.** Internal use only |
| ICE Data Indices (via FRED) | BAMLH0A0HYM2 | **Owner's terms apply.** Internal use only |

For this reason, the committed live sample (`docs/sample/…LIVE…_public.xlsx`) is built with `config/public-sample.toml`, which leaves out the restricted series. Source citation: *Federal Reserve Bank of St. Louis, FRED; U.S. Department of the Treasury; European Central Bank.*
