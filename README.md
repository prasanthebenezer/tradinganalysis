# tradinganalysis

Multi-agent equity research for NIFTY 50 stocks, built for Claude Code / Claude Desktop.
Inspired by [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (Apache-2.0).

Research and decision support only. Not financial advice. No order placement.

See [PLAN.md](PLAN.md) for architecture, data sources, phases and decisions.

## Status

| Phase | What | State |
|---|---|---|
| 1 | Point-in-time NSE data MCP server + look-ahead tests | done |
| 2 | 12 subagents + decision schemas | next |
| 3 | `/analyze SYMBOL DATE` skill | |
| 4 | Memory, settlement vs NIFTY 50, backtest | |
| 5 | HTML report | |

## Setup

Needs [uv](https://docs.astral.sh/uv/) (it installs Python 3.11+ and the dependencies).

```bash
git clone https://github.com/prasanthebenezer/tradinganalysis.git
cd tradinganalysis
uv sync
uv run pytest            # all tests (needs internet)
uv run pytest -m "not network"   # offline tests only
```

### Claude Code

`.mcp.json` registers the server as `tradinganalysis-data`. Open the repo folder in Claude Code,
approve the project MCP server when asked, then check with `/mcp`.

### Claude Desktop (chat)

Add to `claude_desktop_config.json` (Settings → Developer → Edit Config), with your own path:

```json
{
  "mcpServers": {
    "tradinganalysis-data": {
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\tradinganalysis", "run", "--quiet", "python", "-m", "mcp_server.server"]
    }
  }
}
```

## MCP tools (Phase 1)

Every dated tool takes `as_of` (YYYY-MM-DD, India date) and never returns information that was not
public by the NSE close that day.

| Tool | Returns |
|---|---|
| `get_mode(as_of)` | `LIVE` (today: Kite and live-only tools allowed) or `HISTORICAL` |
| `resolve_symbol(query)` | NSE symbol, name, ISIN, Yahoo ticker, NIFTY 50 flag |
| `list_nifty50()` | Pinned constituent list |
| `get_price_history(symbol, as_of, lookback_days)` | Daily OHLCV as quoted on as_of |
| `get_indicators(symbol, as_of, indicators_csv, rows)` | SMA/EMA, RSI, MACD, Bollinger, ATR, VWMA |
| `get_market_snapshot(symbol, as_of)` | Source-of-truth numbers for exact price/indicator claims |
| `get_financials(symbol, as_of, statement, freq)` | Income / balance / cash flow, ₹ crore, SEBI-deadline fenced |
| `get_fundamentals_summary(symbol, as_of)` | Valuation ratios, **live only** |
| `get_company_news(symbol, as_of, days)` | Headlines, newest first |
| `get_market_news(as_of, days)` | Sensex / Nifty / RBI / economy headlines |
| `get_market_context(as_of)` | NIFTY, BANKNIFTY, India VIX, USD/INR, Brent, US10Y |
| `get_corporate_actions(symbol, as_of)` | Dividends, splits/bonuses |

### Point-in-time rules

* **Prices**: Yahoo rewrites old prices after each split or bonus. The server undoes splits dated
  after `as_of`, so RELIANCE on 2024-10-01 shows ₹2,929.65, not the bonus-adjusted ₹1,464.82.
  Dividend adjustment is not applied (it would use future dividends).
* **Results**: Yahoo has no filing dates for Indian companies. A period counts as public only after
  the SEBI LODR Reg. 33 deadline: quarter end + 45 days, + 60 days for the March quarter / annual.
  EPS and share counts are restored to pre-split values the same way as prices.
* **Global prices** (USD/INR, Brent, US10Y) close after the NSE, so they stop the day before `as_of`.
* **Today before 15:30 IST**: the last bar is marked partial.
* **Valuation ratios** from Yahoo are current values only, so `get_fundamentals_summary` refuses past dates.
* **Zerodha Kite MCP** tools have no date limit: use them only when `get_mode` says `LIVE`.

### Known limits

* yfinance is an unofficial Yahoo client; fields and rate limits can change.
* Yahoo keeps about 5 quarters and 5 years of statements, with occasional missing quarters.
* Google News coverage of older dates is thin (a handful of headlines per week).
* The NIFTY 50 list is today's; backtests over past dates have survivorship bias.
