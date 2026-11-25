# Security, compliance and data handling

## Data
- **Public market data only**, from official publishers. No personal, client or portfolio data is read, stored or sent.
- The HTTP user agent is a generic program name with the project URL. It contains no names or email addresses.
- Secrets (`STATUS_WEBHOOK_URL`, `ANTHROPIC_API_KEY`) live only in `.env` (git-ignored) or the environment.

## Being a good API citizen
- At most 2 requests per second per host (config validation rejects more than 5). One request per series per run, plus 2 Treasury files and 1 ECB request: **14 requests a week**.
- Retries only for temporary errors, honouring `Retry-After`; never for 4xx.
- An HTML page where data was expected (a bot check or maintenance page) is treated as an error, never parsed as data.

## Licensing
Some FRED series belong to third parties (S&P Dow Jones Indices, Nasdaq, Cboe, ICE) whose terms restrict redistribution. Reports are for internal research. The public repository contains only synthetic demo data and a live sample limited to public-domain/ECB series (see DATA_DICTIONARY.md → Sources and licensing).

## Optional AI summary
- Off by default. When on, only the computed facts table and signal texts are sent to the Anthropic API: no raw data and nothing about the organisation.
- **Number check:** every number in Claude's reply must appear in the facts that were sent, or the whole summary is discarded and the run continues without it. Claude can choose words, but it cannot introduce figures.
- The request asks for structured output (a JSON schema). Refusal fallbacks are enabled (`fallbacks: "default"`) so a declined request is retried on a fallback model in the same call; a final refusal just skips the summary.
- Give the API key its own workspace and a monthly spend limit.

## Program safety
- Atomic writes: no half-written workbook ever replaces `latest.xlsx`.
- A lock file stops overlapping runs; a lock older than 2 hours is taken over.
- The scheduled task runs as the normal user, not as administrator.
- Dependencies: `requests` and `openpyxl` (plus `anthropic` only with the `ai` extra, and `pytest` for development).
