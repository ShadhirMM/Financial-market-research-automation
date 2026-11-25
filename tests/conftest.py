from datetime import date
from pathlib import Path

import pytest

from market_research.config import DEFAULT_CONFIG, SeriesDef, load_config

RAW = Path(__file__).parent / "fixtures" / "raw"
AS_OF = date(2026, 11, 25)


@pytest.fixture
def config():
    return load_config(DEFAULT_CONFIG, env={})


@pytest.fixture
def tmp_config_file(tmp_path):
    """Copy of the real config with every output folder inside tmp_path."""
    text = DEFAULT_CONFIG.read_text(encoding="utf-8")
    for key, folder in (("reports_dir", "reports"), ("raw_dir", "raw"), ("logs_dir", "logs")):
        text = text.replace(f'{key} = "', f'{key} = "{(tmp_path / folder).as_posix()}/_', 1)
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def sd(change="pct", vmin=-1e9, vmax=1e9, jump=1e9, sid="X", stale=None):
    return SeriesDef(id=sid, source="fred", label=sid, category="Test", unit="", change=change,
                     valid_min=vmin, valid_max=vmax, max_jump=jump, stale_business_days=stale)
