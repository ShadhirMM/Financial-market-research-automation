# Financial Market Research Automation: market & macro research pack

[![tests](https://github.com/ShadhirMM/Financial-market-research-automation/actions/workflows/tests.yml/badge.svg)](https://github.com/ShadhirMM/Financial-market-research-automation/actions/workflows/tests.yml)

A scheduled **Python** program that downloads **official public market data** from these sources:
- **FRED** (Federal Reserve Bank of St. Louis)
- the **U.S. Treasury** yield curve
- **ECB** euro reference rates

It cleans and validates the data, runs **research checks** (OK / WATCH / ALERT, each with a plain-English reason), and writes a **clean Excel research pack** with native charts.

> Built as a portfolio project for an *IT Specialist (AI & Automation)* role whose job description asks for *"scripts that collect public market data and rebuild research datasets"* and to *"automate recurring research checks with AI tools and report results clearly."* Its sister project, [automated-data-collection](https://github.com/ShadhirMM/automated-data-collection), covers company fundamentals from SEC EDGAR. This one covers markets and macro.

| Requirement | How it is met |
|---|---|
| **Retrieves public financial data** | 11 FRED series (equity indices, VIX, Fed funds, 2Y/10Y yields, 2s10s, high-yield spread, Brent/WTI), the full Treasury par yield curve, and 5 FX rates from ECB reference rates. No API keys, polite per-host rate limit, retries with back-off and `Retry-After` |
| **Clean data** | Missing-value markers (`''`, `.`), duplicates (last value wins), out-of-range values excluded, holidays left as gaps (never forward-filled), USD crosses derived from same-day ECB rates |
| **Validated** | Stale series (per-series limits), gaps, implausible jumps, out-of-range values, missing curve tenors, Treasury vs FRED 2s10s consistency. Per-series quality flag |
| **Excel report** | 11 sheets: README/method, Dashboard (signals + key figures), Signals, Curve, Equities, Rates, Volatility & Credit, Commodities, FX, Data_Quality, Run_Log. Native line charts, number formats, colour-coded status |
| **Research checks** | 9 configurable rules: VIX level, S&P/Nasdaq drawdown, curve inversion, 10Y weekly move, HY spread widening, Brent move, EUR/USD and USD/JPY moves |
| **AI (optional)** | Claude writes a short summary **from the computed numbers only**. Every number in the summary is checked against the facts that were sent; a summary with any invented figure is rejected. Off by default |
| **Runs on a schedule** | Windows Task Scheduler (with `-WhatIf` and rollback), macOS launchd, cron. Lock file, exit codes, rotating logs, JSON run summary, OK/WARNING/ALERT webhook |
| **Rebuild** | Every live run archives the raw downloads. `rebuild` re-creates the report offline with identical numbers |

## Live run evidence (2026-11-25)

One live run against the official sources: **16/16 series, 0 data issues, 14 requests, 0 retries**, run status OK. Signals: 1 ALERT (Brent −28.4% over 1 month) and 3 WATCH (10-year yield −20 bp in a week, VIX 26.36, Nasdaq −14.0% from its 52-week high). The Treasury curve's 2s10s (+28 bp) agrees with FRED's T10Y2Y.

- [`docs/sample/market_research_LIVE_2026-11-25_public.xlsx`](docs/sample/market_research_LIVE_2026-11-25_public.xlsx): the live data, rebuilt offline from that run's raw files **without the series whose owners do not allow redistribution** (S&P 500, Dow Jones, Nasdaq, VIX, ICE BofA spread; see [licensing](docs/DATA_DICTIONARY.md#sources-and-licensing)). Running the tool yourself gives the full 16-series report.
- [`docs/sample/live-run-2026-11-25.log`](docs/sample/live-run-2026-11-25.log): log of the full live run.
- [`docs/sample/market_research_DEMO.xlsx`](docs/sample/market_research_DEMO.xlsx): the offline demo (synthetic data built to trigger every rule).

## Run it

```bash
python -m venv .venv && .venv/Scripts/activate      # macOS: source .venv/bin/activate
pip install -e ".[dev]"            # add ,ai for the optional Claude summary
pytest                             # 70 tests, offline
python -m market_research demo     # offline demo -> reports/latest_DEMO.xlsx
python -m market_research run      # live -> reports/latest.xlsx
python -m market_research rebuild --raw data/raw/<run_id>   # offline, same numbers as that run
```
Schedule it with `scripts\windows\Register-ResearchTask.ps1` or `scripts/macos/install-launchd.sh`. See [docs/INSTALL.md](docs/INSTALL.md).

## Run status vs market signals

The program reports two different things, and keeps them apart:

| | Values | About | Effect |
|---|---|---|---|
| **Run status** | OK / WARNING / ALERT | Did the pipeline work? (ALERT = a source or series could not be collected) | Exit code 0 (OK/WARNING) or 1 (ALERT); 2 = fatal |
| **Signals** | OK / WATCH / ALERT | What the market data says | Reported in the Excel file and the webhook; never changes the exit code |

## How the numbers are computed
- **Changes** compare the latest value with the last observation **on or before** the window start (1W = 7 days, 1M/3M/1Y = calendar months, YTD = previous year end), so weekends and holidays never break a comparison. Levels are in %, rates and spreads in **basis points**.
- **Volatility** is annualised: standard deviation of daily log returns × √252 (levels), or of daily bp changes × √252 (rates).
- **Drawdown** is the % below the 52-week high, plus the maximum peak-to-trough fall over 1 year.
- **FX crosses** come from ECB rates on the same day, e.g. USDJPY = (JPY per EUR) ÷ (USD per EUR).

Every formula is unit-tested against hand-calculated values: [tests/TEST_PLAN.md](tests/TEST_PLAN.md).

## Repository
```
config/config.toml          series, valid ranges, jump limits, research-check rules, schedule-related settings
config/public-sample.toml   generated: redistributable series only (for the committed live sample)
src/market_research/        http_client · sources · analytics · validate · checks · ai_summary · excel_report · runner · ops · cli
scripts/windows|macos/      scheduling (install + rollback)
tests/                      70 pytest tests + synthetic fixtures in the real file formats (make_fixtures.py)
docs/                       INSTALL · OPERATIONS · DATA_DICTIONARY · CHANGE_CONTROL · SECURITY · AI_BUILD_LOG · sample/
```

## Limitations
- FRED re-publishes third-party data under the owners' terms. Reports are for internal research use; do not republish restricted series.
- FRED's S&P 500, Dow Jones and Nasdaq series only cover the last ~10 years (licence limit). Brent/WTI on FRED lag by about a week, which is why they have their own staleness limit.
- Daily close data only. No intraday data, and no individual stocks (see the EDGAR project for company data).
- Research, not investment advice.

## How AI was used
Built with Claude Code. Every output was checked by tests, 4 mutation checks and one live run. See [docs/AI_BUILD_LOG.md](docs/AI_BUILD_LOG.md).

## License
MIT © Mushaff Shadhir (code). Data belongs to its publishers; see the licensing table in DATA_DICTIONARY.md.
