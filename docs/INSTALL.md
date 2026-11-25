# Installation

About 15 minutes. Windows or macOS, Python 3.11+. No API keys needed (the Anthropic key is only needed for the optional AI summary).

## 1. Get the code and create the environment
```bash
git clone https://github.com/ShadhirMM/Financial-market-research-automation.git
cd Financial-market-research-automation
python -m venv .venv
.venv\Scripts\Activate.ps1            # macOS: source .venv/bin/activate
pip install -e ".[dev]"               # or ".[dev,ai]" for the optional Claude summary
```

## 2. Prove it works offline
```bash
pytest                                # 70 passed
python -m market_research demo        # reports/latest_DEMO.xlsx (synthetic data)
```

## 3. First live run
```bash
python -m market_research check
python -m market_research run         # about 1 minute; reports/latest.xlsx
```
Open the Dashboard sheet, then Data_Quality. Raw downloads are archived under `data/raw/<run_id>/`.

## 4. Optional settings (`.env`, git-ignored; copy from `.env.example`)
- `STATUS_WEBHOOK_URL`: Slack-compatible webhook. Each run posts `[OK]`/`[WARNING]`/`[ALERT]` plus the WATCH/ALERT signals.
- `ANTHROPIC_API_KEY` **and** `[ai] enabled = true` in `config/config.toml`: adds a Claude-written summary to the Dashboard. Only the computed facts are sent, and any summary containing a number that is not in the facts is discarded. Set a monthly spend limit on the key.

## 5. Choose series and rules
Edit `config/config.toml`. Add FRED series by their ID (check them on fred.stlouisfed.org first), and adjust ranges, jump limits and the `[[checks]]` rules. Run `python -m market_research check`, then `pytest`. If you changed series, run `python tools/make_public_config.py` (a test enforces this).

## 6. Schedule it (weekly, Monday 06:00)
Windows:
```powershell
.\scripts\windows\Register-ResearchTask.ps1 -WhatIf     # preview (runs the config check first)
.\scripts\windows\Register-ResearchTask.ps1             # register (-Day Friday -Time 18:30 to change)
Start-ScheduledTask -TaskName 'Market Research Pack'    # test now
Get-ScheduledTaskInfo -TaskName 'Market Research Pack'  # LastTaskResult 0 = OK/WARNING, 1 = ALERT, 2 = fatal
.\scripts\windows\Unregister-ResearchTask.ps1           # rollback
```
macOS:
```bash
chmod +x scripts/macos/install-launchd.sh && ./scripts/macos/install-launchd.sh
launchctl kickstart -k gui/$(id -u)/com.example.market-research
./scripts/macos/install-launchd.sh --remove             # rollback
```
cron: `0 6 * * 1 cd /opt/market-research && .venv/bin/python -m market_research run >> logs/cron.log 2>&1`
