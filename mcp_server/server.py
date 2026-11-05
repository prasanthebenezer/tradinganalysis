"""MCP server: point-in-time NSE data tools for the tradinganalysis agents.

Run:  uv run python -m mcp_server.server        (stdio, for Claude Code / Desktop)
"""

from __future__ import annotations

import functools
import urllib.error
from datetime import timedelta

import pandas as pd
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import fundamentals, indicators, market, news, symbols
from .asof import header, is_live, parse_as_of
from .prices import NoDataError, ohlcv_table, stock_bars

# Failures the agent should read and react to. Anything else is a bug and is logged as a crash.
_EXPECTED = (ValueError, LookupError)  # AsOfError, SymbolError, bad indicator/statement, NoDataError
_NETWORK = (urllib.error.URLError, ConnectionError, TimeoutError)

INSTRUCTIONS = """\
Point-in-time data for NSE-listed stocks (NIFTY 50 focus). Every dated tool needs as_of (YYYY-MM-DD,
India date). Nothing after the as_of close is ever returned, so analysis for a past date can't see
the future. Prices are as quoted on as_of (later splits/bonuses are undone). Results periods appear
only after the SEBI filing deadline (quarter end + 45 days, +60 for March/annual). Amounts are INR;
statement amounts are in ₹ crore. Use get_market_snapshot as the source of truth for any exact
price or indicator claim. Research only: this server cannot place orders."""

mcp = MCPServer("tradinganalysis-data", instructions=INSTRUCTIONS, version="0.1.0")
RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)


