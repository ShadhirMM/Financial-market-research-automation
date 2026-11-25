"""Excel workbook (openpyxl) with native Excel charts.

Sheets: README · Dashboard · Signals · Curve · Equities · Rates · Volatility & Credit · Commodities · FX · Data_Quality · Run_Log
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.chart.axis import DateAxis
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF")
FILLS = {
    "ALERT": PatternFill("solid", fgColor="F8CBAD"), "ERROR": PatternFill("solid", fgColor="F8CBAD"),
    "WATCH": PatternFill("solid", fgColor="FFE699"), "WARNING": PatternFill("solid", fgColor="FFE699"),
    "OK": PatternFill("solid", fgColor="C6EFCE"),
}
NUM = "#,##0.00"
PCT1 = '+0.0"%";-0.0"%";0.0"%"'
BPS = '+0" bp";-0" bp";0" bp"'
DATE = "yyyy-mm-dd"

CHART_SHEETS = [  # (sheet, categories, chart title, y-axis, rebase)
    ("Equities", ("Equities",), "Equity indices", "Index", True),
    ("Rates", ("Rates",), "US rates", "%", False),
    ("Volatility & Credit", ("Volatility", "Credit"), "VIX and high-yield spread (%)", "Level", False),
    ("Commodities", ("Commodities",), "Crude oil", "USD/bbl", False),
    ("FX", ("FX",), "FX (USD crosses from ECB reference rates)", "Rate", True),
]

METHOD = [
    ("Sources", "FRED (Federal Reserve Bank of St. Louis), U.S. Department of the Treasury daily par yield curve, "
                "European Central Bank euro reference rates. Official public data, no API keys."),
    ("Changes", "Latest value versus the last observation on or before the window start (1W = 7 days, 1M/3M/1Y = calendar "
                "months, YTD = last value of the previous year). Levels in %, rates and spreads in basis points (bp)."),
    ("Volatility", "Annualised: standard deviation of daily log returns × √252 (levels, in %) or of daily changes × √252 (rates, in bp), "
                   "over the last 252 observations."),
    ("From 52w high", "Levels: % below the 52-week high. Rates/spreads: bp below the 52-week high."),
    ("FX crosses", "Derived from ECB rates quoted per EUR on the same day: GBPUSD = USD/EUR ÷ GBP/EUR; USDJPY = JPY/EUR ÷ USD/EUR, etc."),
    ("Cleaning", "Duplicates: last value kept. Missing values ('' or '.') dropped. Values outside each series' valid range are "
                 "excluded and listed in Data_Quality. Holidays stay as gaps (no forward-fill)."),
    ("Signals", "Rule-based research checks from config/config.toml. OK / WATCH / ALERT with the reason."),
    ("Rebuild", "Each run archives the raw downloads. `python -m market_research rebuild --raw data/raw/<run>` re-creates this file offline."),
    ("Disclaimer", "Public data for research. Not investment advice."),
]


def _header(ws: Worksheet, row: int, headers: list[str]) -> None:
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=i, value=h)
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(wrap_text=True, vertical="center")


def _table(ws: Worksheet, columns: list[tuple[str, str, str | None]], rows: list[dict], start_row: int = 1,
           status_key: str | None = None) -> int:
    _header(ws, start_row, [h for _, h, _ in columns])
    r = start_row
    for row in rows:
        r += 1
        for i, (key, _, fmt) in enumerate(columns, start=1):
            c = ws.cell(row=r, column=i, value=row.get(key))
            if fmt:
                fmt_value = fmt(row) if callable(fmt) else fmt
                c.number_format = fmt_value
            if status_key and key == status_key and row.get(key) in FILLS:
                c.fill = FILLS[row[key]]
    for i, (key, h, _) in enumerate(columns, start=1):
        longest = max([len(h)] + [len(str(x.get(key) or "")) for x in rows[:200]])
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, longest + 2), 70)
    return r


def _chg_fmt(row: dict) -> str:
    return BPS if row.get("change_kind") == "bps" else PCT1


def _series_sheet(wb: Workbook, name: str, defs: list, clean: dict, chart_days: int, as_of: date, title: str,
                  y_title: str, rebase: bool) -> None:
    """Date × series table for the last `chart_days`, plus a native line chart.
    rebase=True also writes each series rebased to 100 at the first date and charts those,
    so series with very different levels (e.g. EURUSD 1.1 and USDJPY 150) share one chart."""
    ws = wb.create_sheet(name)
    defs = [d for d in defs if clean.get(d.id)]
    _header(ws, 1, ["Date"] + [d.label for d in defs])
    start = date.fromordinal(as_of.toordinal() - chart_days)
    lookup = {d.id: dict(clean[d.id]) for d in defs}
    dates = sorted({x for d in defs for x, _ in clean[d.id] if x >= start})
    first = {d.id: next((lookup[d.id][x] for x in dates if x in lookup[d.id]), None) for d in defs}
    reb_col = len(defs) + 3
    if rebase:
        for j, d in enumerate(defs):
            c = ws.cell(row=1, column=reb_col + j, value=f"{d.id} (rebased = 100)")
            c.fill, c.font = HEADER_FILL, HEADER_FONT
    for i, x in enumerate(dates, start=2):
        ws.cell(row=i, column=1, value=x).number_format = DATE
        for j, d in enumerate(defs, start=2):
            v = lookup[d.id].get(x)
            if v is None:
                continue
            ws.cell(row=i, column=j, value=v).number_format = NUM
            if rebase and first[d.id]:
                ws.cell(row=i, column=reb_col + j - 2, value=v / first[d.id] * 100).number_format = "0.0"
    ws.column_dimensions["A"].width = 12
    for j in range(2, reb_col + len(defs)):
        ws.column_dimensions[get_column_letter(j)].width = 16
    ws.freeze_panes = "B2"
    if not defs or not dates:
        return
    chart = LineChart()
    chart.title = title + (" (rebased to 100)" if rebase else "")
    chart.y_axis.title = "Index (start = 100)" if rebase else y_title
    chart.height, chart.width = 9, 22
    chart.display_blanks = "span"  # holidays don't break the lines
    lo, hi = (reb_col, reb_col + len(defs) - 1) if rebase else (2, len(defs) + 1)
    chart.add_data(Reference(ws, min_col=lo, max_col=hi, min_row=1, max_row=len(dates) + 1), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=len(dates) + 1))
    chart.x_axis = DateAxis(crossAx=100)
    chart.x_axis.number_format, chart.x_axis.majorTimeUnit = "mmm-yy", "months"
    ws.add_chart(chart, f"{get_column_letter(reb_col + len(defs) + 1)}2")


def build_workbook(ds: dict, path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "README"
    run = ds["run"]
    ws["A1"] = ds["title"]
    ws["A1"].font = Font(bold=True, size=14)
    r = 2
    if ds.get("demo"):
        ws["A2"] = "DEMO DATA: synthetic series in the real source formats. Not market data."
        ws["A2"].font = Font(bold=True, color="C00000")
        r = 3
    for k, v in [("Data as of", run["as_of"]), ("Generated (UTC)", run["finished_at"]), ("Run ID", run["run_id"]),
                 ("Run status", run["status"]), ("Series collected", f'{run["series_collected"]}/{run["series_requested"]}'),
                 ("Signals", f'{run["signals"].get("ALERT", 0)} ALERT, {run["signals"].get("WATCH", 0)} WATCH'),
                 ("Data issues", f'{run["errors"]} error(s), {run["warnings"]} warning(s)')]:
        r += 1
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        ws.cell(row=r, column=2, value=v)
    r += 2
    ws.cell(row=r, column=1, value="Method").font = Font(bold=True, size=12)
    for k, v in METHOD:
        r += 1
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        ws.cell(row=r, column=2, value=v).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 20, 120

    # Dashboard: AI summary (if any), signals, key table
    ws = wb.create_sheet("Dashboard")
    ws["A1"] = f"Market & macro dashboard: data as of {run['as_of']}"
    ws["A1"].font = Font(bold=True, size=14)
    row = 3
    if ds.get("ai_summary"):
        ws.cell(row=row, column=1, value="Summary (AI-written from the numbers below; every figure checked)").font = Font(bold=True)
        row += 1
        ws.cell(row=row, column=1, value=ds["ai_summary"]["headline"]).font = Font(italic=True)
        for p in ds["ai_summary"]["points"]:
            row += 1
            ws.cell(row=row, column=1, value=f"• {p['text']}")
        row += 2
    ws.cell(row=row, column=1, value="Signals").font = Font(bold=True, size=12)
    row = _table(ws, [("status", "Status", None), ("check", "Check", None), ("explanation", "Explanation", None)],
                 ds["signals"], start_row=row + 1, status_key="status") + 2
    ws.cell(row=row, column=1, value="Key figures").font = Font(bold=True, size=12)
    key_cols = [("label", "Series", None), ("category", "Category", None), ("latest", "Latest", NUM), ("date", "As of", DATE),
                ("chg_1W", "1W", _chg_fmt), ("chg_1M", "1M", _chg_fmt), ("chg_3M", "3M", _chg_fmt), ("chg_YTD", "YTD", _chg_fmt),
                ("chg_1Y", "1Y", _chg_fmt), ("vol_1y", "Volatility 1Y (ann.)", lambda r: BPS if r.get("change_kind") == "bps" else '0.0"%"'),
                ("high_52w", "52w high", NUM), ("low_52w", "52w low", NUM), ("from_high", "From 52w high", _chg_fmt),
                ("max_drawdown_1y", "Max drawdown 1Y", PCT1), ("quality", "Quality", None)]
    _table(ws, key_cols, ds["summaries"], start_row=row + 1, status_key="quality")
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["C"].width = 90 if ds["signals"] else 14

    ws = wb.create_sheet("Signals")
    _table(ws, [("status", "Status", None), ("check", "Check", None), ("series", "Series", None),
                ("value", "Value", lambda r: BPS if r.get("unit") == "bp" else PCT1 if r.get("unit") == "%" else NUM),
                ("rule", "Rule", None), ("explanation", "Explanation", None), ("why", "Why it matters", None)],
           ds["signals"], status_key="status")
    ws.freeze_panes = "A2"

    # Curve
    ws = wb.create_sheet("Curve")
    curve = ds.get("curve")
    if curve:
        d = curve["dates"]
        heads = ["Tenor"] + [f"{k} ({v})" if v else k for k, v in d.items()]
        _header(ws, 1, heads)
        for i, row_ in enumerate(curve["rows"], start=2):
            ws.cell(row=i, column=1, value=row_["tenor"])
            for j, k in enumerate(d, start=2):
                if row_.get(k) is not None:
                    ws.cell(row=i, column=j, value=row_[k]).number_format = NUM
        n = len(curve["rows"])
        sp_row = n + 3
        ws.cell(row=sp_row, column=1, value="2s10s (bp)").font = Font(bold=True)
        for j, k in enumerate(d, start=2):
            v = curve["spread_2s10s_bps"].get(k)
            if v is not None:
                ws.cell(row=sp_row, column=j, value=v).number_format = BPS
        for j in range(1, 5):
            ws.column_dimensions[get_column_letter(j)].width = 22
        chart = LineChart()
        chart.title, chart.y_axis.title, chart.x_axis.title = "US Treasury par yield curve", "%", "Tenor"
        chart.height, chart.width = 9, 20
        chart.add_data(Reference(ws, min_col=2, max_col=len(d) + 1, min_row=1, max_row=n + 1), titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=n + 1))
        ws.add_chart(chart, "F2")

    defs = ds["series_defs"]
    for name, cats, title, y, rebase in CHART_SHEETS:
        _series_sheet(wb, name, [s for s in defs if s.category in cats], ds["clean"], ds["chart_days"],
                      date.fromisoformat(run["as_of"]), title, y, rebase)

    ws = wb.create_sheet("Data_Quality")
    _table(ws, [("severity", "Severity", None), ("series", "Series", None), ("date", "Date", None), ("rule", "Rule", None),
                ("message", "Message", None)], ds["issues"], status_key="severity")
    ws.freeze_panes = "A2"

    ws = wb.create_sheet("Run_Log")
    _table(ws, [("time", "Time (UTC)", None), ("level", "Level", None), ("message", "Message", None)], ds["run_log"])

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(path)  # atomic
    return path
