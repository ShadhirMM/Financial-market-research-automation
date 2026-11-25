"""Optional AI summary (off by default).

Claude receives ONLY the computed facts table and signals, never raw data, and
returns a short structured summary. Before the summary is used, every number in
it is checked against the numbers in the facts that were sent. If Claude writes
any number that is not in the facts, the summary is rejected and the report is
produced without it. The AI can phrase things; it cannot invent figures.
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["headline", "points"],
    "properties": {
        "headline": {"type": "string"},
        "points": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False, "required": ["text"],
                      "properties": {"text": {"type": "string"}}},
        },
    },
}

SYSTEM = (
    "You write the weekly market summary for the IT/research team of a private family office. "
    "You receive a table of computed market facts and rule-based signals. Write a one-sentence headline and "
    "3 to 6 short points in plain English for a busy reader: what moved, what the signals mean, what to watch. "
    "Use only numbers that appear in the facts, written exactly as they appear there (same decimals and units). "
    "Do not calculate new numbers, do not round differently, do not forecast prices, and do not give investment advice."
)

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[float]:
    out = set()
    for tok in _NUMBER.findall(text):
        try:
            out.add(float(tok.replace(",", "")))
        except ValueError:
            continue
    return out


def facts_text(summaries: list[dict], signals: list[dict], curve: dict | None) -> str:
    lines = ["MARKET FACTS (as computed by the program)"]
    for s in summaries:
        if s.get("latest") is None:
            continue
        unit = " bp" if s["change_kind"] == "bps" else "%"
        parts = [f"{s['label']} ({s['id']}): latest {s['latest']:,.2f} on {s['date']}"]
        for w in ("1W", "1M", "YTD", "1Y"):
            v = s.get(f"chg_{w}")
            if v is not None:
                parts.append(f"{w} {v:+.0f}{unit}" if unit == " bp" else f"{w} {v:+.1f}{unit}")
        lines.append("; ".join(parts))
    if curve:
        sp = curve["spread_2s10s_bps"]
        if sp.get("today") is not None:
            lines.append(f"Treasury 2s10s spread: {sp['today']:+.0f} bp today"
                         + (f", {sp['1Y ago']:+.0f} bp one year ago" if sp.get("1Y ago") is not None else ""))
    lines.append("SIGNALS")
    for g in signals:
        lines.append(f"[{g['status']}] {g['check']}: {g['explanation']}")
    return "\n".join(lines)


def verify_numbers(summary: dict, facts: str) -> list[float]:
    """Numbers used in the summary that do not appear in the facts (must be empty)."""
    allowed = numbers_in(facts)
    used = numbers_in(summary["headline"] + " " + " ".join(p["text"] for p in summary["points"]))
    return sorted(n for n in used if n not in allowed)


def summarise(facts: str, model: str, effort: str, client=None) -> dict:
    """Call Claude with structured output. Raises RuntimeError when the reply cannot be used."""
    if client is None:
        from anthropic import Anthropic  # optional dependency: pip install -e ".[ai]"
        client = Anthropic(max_retries=2, timeout=120)
    response = client.beta.messages.create(
        model=model,
        max_tokens=4096,
        betas=[FALLBACK_BETA],
        fallbacks="default",  # if the model declines, the API retries on a fallback model in the same call
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": facts}],
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"AI summary unavailable (stop_reason={response.stop_reason})")
    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    try:
        summary = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI summary was not valid JSON: {exc}") from exc
    unknown = verify_numbers(summary, facts)
    if unknown:
        raise RuntimeError(f"AI summary rejected: numbers not in the facts {unknown}")
    return summary
