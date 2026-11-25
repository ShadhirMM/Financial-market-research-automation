# Change control

Covers code, `config/config.toml` (series, ranges, rules) and the schedule.

1. **Scope.** Under *Unreleased* in `CHANGELOG.md`, write what changes, why, the risk and the rollback.
2. **Test.**
   - `pytest` passes. A code change comes with a test that fails without it.
   - **Rebuild comparison:** `python -m market_research rebuild --raw data/raw/<recent run>` before and after the change. The raw folder is a fixed input, so every difference in the Dashboard, Signals and Data_Quality sheets comes from the change. Confirm each difference is intended.
   - Config change: `python -m market_research check`. Series changes: `python tools/make_public_config.py`.
3. **Deploy.** `git pull` on the machine that runs the schedule, then tag `vX.Y.Z`.
4. **Verify.** Start the task by hand once; check the status message, the log and the report.
5. **Roll back.** `git checkout v<previous>`, then rebuild from the latest raw folder to regenerate `latest.xlsx`. For the schedule: `Unregister-ResearchTask.ps1` / `install-launchd.sh --remove`, then register the previous settings.

## Record

| Date | Version | Change | Tests | Rebuild comparison | Rollback |
|---|---|---|---|---|---|
| 2026-11-25 | 1.0.0 | First release | 70/70 | Rebuild from the live run's raw files: report produced offline, status OK | Unregister script; task registration dry-run (`-WhatIf`) |
