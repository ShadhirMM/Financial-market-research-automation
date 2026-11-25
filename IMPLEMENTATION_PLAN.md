# Financial Market Research Automation: implementation plan

> **Status: v1.0.0 complete and verified live (2026-11-25).** 70 tests pass; one live run against the official sources (16/16 series, run status OK); public live sample and demo committed. **Still open:** the AI summary against the real API (needs a key), registering the schedule for real, and a real webhook (TEST_PLAN T05–T10).

**Brief:** a Python program that retrieves public financial data and generates a clean Excel report.

**Scope decision:** the sister project (automated-data-collection) covers company fundamentals from SEC EDGAR. This one covers **markets and macro** (indices, volatility, rates, curve, credit, oil, FX) from official keyless sources, plus rule-based **research checks**. That matches the job description's "exchange data" and "recurring research checks" lines without repeating the EDGAR work.

| # | Phase | Done |
|---|---|---|
| 1 | Probe sources live; choose FRED + Treasury + ECB; drop gold (no data), Stooq (bot check), Yahoo (unofficial) | ✅ |
| 2 | Config with valid ranges, jump limits, per-series staleness, check rules | ✅ |
| 3 | HTTP client: per-host rate limit, retries, Retry-After, HTML detection, raw archive + manifest | ✅ |
| 4 | Parsers for the 3 formats; synthetic fixtures in the same formats | ✅ |
| 5 | Cleaning + analytics (as-of changes, vol, drawdown, 52w, curve, crosses) | ✅ |
| 6 | Validation (8 rules) + research checks (9 rules) | ✅ |
| 7 | Optional AI summary with number verification | ✅ (offline-tested) |
| 8 | Excel with native charts; run status; logs; webhook; lock; pruning; rebuild; demo | ✅ |
| 9 | Scheduling: Task Scheduler (+ rollback), launchd (+ rollback), cron | ✅ (dry run) |
| 10 | Tests (70) + mutation checks + CI matrix | ✅ |
| 11 | One live run + licensing-safe public sample | ✅ |
| 12 | Docs | ✅ |

## Mapping to the job description
| Job description | Where |
|---|---|
| "scripts that collect public market data and rebuild research datasets" | `run` + `rebuild --raw` (identical numbers, tested) |
| "Automate recurring research checks with AI tools and report results clearly" | Weekly schedule, 9 rules with plain-English explanations, optional verified AI summary, webhook |
| "public market sources … exchange data … delivered as clean, documented Excel files" | 11-sheet workbook with README/method sheet and DATA_DICTIONARY.md |
| "All outputs, including AI-written code, must be checked and tested" | 70 tests, mutation checks, number check on AI text, AI_BUILD_LOG.md |
| "Package each program with its configuration, installation steps and documentation" | pyproject, config.toml, INSTALL.md, OPERATIONS.md |
| "change control … tested rollback" | CHANGE_CONTROL.md (rebuild comparison), unregister/remove scripts |
| Company iMac / macOS | launchd job |
