# AI build log

Built with **Claude Code** (Claude Opus 5.5). The rule throughout: **AI writes, tests decide.**

| # | Step | How it was checked |
|---|---|---|
| 1 | Source choice and probing | Every candidate source was probed live before any code was written. FRED, Treasury and ECB returned data. FRED's gold series returned an HTML page and was dropped; Stooq returned a bot-check page and was not used; Yahoo was ruled out (unofficial API). The probe also showed FRED now marks missing values with an empty cell rather than `.`, so the parser handles both |
| 2 | Test data first | `tests/fixtures/make_fixtures.py` writes synthetic data in the exact real file formats, with each series built to trigger a specific rule (documented at the top of the file) |
| 3 | Analytics | Hand-calculated expected values in tests: % and bp changes, as-of lookups across gaps, month-end arithmetic, YTD base, volatility (against `statistics.stdev`), max drawdown, USD crosses |
| 4 | Excel | Opened and read back in tests: sheet order, 6 native charts, rebased FX columns, colour-coded statuses, curve and 2s10s rows |
| 5 | AI summary (optional) | Request shape tested (model, structured output, refusal fallbacks, no sampling parameters). The number check rejects invented figures, and a refusal, truncation or invalid JSON leaves the run unaffected. Runs only when enabled **and** a key is set |
| 6 | Scheduling | PSScriptAnalyzer: 0 findings. `-WhatIf` dry run, including the config pre-flight; nothing registered on the build PC |

## What the checks caught
- **ECB archive name bug:** the first version named the archived ECB file after the URL path (`ecb_D.USD+GBP….csv`). The demo failed to find it, and the FX series came back empty with a run ALERT. Fixed to use the dataflow name (`ecb_EXR.csv`); covered by `test_raw_names_ignore_dates_so_rebuild_finds_the_file`.
- **Signal suppressed by an unrelated data issue:** one excluded out-of-range VIX value marked the series ERROR, and the VIX check went to N/A even though the latest value was fine. Now the check still runs, and notes the data issue in "why it matters".
- **Floating-point noise:** the 2s10s spread displayed as 58.99999999999999. Now rounded to 0.1 bp at the source of the calculation.
- **Staleness false alarm:** FRED publishes Brent/WTI about a week late, so a 5-business-day limit would warn every week. Added a per-series `stale_business_days` (10 for oil). Found while designing the demo, before the live run.
- **Licensing:** a first draft would have committed the full live report. FRED's S&P/Dow/Nasdaq/VIX/ICE series are third-party data with redistribution limits, so the committed live sample is rebuilt with a generated public-only config (`tools/make_public_config.py`, kept in sync by a test).
- **Mutation checks (4 of 4 caught):** "first duplicate wins" instead of "last"; `>` instead of `>=` at the ALERT boundary; a number check that accepts anything; changes measured from the first observation instead of the as-of base. Each made at least one test fail, and restoring the code made the suite pass again.

## Live verification (2026-11-25)
One live run: 16/16 series, 0 data issues, 14 requests, 0 retries. Spot checks: FRED DGS10 (4.92 on 2026-11-23) equals the Treasury curve's 10-year on the same day; the Treasury 2s10s (+28 bp) equals FRED T10Y2Y (0.28). The `rebuild` of that run's raw folder ran offline and produced the public sample.

## Not verified yet
| Item | How |
|---|---|
| AI summary against the real API | Needs an Anthropic key: set `[ai] enabled = true`, run, check the Dashboard summary and the log line "all figures verified" |
| Scheduled task firing for real / launchd on the iMac | TEST_PLAN T08–T10 |
| Webhook to a real Slack channel | TEST_PLAN T06 |
