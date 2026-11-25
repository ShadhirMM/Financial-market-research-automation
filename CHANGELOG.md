# Changelog

## [1.0.0] - 2026-11-25
- Sources: FRED (11 series), U.S. Treasury daily par yield curve, ECB euro reference rates (5 USD crosses). No API keys.
- HTTP: per-host rate limit, retries with back-off and Retry-After, HTML-instead-of-data detection, raw archive with manifest.
- Cleaning, validation (8 rules, per-series quality), analytics (as-of changes, volatility, drawdown, 52-week range, curve and 2s10s).
- 9 configurable research checks (OK / WATCH / ALERT with explanations); optional Claude summary with number verification.
- 11-sheet Excel report with native charts; run summary JSON; rotating logs; webhook; lock; pruning; rebuild and demo modes.
- Scheduling: Windows Task Scheduler (register/unregister, -WhatIf), macOS launchd, cron.
- 70 tests (CI: Linux + Windows, Python 3.11-3.13); one live run 2026-11-25 (16/16 series, status OK).
