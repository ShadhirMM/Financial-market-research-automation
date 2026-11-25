# Test plan

## Automated: 70 pytest tests (CI: Linux + Windows × Python 3.11 / 3.12 / 3.13, offline)
Latest local results: `tests/TEST_RESULTS.txt`.

| File | Covers |
|---|---|
| `test_config_http.py` | Default config; 9 kinds of invalid config rejected; secrets from the environment; retries with back-off; `Retry-After`; network errors retried; gives up after max retries; 4xx not retried; HTML-instead-of-data rejected; per-host rate limit; archive names stable across dates; replay session; the public-sample config is in sync and free of restricted series |
| `test_sources_analytics.py` | FRED parser (blank and `.` missing values, BOM, wrong header, garbage); Treasury parser (columns by name, blank cells); ECB parser and hand-computed crosses; cleaning (last duplicate wins, missing, out-of-range); month arithmetic and windows; business days; as-of lookup; % and bp changes; volatility vs `statistics.stdev`; max drawdown; summary row; curve snapshot and 2s10s |
| `test_validate_checks_ai.py` | Every validation rule including per-series staleness and curve rules; every check type and direction including exact boundaries; explanations and units; N/A cases; signal ordering; AI facts text, number check, request shape, and rejection of invented numbers, refusals, truncation and invalid JSON |
| `test_end_to_end.py` | Demo run (sheets, charts, signals, Data_Quality, curve inversion a year ago, rebased FX, JSON summary without absolute paths); live-style run then `rebuild` gives identical numbers; ECB/FRED/Treasury failures each isolated with the right N/A and quality flags; format change caught; nothing collected never replaces `latest.xlsx`; AI summary off by default, added when enabled, rejected when it invents a figure; exit codes for bad config / missing raw folder / lock; stale lock; webhook text and failure; pruning |

**Mutation checks** (done once, at release): 4 deliberate bugs, 4 caught. See AI_BUILD_LOG.md.

## Live run (done 2026-11-25)
| ID | Test | Result |
|---|---|---|
| L01 | `python -m market_research run` against FRED, Treasury and ECB | ✅ 16/16 series, 0 data issues, 14 requests, run status OK |
| L02 | FRED DGS10 vs Treasury 10 Yr on the same day | ✅ 4.92 = 4.92 |
| L03 | Treasury 2s10s vs FRED T10Y2Y | ✅ +28 bp = 0.28 |
| L04 | `rebuild --raw` of the live run (offline) with the public-sample config | ✅ report produced, status OK |

## Manual (before go-live)
| ID | Test | Pass when |
|---|---|---|
| T01 | Spot-check 3 Dashboard values against the source websites | Match |
| T02 | Disconnect the network, run | Retries in the log, then exit 1 (ALERT); no partial `latest.xlsx` |
| T03 | Wrong FRED ID in the config | That series ERROR / N/A, the rest fine, exit 1 |
| T04 | Two runs at once | The second exits 2 |
| T05 | Enable AI with a key | Summary on the Dashboard; log says "all figures verified" |
| T06 | Webhook to a real channel | Message with status and WATCH/ALERT signals |
| T07 | `Register-ResearchTask.ps1 -WhatIf`, then for real | Task visible with the weekly trigger |
| T08 | `Start-ScheduledTask` | `LastTaskResult` 0, new report |
| T09 | `Unregister-ResearchTask.ps1` | Task removed, data kept |
| T10 | macOS `install-launchd.sh`, `kickstart`, `--remove` | Report produced; job removed |
