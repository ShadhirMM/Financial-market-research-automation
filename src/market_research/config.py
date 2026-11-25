"""Load and check config/config.toml (+ environment variables)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "config.toml"

SOURCES = {"fred", "ecb", "treasury"}
ECB_DERIVED = {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCNY"}
WINDOWS = ("1W", "1M", "3M", "YTD", "1Y")
CHECK_TYPES = {"level", "change", "drawdown", "curve"}
DIRECTIONS = {"above", "below", "abs"}


class ConfigError(ValueError):
    """The configuration is invalid; the run cannot start."""


@dataclass(frozen=True)
class SeriesDef:
    id: str
    source: str
    label: str
    category: str
    unit: str
    change: str  # "pct" | "bps"
    valid_min: float
    valid_max: float
    max_jump: float
    stale_business_days: int | None = None  # overrides [validation] for slow-publishing series


@dataclass(frozen=True)
class CheckDef:
    name: str
    series: str
    type: str
    direction: str
    watch: float
    alert: float
    why: str
    window: str | None = None


@dataclass(frozen=True)
class Config:
    history_days: int
    user_agent: str
    requests_per_second: float
    timeout_seconds: float
    max_retries: int
    backoff_seconds: tuple[float, ...]
    reports_dir: Path
    raw_dir: Path
    logs_dir: Path
    keep_raw_days: int
    keep_reports: int
    chart_days: int
    stale_business_days: int
    max_gap_business_days: int
    curve_consistency_bps: float
    series: tuple[SeriesDef, ...]
    tenors: tuple[str, ...]
    checks: tuple[CheckDef, ...]
    ai_enabled: bool = False
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "low"
    status_webhook: str | None = None
    anthropic_key_set: bool = False

    def get(self, series_id: str) -> SeriesDef:
        for s in self.series:
            if s.id == series_id:
                return s
        raise KeyError(series_id)


def _resolve(base: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else base / p


def _check_rule(direction: str, watch: float, alert: float) -> bool:
    """WATCH must be reached before ALERT in the rule's direction."""
    if direction == "below":
        return alert <= watch
    return alert >= watch


def load_config(path: Path | str = DEFAULT_CONFIG, *, env: dict | None = None, base_dir: Path | None = None) -> Config:
    env = os.environ if env is None else env
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Config file is not valid TOML: {exc}") from exc

    base = base_dir or PROJECT_ROOT
    run, h, o, v, ai = (raw.get(k, {}) for k in ("run", "http", "output", "validation", "ai"))
    errors: list[str] = []

    rps = h.get("requests_per_second", 2)
    if not isinstance(rps, (int, float)) or not 0 < rps <= 5:
        errors.append("http.requests_per_second must be above 0 and at most 5")
    retries = h.get("max_retries", 3)
    backoff = tuple(h.get("backoff_seconds", [2, 10, 30]))
    if not isinstance(retries, int) or retries < 0:
        errors.append("http.max_retries must be a non-negative integer")
    elif len(backoff) < retries:
        errors.append("http.backoff_seconds needs one value per retry")
    history = run.get("history_days", 800)
    if not isinstance(history, int) or history < 400:
        errors.append("run.history_days must be an integer of at least 400 (1-year changes and 52-week ranges)")
    ua = str(h.get("user_agent", "")).strip()
    if not ua:
        errors.append("http.user_agent must not be empty")

    series: list[SeriesDef] = []
    for i, s in enumerate(raw.get("series", [])):
        try:
            sd = SeriesDef(id=s["id"], source=s["source"], label=s.get("label", s["id"]), category=s.get("category", "Other"),
                           unit=s.get("unit", ""), change=s.get("change", "pct"), valid_min=float(s["valid_min"]),
                           valid_max=float(s["valid_max"]), max_jump=float(s["max_jump"]),
                           stale_business_days=s.get("stale_business_days"))
        except KeyError as exc:
            errors.append(f"series[{i}] is missing {exc}")
            continue
        if sd.source not in SOURCES:
            errors.append(f"series {sd.id}: source must be one of {sorted(SOURCES)}")
        if sd.change not in ("pct", "bps"):
            errors.append(f"series {sd.id}: change must be 'pct' or 'bps'")
        if sd.valid_min >= sd.valid_max:
            errors.append(f"series {sd.id}: valid_min must be below valid_max")
        if sd.source == "ecb" and sd.id not in ECB_DERIVED:
            errors.append(f"series {sd.id}: ECB series must be one of {sorted(ECB_DERIVED)}")
        series.append(sd)
    ids = [s.id for s in series]
    if not series:
        errors.append("at least one [[series]] is required")
    if len(set(ids)) != len(ids):
        errors.append("series ids must be unique")

    tenors = tuple(raw.get("treasury", {}).get("tenors", []))
    for needed in ("2 Yr", "10 Yr"):
        if needed not in tenors:
            errors.append(f"treasury.tenors must include '{needed}' (2s10s)")

    checks: list[CheckDef] = []
    for i, c in enumerate(raw.get("checks", [])):
        try:
            cd = CheckDef(name=c["name"], series=c["series"], type=c["type"], direction=c["direction"],
                          watch=float(c["watch"]), alert=float(c["alert"]), why=c.get("why", ""), window=c.get("window"))
        except KeyError as exc:
            errors.append(f"checks[{i}] is missing {exc}")
            continue
        if cd.type not in CHECK_TYPES:
            errors.append(f"check '{cd.name}': type must be one of {sorted(CHECK_TYPES)}")
        if cd.direction not in DIRECTIONS:
            errors.append(f"check '{cd.name}': direction must be one of {sorted(DIRECTIONS)}")
        if cd.type == "change" and cd.window not in WINDOWS:
            errors.append(f"check '{cd.name}': window must be one of {WINDOWS}")
        if cd.type != "curve" and cd.series not in ids:
            errors.append(f"check '{cd.name}': unknown series {cd.series}")
        if not _check_rule(cd.direction, cd.watch, cd.alert):
            errors.append(f"check '{cd.name}': alert threshold must be beyond the watch threshold")
        checks.append(cd)

    if errors:
        raise ConfigError("; ".join(errors))

    return Config(
        history_days=history, user_agent=ua, requests_per_second=float(rps),
        timeout_seconds=float(h.get("timeout_seconds", 30)), max_retries=retries,
        backoff_seconds=tuple(float(b) for b in backoff),
        reports_dir=_resolve(base, o.get("reports_dir", "reports")), raw_dir=_resolve(base, o.get("raw_dir", "data/raw")),
        logs_dir=_resolve(base, o.get("logs_dir", "logs")), keep_raw_days=int(o.get("keep_raw_days", 90)),
        keep_reports=int(o.get("keep_reports", 52)), chart_days=int(o.get("chart_days", 365)),
        stale_business_days=int(v.get("stale_business_days", 5)), max_gap_business_days=int(v.get("max_gap_business_days", 7)),
        curve_consistency_bps=float(v.get("curve_consistency_bps", 10)),
        series=tuple(series), tenors=tenors, checks=tuple(checks),
        ai_enabled=bool(ai.get("enabled", False)), ai_model=str(ai.get("model", "claude-opus-5-5")),
        ai_effort=str(ai.get("effort", "low")),
        status_webhook=env.get("STATUS_WEBHOOK_URL") or None,
        anthropic_key_set=bool(env.get("ANTHROPIC_API_KEY")),
    )


def load_dotenv(path: Path | str = PROJECT_ROOT / ".env") -> None:
    """Minimal .env loader (KEY=value). Existing environment variables win."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
