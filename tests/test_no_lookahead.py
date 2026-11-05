"""Network tests: every dated MCP tool, called for a past as_of, must not reveal later information.

Run with:  uv run pytest -m network
"""

import re
from datetime import date, timedelta

import pytest

from mcp_server import server as s
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.asof import results_public_on, today_ist

pytestmark = pytest.mark.network

DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
CASES = [("RELIANCE", "2024-10-01"), ("INFY", "2025-02-03"), ("HDFCBANK", "2026-08-10")]


def dates_in(text: str) -> list[date]:
    # Skip link URLs, which can contain unrelated digits.
    body = "\n".join(line.split(" | http")[0] for line in text.splitlines())
    return [date.fromisoformat(m) for m in DATE_RE.findall(body)]


def assert_fenced(text: str, as_of: date):
    later = [d for d in dates_in(text) if d > as_of]
    assert not later, f"dates after as_of {as_of}: {sorted(set(later))[:5]}\n{text[:600]}"


@pytest.mark.parametrize("symbol,as_of", CASES)
def test_price_tools_fenced(symbol, as_of):
    d = date.fromisoformat(as_of)
    for out in (s.get_price_history(symbol, as_of, 60), s.get_indicators(symbol, as_of, "rsi_14,macd,atr_14", 30),
                s.get_market_snapshot(symbol, as_of), s.get_corporate_actions(symbol, as_of)):
        assert_fenced(out, d)
        assert f"as_of={as_of}" in out


@pytest.mark.parametrize("symbol,as_of", CASES)
@pytest.mark.parametrize("kind,freq", [("income", "quarterly"), ("income", "annual"), ("balance", "quarterly"), ("cashflow", "annual")])
def test_financials_respect_sebi_deadline(symbol, as_of, kind, freq):
    d = date.fromisoformat(as_of)
    out = s.get_financials(symbol, as_of, kind, freq)
    header_line = out.splitlines()[0]
    m = re.search(r"data_through=(\d{4}-\d{2}-\d{2})", header_line)
    if m:
        through = date.fromisoformat(m.group(1))
        assert results_public_on(through, annual=(freq == "annual")) <= d


@pytest.mark.parametrize("symbol,as_of", CASES)
def test_news_fenced(symbol, as_of):
    d = date.fromisoformat(as_of)
    assert_fenced(s.get_company_news(symbol, as_of, 7), d)


def test_market_tools_fenced():
    as_of = "2024-10-01"
    d = date.fromisoformat(as_of)
    assert_fenced(s.get_market_news(as_of, 3), d)
    ctx = s.get_market_context(as_of)
    assert_fenced(ctx, d)
    # instruments that close after the NSE must stop the day before
    for line in ctx.splitlines():
        if line.startswith(("USD/INR", "Brent", "US 10Y")):
            assert date.fromisoformat(line.split(",")[2]) < d


def test_reliance_bonus_restored():
    """RELIANCE 1:1 bonus (ex 2024-10-28): the 2024-10-01 close must be the pre-bonus quote (~2930)."""
    snap = s.get_market_snapshot("RELIANCE", "2024-10-01")
    close = float(re.search(r"close (\d+\.\d+)", snap).group(1))
    assert 2800 < close < 3100
    later = s.get_market_snapshot("RELIANCE", "2024-11-04")
    assert 1200 < float(re.search(r"close (\d+\.\d+)", later).group(1)) < 1500


def test_reliance_eps_restored():
    out = s.get_financials("RELIANCE", "2024-10-01", "income", "annual")
    row = next(line for line in out.splitlines() if line.startswith("Basic EPS"))
    assert float(row.split(",")[1]) == pytest.approx(102.9, abs=0.5)  # FY24 reported EPS, pre-bonus


def test_summary_is_live_only():
    with pytest.raises(ToolError, match="live-only"):
        s.get_fundamentals_summary("RELIANCE", (today_ist() - timedelta(days=1)).isoformat())


def test_future_as_of_refused():
    with pytest.raises(ToolError, match="future"):
        s.get_price_history("RELIANCE", (today_ist() + timedelta(days=1)).isoformat())


def test_all_nifty50_resolve_on_yahoo():
    as_of = (today_ist() - timedelta(days=7)).isoformat()
    missing = []
    for row in s.symbols.nifty50():
        out = s.get_price_history(row["symbol"], as_of, 10)
        if "data_through=no data" in out or out.rstrip().endswith("(no rows)"):
            missing.append(row["symbol"])
    assert not missing, f"no Yahoo prices for {missing}"


def test_bad_symbol_message():
    with pytest.raises(ToolError, match="not a valid NSE symbol"):
        s.get_price_history("../etc", "2024-10-01")