def expected_errors(fn):
    """Turn anticipated failures into ToolError so the model sees the reason, not a generic error."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _EXPECTED as exc:
            raise ToolError(str(exc)) from exc
        except _NETWORK as exc:
            raise ToolError(f"data source unavailable, try again later ({exc.__class__.__name__}: {exc})") from exc
    return wrapper


@mcp.tool(annotations=RO)
@expected_errors
def resolve_symbol(query: str) -> str:
    """Find an NSE symbol from a symbol or company name, e.g. 'infosys' or 'M&M'.

    Returns up to 5 matches with NSE symbol, company name, ISIN, Yahoo ticker and NIFTY 50 membership.
    """
    hits = symbols.search(query)
    if not hits:
        return f"No NSE equity matches {query!r}."
    return pd.DataFrame(hits)[["symbol", "name", "isin", "yahoo", "nifty50"]].to_csv(index=False)


@mcp.tool(annotations=RO)
@expected_errors
def list_nifty50() -> str:
    """The NIFTY 50 constituents used by this project (pinned copy of NSE's list), with industry and ISIN."""
    return pd.DataFrame(symbols.nifty50()).to_csv(index=False)


@mcp.tool(annotations=RO)
@expected_errors
def get_price_history(symbol: str, as_of: str, lookback_days: int = 90) -> str:
    """Daily OHLCV for an NSE stock for the lookback_days calendar days up to and including as_of.

    Prices are as quoted on as_of (INR). lookback_days is capped at 1100.
    """
    d = parse_as_of(as_of)
    b = stock_bars(symbol, d)
    start = d - timedelta(days=max(1, min(int(lookback_days), 1100)))
    df = b.df[pd.Index([pd.Timestamp(i).date() for i in b.df.index]) >= start]
    h = header("get_price_history", d, symbols.normalize(symbol), b.through, "Yahoo Finance", b.notes)
    return h + "\n" + (ohlcv_table(df) if not df.empty else "(no rows)")


@mcp.tool(annotations=RO)
@expected_errors
def get_indicators(symbol: str, as_of: str, indicators_csv: str = "rsi_14,macd,macd_signal,sma_50,sma_200", rows: int = 20) -> str:
    """Technical indicators for an NSE stock, computed on prices up to as_of; returns the last `rows` days.

    indicators_csv: comma-separated from sma_20, sma_50, sma_200, ema_10, ema_20, rsi_14, macd,
    macd_signal, macd_hist, bb_mid, bb_upper, bb_lower, atr_14, vwma_20.
    """
    d = parse_as_of(as_of)
    names = [n.strip().lower() for n in indicators_csv.split(",") if n.strip()]
    b = stock_bars(symbol, d)
    if b.df.empty:
        return header("get_indicators", d, symbol, None, "Yahoo Finance", b.notes)
    ind = indicators.compute(b.df, names)
    ind.insert(0, "Close", b.df["Close"])
    tail = ind.tail(max(1, min(int(rows), 250))).round(2)
    tail.index = [pd.Timestamp(i).date().isoformat() for i in tail.index]
    tail.index.name = "Date"
    h = header("get_indicators", d, symbols.normalize(symbol), b.through, "Yahoo Finance prices; computed locally", b.notes)
    return h + "\n" + tail.to_csv()


@mcp.tool(annotations=RO)
@expected_errors
def get_market_snapshot(symbol: str, as_of: str) -> str:
    """Source-of-truth snapshot for exact claims: last bar on/before as_of, 52-week range, moving
    averages, RSI, MACD, Bollinger, ATR, distance from key levels, and the last 10 closes."""
    d = parse_as_of(as_of)
    b = stock_bars(symbol, d)
    sym = symbols.normalize(symbol)
    if b.df.empty:
        return header("get_market_snapshot", d, sym, None, "Yahoo Finance", b.notes)
    df = b.df
    names = ["sma_20", "sma_50", "sma_200", "ema_10", "rsi_14", "macd", "macd_signal", "macd_hist",
             "bb_upper", "bb_mid", "bb_lower", "atr_14", "vwma_20"]
    ind = indicators.compute(df, names).iloc[-1]
    last = df.iloc[-1]
    close = float(last["Close"])
    yr = df[pd.Index([pd.Timestamp(i).date() for i in df.index]) > b.through - timedelta(days=365)]
    lines = [
        header("get_market_snapshot", d, sym, b.through, "Yahoo Finance prices; indicators computed locally", b.notes),
        f"last_bar {b.through}: open {last['Open']:.2f} high {last['High']:.2f} low {last['Low']:.2f} "
        f"close {close:.2f} volume {int(last['Volume'])}" + (" (PARTIAL)" if b.partial_last_bar else ""),
        f"52w_high {yr['High'].max():.2f}  52w_low {yr['Low'].min():.2f}  "
        f"from_52w_high {(close / yr['High'].max() - 1) * 100:.2f}%",
        f"avg_volume_20d {int(df['Volume'].tail(20).mean())}",
    ]
    for n in names:
        v = ind[n]
        lines.append(f"{n} " + ("n/a (not enough history)" if pd.isna(v) else f"{v:.2f}"))
    for n in ("sma_50", "sma_200"):
        if not pd.isna(ind[n]):
            lines.append(f"close_vs_{n} {(close / ind[n] - 1) * 100:.2f}%")
    closes = df["Close"].tail(10)
    lines.append("last_10_closes " + ", ".join(f"{pd.Timestamp(i).date()}:{v:.2f}" for i, v in closes.items()))
    return "\n".join(lines)


@mcp.tool(annotations=RO)
@expected_errors
def get_financials(symbol: str, as_of: str, statement: str = "income", freq: str = "quarterly") -> str:
    """Income statement, balance sheet or cash flow (statement=income|balance|cashflow,
    freq=quarterly|annual) showing only periods whose results were public by as_of.

    Amounts in ₹ crore; per-share values in ₹. Indian companies file balance sheets half-yearly,
    so quarterly balance sheets have Sep/Mar periods only. Yahoo keeps ~5 quarters and ~5 years.
    """
    d = parse_as_of(as_of)
    df, notes = fundamentals.statement(symbol, statement.lower().strip(), freq.lower().strip(), d)
    through = max((pd.Timestamp(c).date() for c in df.columns), default=None) if not df.empty else None
    h = header("get_financials", d, f"{symbols.normalize(symbol)} {freq} {statement}", through, "Yahoo Finance", notes)
    return h + "\n" + (df.to_csv() if not df.empty else "(no public periods)")


@mcp.tool(annotations=RO)
@expected_errors
def get_fundamentals_summary(symbol: str, as_of: str) -> str:
    """Current valuation and quality ratios (P/E, P/B, ROE, margins, debt/equity, holdings).
    LIVE ONLY: works only when as_of is today in India, because Yahoo keeps no history of these."""
    d = parse_as_of(as_of)
    rows = fundamentals.summary(symbol, d)
    h = header("get_fundamentals_summary", d, symbols.normalize(symbol), d, "Yahoo Finance (live)",
               ["ratios as of now; growth figures compare the latest reported quarter with a year earlier"])
    return h + "\n" + "\n".join(f"{k}: {v}" for k, v in rows)


@mcp.tool(annotations=RO)
@expected_errors
def get_company_news(symbol: str, as_of: str, days: int = 7) -> str:
    """Headlines about the company from the `days` days up to as_of (max 30), newest first:
    date | source | title | link. Sources: Google News (India edition) and, for recent dates, Yahoo."""
    d = parse_as_of(as_of)
    items, notes = news.company_news(symbol, d, days)
    through = items[0].published.date() if items else None
    h = header("get_company_news", d, symbols.normalize(symbol), through, "Google News RSS; Yahoo Finance", notes)
    return h + "\n" + news.render(items)


@mcp.tool(annotations=RO)
@expected_errors
def get_market_news(as_of: str, days: int = 3) -> str:
    """Indian market and macro headlines (Sensex, Nifty, RBI, economy, FII flows) from the `days`
    days up to as_of (max 30), newest first."""
    d = parse_as_of(as_of)
    items, notes = news.market_news(d, days)
    through = items[0].published.date() if items else None
    return header("get_market_news", d, "India market", through, "Google News RSS", notes) + "\n" + news.render(items)


@mcp.tool(annotations=RO)
@expected_errors
def get_market_context(as_of: str) -> str:
    """Backdrop on as_of: NIFTY 50, NIFTY BANK, India VIX, USD/INR, Brent and US 10Y with 5- and
    20-trading-day % changes."""
    d = parse_as_of(as_of)
    df, notes = market.context(d)
    through = max((pd.Timestamp(x).date() for x in df["date"]), default=None) if not df.empty else None
    return header("get_market_context", d, "market", through, "Yahoo Finance", notes) + "\n" + (
        df.to_csv(index=False) if not df.empty else "(no data)")


@mcp.tool(annotations=RO)
@expected_errors
def get_corporate_actions(symbol: str, as_of: str) -> str:
    """Dividends (₹ per share, as quoted on as_of) and splits/bonuses on or before as_of."""
    d = parse_as_of(as_of)
    b = stock_bars(symbol, d)
    sym = symbols.normalize(symbol)
    if b.df.empty:
        return header("get_corporate_actions", d, sym, None, "Yahoo Finance", b.notes)
    acts = b.df[(b.df.get("Dividends", 0) > 0) | (b.df.get("Splits", 0) > 0)][["Dividends", "Splits"]]
    acts = acts.round(4)
    acts.index = [pd.Timestamp(i).date().isoformat() for i in acts.index]
    acts.index.name = "Date"
    notes = b.notes + ["Splits column is the ratio (2.0 = 1:1 bonus or 2-for-1 split); Yahoo records bonuses as splits"]
    through = pd.Timestamp(acts.index[-1]).date() if not acts.empty else None
    return header("get_corporate_actions", d, sym, through, "Yahoo Finance", notes) + "\n" + (
        acts.to_csv() if not acts.empty else "(none)")


@mcp.tool(annotations=RO)
@expected_errors
def get_mode(as_of: str) -> str:
    """Whether as_of is LIVE (today in India: live-only sources such as Zerodha Kite and
    get_fundamentals_summary may be used) or HISTORICAL (only this server's dated tools)."""
    d = parse_as_of(as_of)
    return "LIVE" if is_live(d) else "HISTORICAL"


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
