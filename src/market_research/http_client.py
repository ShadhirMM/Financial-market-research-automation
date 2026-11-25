"""HTTP client: per-host rate limit, retries with back-off, raw-response archive.

Temporary failures (429, 5xx, timeouts, connection errors) are retried and
Retry-After is honoured. Permanent failures (403, 404, other 4xx, HTML instead
of CSV) are raised at once, so the run can log them and carry on with the
other sources.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

import requests

log = logging.getLogger(__name__)

TEMPORARY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(Exception):
    def __init__(self, message: str, *, url: str, status: int | None = None, temporary: bool = False, attempts: int = 1):
        super().__init__(message)
        self.url = url
        self.status = status
        self.temporary = temporary
        self.attempts = attempts


def raw_name(url: str) -> str:
    """Stable archive file name for a source URL (query dates are ignored, so rebuilds find the file)."""
    u = urlparse(url)
    q = parse_qs(u.query)
    if "fred.stlouisfed.org" in u.netloc:
        return f"fred_{q['id'][0]}.csv"
    if "treasury.gov" in u.netloc:
        return f"treasury_{q['field_tdr_date_value'][0]}.csv"
    if "ecb.europa.eu" in u.netloc:
        parts = u.path.strip("/").split("/")
        return f"ecb_{parts[parts.index('data') + 1]}.csv"  # e.g. ecb_EXR.csv (dataflow name)
    return u.path.rstrip("/").split("/")[-1] or "response.txt"


class HttpClient:
    def __init__(
        self,
        user_agent: str,
        *,
        requests_per_second: float = 2,
        timeout: float = 30,
        max_retries: int = 3,
        backoff: tuple[float, ...] = (2, 10, 30),
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        archive_dir: Path | None = None,
    ):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self.min_interval = 1.0 / requests_per_second
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.sleep = sleep
        self.clock = clock
        self.archive_dir = archive_dir
        self._last: dict[str, float] = {}
        self.stats = {"requests": 0, "retries": 0, "failures": 0}

    def _throttle(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = self.min_interval - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last[host] = self.clock()

    def _delay(self, attempt: int, response) -> float:
        if response is not None:
            retry_after = (response.headers or {}).get("Retry-After")
            if retry_after and str(retry_after).isdigit():
                return min(float(retry_after), 300.0)
        return self.backoff[min(attempt, len(self.backoff) - 1)]

    def get_text(self, url: str) -> str:
        host = urlparse(url).netloc
        attempt = 0
        while True:
            self._throttle(host)
            self.stats["requests"] += 1
            response = None
            try:
                response = self.session.get(url, timeout=self.timeout)
                status = response.status_code
                if status == 200:
                    text = response.text
                    if text.lstrip()[:15].lower().startswith(("<!doctype", "<html", "<script")):
                        # Some sites answer bot checks or errors with an HTML page and status 200.
                        self.stats["failures"] += 1
                        raise FetchError(f"HTML page instead of data from {url}", url=url, status=200, attempts=attempt + 1)
                    self._archive(url, text)
                    return text
                temporary = status in TEMPORARY_STATUS
                error = FetchError(f"HTTP {status} from {url}", url=url, status=status, temporary=temporary)
            except (requests.Timeout, requests.ConnectionError) as exc:
                error = FetchError(f"{type(exc).__name__} for {url}: {exc}", url=url, temporary=True)

            if not error.temporary or attempt >= self.max_retries:
                error.attempts = attempt + 1
                self.stats["failures"] += 1
                raise error
            delay = self._delay(attempt, response)
            attempt += 1
            self.stats["retries"] += 1
            log.warning("Temporary error (%s), retry %d/%d in %.0fs", error, attempt, self.max_retries, delay)
            self.sleep(delay)

    def _archive(self, url: str, text: str) -> None:
        if self.archive_dir is None:
            return
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        (self.archive_dir / raw_name(url)).write_text(text, encoding="utf-8")


class ReplaySession:
    """Requests-like session that answers from archived files (rebuild, demo, tests).

    `failures` maps an archive file name to status codes returned before the
    file is served (-1 = connection error).
    """

    def __init__(self, directory: Path, failures: dict[str, list[int]] | None = None):
        self.directory = Path(directory)
        self.failures = {k: list(v) for k, v in (failures or {}).items()}
        self.headers: dict = {}
        self.calls: list[str] = []

    def get(self, url: str, timeout: float | None = None):
        name = raw_name(url)
        self.calls.append(name)
        queue = self.failures.get(name)
        if queue:
            status = queue.pop(0)
            if status == -1:
                raise requests.ConnectionError("simulated connection reset")
            return _FakeResponse(status, "")
        path = self.directory / name
        if not path.exists():
            return _FakeResponse(404, "")
        return _FakeResponse(200, path.read_text(encoding="utf-8"))


class _FakeResponse:
    def __init__(self, status: int, text: str):
        self.status_code = status
        self.text = text
        self.headers: dict = {}
