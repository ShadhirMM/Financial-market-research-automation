import itertools

import pytest
import requests

from market_research.config import DEFAULT_CONFIG, ConfigError, load_config
from market_research.http_client import FetchError, HttpClient, ReplaySession, raw_name
from market_research.sources import ECB_URL, FRED_URL, TREASURY_URL

from conftest import RAW


# ---------- config ----------

def test_default_config_loads(config):
    assert len(config.series) == 16 and len(config.checks) == 9
    assert config.get("DCOILBRENTEU").stale_business_days == 10
    assert config.get("SP500").stale_business_days is None
    assert config.ai_enabled is False and "Mozilla" not in config.user_agent


@pytest.mark.parametrize("old,new,msg", [
    ("requests_per_second = 2", "requests_per_second = 50", "at most 5"),
    ("history_days = 800", "history_days = 100", "at least 400"),
    ('source = "fred"', 'source = "yahoo"', "source must be"),
    ('change = "pct"', 'change = "log"', "change must be"),
    ('window = "1W"', 'window = "2W"', "window must be"),
    ("watch = 25\nalert = 35", "watch = 25\nalert = 15", "beyond the watch"),
    ('"2 Yr", "3 Yr"', '"3 Yr"', "2 Yr"),
    ('series = "VIXCLS"', 'series = "NOPE"', "unknown series"),
    ('id = "NASDAQCOM"', 'id = "SP500"', "unique"),
])
def test_bad_config_is_rejected(tmp_path, old, new, msg):
    text = DEFAULT_CONFIG.read_text(encoding="utf-8")
    assert old in text, old
    bad = tmp_path / "c.toml"
    bad.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ConfigError, match=msg):
        load_config(bad, env={})


def test_missing_and_invalid_toml(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml", env={})
    (tmp_path / "x.toml").write_text("[run\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(tmp_path / "x.toml", env={})


def test_secrets_come_from_environment():
    cfg = load_config(DEFAULT_CONFIG, env={"STATUS_WEBHOOK_URL": "https://hooks.example/x", "ANTHROPIC_API_KEY": "k"})
    assert cfg.status_webhook == "https://hooks.example/x" and cfg.anthropic_key_set


# ---------- HTTP ----------

class FakeResp:
    def __init__(self, status, text="a,b\n", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


class FakeSession:
    def __init__(self, script):
        self.script, self.headers = list(script), {}

    def get(self, url, timeout=None):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def client(script, **kw):
    sleeps = []
    ticks = itertools.count(step=100)  # time moves on, so only back-off sleeps are recorded
    c = HttpClient("test-agent/1.0", session=FakeSession(script), sleep=sleeps.append, clock=lambda: next(ticks), **kw)
    return c, sleeps


def test_retries_temporary_errors_then_succeeds():
    c, sleeps = client([FakeResp(429), FakeResp(503), FakeResp(200, "ok,1\n")], backoff=(2, 10, 30))
    assert c.get_text("https://x.example/a") == "ok,1\n"
    assert sleeps == [2, 10] and c.stats == {"requests": 3, "retries": 2, "failures": 0}


def test_honours_retry_after_and_retries_network_errors():
    c, sleeps = client([FakeResp(429, headers={"Retry-After": "7"}), requests.ConnectionError("x"), requests.Timeout("y"),
                        FakeResp(200)])
    c.get_text("https://x.example/a")
    assert sleeps == [7.0, 10, 30]


def test_gives_up_after_max_retries():
    c, sleeps = client([FakeResp(503)] * 4, max_retries=3)
    with pytest.raises(FetchError) as e:
        c.get_text("https://x.example/a")
    assert e.value.attempts == 4 and e.value.temporary and len(sleeps) == 3


@pytest.mark.parametrize("status", [400, 403, 404])
def test_permanent_errors_are_not_retried(status):
    c, sleeps = client([FakeResp(status)])
    with pytest.raises(FetchError, match=f"HTTP {status}") as e:
        c.get_text("https://x.example/a")
    assert e.value.attempts == 1 and sleeps == []


def test_html_bot_page_with_status_200_is_an_error():
    c, _ = client([FakeResp(200, "<!DOCTYPE html><html><body>checking your browser</body></html>")])
    with pytest.raises(FetchError, match="HTML page"):
        c.get_text("https://x.example/a")


def test_rate_limit_is_per_host():
    t = [0.0]
    sleeps = []
    c = HttpClient("t", session=FakeSession([FakeResp(200)] * 3), requests_per_second=2,
                   sleep=lambda s: (sleeps.append(round(s, 3)), t.__setitem__(0, t[0] + s)), clock=lambda: t[0])
    c.get_text("https://a.example/1")
    c.get_text("https://b.example/1")  # other host: no wait
    c.get_text("https://a.example/2")  # same host: wait 0.5 s
    assert sleeps == [0.5]


def test_raw_names_ignore_dates_so_rebuild_finds_the_file(tmp_path):
    assert raw_name(FRED_URL.format(id="DGS10", start="2024-01-01")) == "fred_DGS10.csv"
    assert raw_name(TREASURY_URL.format(year=2026)) == "treasury_2026.csv"
    assert raw_name(ECB_URL.format(ccys="USD+GBP", start="2024-01-01")) == "ecb_EXR.csv"
    c, _ = client([FakeResp(200, "observation_date,DGS10\n")], archive_dir=tmp_path)
    c.get_text(FRED_URL.format(id="DGS10", start="2020-01-01"))
    assert (tmp_path / "fred_DGS10.csv").read_text() == "observation_date,DGS10\n"


def test_replay_session():
    s = ReplaySession(RAW, {"fred_SP500.csv": [503, -1]})
    url = FRED_URL.format(id="SP500", start="x")
    assert s.get(url).status_code == 503
    with pytest.raises(requests.ConnectionError):
        s.get(url)
    assert s.get(url).status_code == 200
    assert s.get(FRED_URL.format(id="NOPE", start="x")).status_code == 404


def test_public_sample_config_is_in_sync_and_has_no_restricted_series():
    import importlib.util
    from pathlib import Path

    from market_research.config import PROJECT_ROOT
    spec = importlib.util.spec_from_file_location("mpc", PROJECT_ROOT / "tools" / "make_public_config.py")
    mpc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mpc)
    built = mpc.build(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    on_disk = Path(PROJECT_ROOT / "config" / "public-sample.toml").read_text(encoding="utf-8")
    assert built == on_disk.replace("\r\n", "\n"), "run python tools/make_public_config.py"
    cfg = load_config(PROJECT_ROOT / "config" / "public-sample.toml", env={})
    assert not {s.id for s in cfg.series} & mpc.RESTRICTED
    assert len(cfg.series) == 11 and len(cfg.checks) == 5
