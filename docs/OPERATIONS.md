# Operations runbook

## After each scheduled run (2 minutes)
1. Read the webhook message, or `logs/runs/run_<id>.json`.
   - **Run status OK/WARNING**: the pipeline worked. For a WARNING, read the Data_Quality sheet.
   - **Run status ALERT**: a source or series failed; see *Failures* below. The report is still produced with everything else.
2. Read the **Signals** at the top of the Dashboard. WATCH/ALERT signals are research findings for the team, not system faults. Pass them on as agreed (e.g. in the weekly note).
3. `latest.xlsx` is replaced only when at least one series was collected.

## Data-quality findings

| Rule | What to do |
|---|---|
| out_of_range (ERROR) | Look at the value on the source website. If it is a source error, it is already excluded; note it. If the market really moved there, widen `valid_min`/`valid_max` through change control |
| jump | Compare with the source chart for that date. Real (crash, policy surprise): no action. Source error: report it to the publisher |
| stale | Check the series page on FRED (holiday? discontinued?). A series that FRED discontinues must be replaced in the config |
| gap | Usually a publisher outage or discontinuation; check the source |
| inconsistent_2s10s | One of the two sources is late or revised; it usually clears on the next run. If it repeats, compare the two websites |
| tenor_missing | Treasury changed its columns; check the CSV header and `[treasury] tenors` |

## Failures (run ALERT)

| Log | Cause | Fix |
|---|---|---|
| `HTTP 429` / `5xx`, retries exhausted | Source busy or down | Rerun later: `python -m market_research run` |
| `HTML page instead of data` | Bot check or source maintenance page | Wait and rerun; if it persists, check the URL in a browser |
| `unexpected header` / `missing columns` | The source changed its file format | Run `rebuild --raw` on that run's folder to reproduce it; update `sources.py` and add a test |
| `HTTP 404` for one FRED series | Series ID renamed or discontinued | Find the new ID on FRED and update the config |
| `Another run is in progress` | Overlap or a crashed run | A lock older than 2 hours is taken over automatically |

Reproduce any run offline: `python -m market_research rebuild --raw data/raw/<run_id>` gives the same numbers, the same signals and the same data as-of date.

## Files

| Path | Kept |
|---|---|
| `reports/market_research_<run>.xlsx`, `reports/latest.xlsx` | Last 52 reports |
| `data/raw/<run>/` (raw downloads + manifest) | 90 days |
| `logs/research.log`, `logs/errors.log` | Rotating, 1 MB × 5 |
| `logs/runs/run_<run>.json` | Small; not pruned |

## Monthly
- Review the signal thresholds with the research team: are they useful, too noisy or too quiet?
- Check that the scheduled task still exists and its last result is 0.
- `pip list --outdated`. Update dependencies through change control.
