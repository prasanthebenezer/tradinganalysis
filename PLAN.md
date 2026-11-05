# tradinganalysis — India Trading Agents for Claude Code: Plan (Option C)

Multi-agent equity research for NSE/BSE stocks, modelled on
[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (Apache-2.0),
rebuilt as Claude Code-native pieces: an MCP data server, subagents, and a skill.
Research/decision support only — no order placement.

Status: PLAN AGREED 2026-11-05. Phase 1 to start on Claude Desktop (machine: EbenezerOne), where the Zerodha Kite MCP is connected.

---

## 1. What we keep from TradingAgents, and what changes

| TradingAgents (LangGraph, Python) | Our version (Claude Code) |
|---|---|
| 4 analysts in parallel (market, sentiment, news, fundamentals) | 4 subagents, launched in parallel by the skill |
| Bull/Bear debate, `max_debate_rounds` (default 1) | Bull/Bear subagents called alternately by the skill; transcript in a file |
| Research Manager → Trader → 3 risk debators → Portfolio Manager | Same chain of subagents |
| Quick vs deep LLM tiers | Subagent frontmatter `model: sonnet` (workers) / `opus` (managers) |
| Pydantic structured output for RM / Trader / PM | Agents write JSON; `scripts/validate.py` checks it against Pydantic schemas |
| `trade_date` injected into every tool → no look-ahead | Every MCP tool takes a required `as_of` and clips data to it server-side |
| US data: yfinance, Alpha Vantage, SEC EDGAR, FRED, StockTwits, Reddit | yfinance (`.NS`/`.BO`), NSE archive files, Google News RSS, Zerodha Kite MCP (live only) |
| Memory log + reflection, settled vs benchmark after `holding_period_days` (default 5) | `decisions.jsonl` + settle script vs NIFTY 50 (`^NSEI`); lessons fed to PM |
| Backtest over ticker × date grid | Headless `claude -p "/analyze …"` loop over the grid (subscription), or Agent SDK script (API billing) |

Orchestration note: Claude Code subagents cannot spawn subagents, so the
**skill (running in the main session) is the orchestrator**. Agents hand
off through files in `runs/<SYMBOL>/<DATE>/`, which also gives us the audit trail.

## 2. Data sources (free) — verified 2026-11-05 from a cloud sandbox

| Source | Status | Use |
|---|---|---|
| Yahoo Finance via `yfinance`, `RELIANCE.NS` | ✅ OHLCV, quarterly + annual statements, `info` (161 fields), 10 news items, `^NSEI` | Prices, indicators, fundamentals, index context |
| NSE archives `archives.nseindia.com/content/equities/EQUITY_L.csv` | ✅ 200 | Symbol master / name ↔ symbol resolution |
| Google News RSS (`hl=en-IN&gl=IN`) | ✅ 200 | Company + market news, filtered by `pubDate <= as_of` |
| NSE `/api/*`, BSE `api.bseindia.com` | ❌ 403 (bot-protected) | **Not used.** We will not bypass bot checks. |
| Screener.in | 200, but scraping its pages is a ToS question | **Not used** unless you confirm it's acceptable |
| Zerodha Kite MCP (`mcp.kite.trade`) | Not reachable from this cloud session; connected on your side | Live quotes/LTP/OHLC, holdings, positions, margins, instrument search |

Kite MCP tools (from its README): `get_quotes, get_ltp, get_ohlc, get_historical_data,
search_instruments, get_profile, get_margins, get_holdings, get_positions, get_mf_holdings,
get_orders, get_trades, …` plus order/GTT tools. The hosted server **excludes**
`place_order/modify_order/cancel_order`; we additionally deny all order/GTT tools in
`.claude/settings.json`.

**Rule:** Kite tools have no `as_of` parameter, so they are used **only in live mode**
(`as_of == today`), never in backtests. Backtests use only our clipped MCP server.

Gaps vs the US version (be explicit in reports):
- No free point-in-time filing dates for Indian results via Yahoo. Mitigation:
  treat a quarter's numbers as unknown until quarter-end + 45 days
  (+60 for Q4/annual), per SEBI LODR Reg. 33 deadlines. Conservative, may lag real disclosure.
- No StockTwits/Reddit equivalent with a free API → "Sentiment" analyst is
  news-tone + price/volume behaviour (delivery %, gaps), not social chatter.
- Macro: no free keyless RBI API. v1 uses market proxies via yfinance
  (`^NSEI`, `^NSEBANK`, `^INDIAVIX`, `USDINR=X`, `BZ=F`, `^TNX`); FRED (free key) optional later.

## 3. Repository layout

```
india-trading-agents/
├── mcp_server/                 # Phase 1 — Python, FastMCP, stdio
│   ├── server.py               # tool registration
│   ├── asof.py                 # date clipping + SEBI results-lag filter
│   ├── symbols.py              # NSE/BSE ↔ Yahoo mapping via EQUITY_L.csv
│   ├── prices.py  indicators.py  fundamentals.py  news.py  market.py
│   └── cache/                  # parquet/json cache, keyed by symbol+as_of
├── schemas/decision.py         # Pydantic: ResearchPlan, TraderProposal, PMDecision
├── scripts/  validate.py  settle.py  backtest.sh  report_html.py
├── .claude/
│   ├── agents/                 # 12 subagent .md files (Phase 2)
│   ├── skills/analyze/SKILL.md # /analyze SYMBOL [DATE] (Phase 3)
│   └── settings.json           # MCP registration + deny order tools
├── .mcp.json
├── runs/                       # per-run artifacts (gitignored)
├── memory/decisions.jsonl
└── tests/                      # look-ahead tests first
```

## 4. MCP tools (Phase 1)

All dated tools: required `symbol`, required `as_of` (YYYY-MM-DD); server refuses/clips anything after `as_of`.

| Tool | Returns |
|---|---|
| `resolve_symbol(query)` | NSE symbol, ISIN, Yahoo ticker, name |
| `get_price_history(symbol, start, as_of)` | Daily OHLCV, clipped |
| `get_indicators(symbol, as_of, indicators[], lookback)` | RSI, MACD, BB, SMA/EMA 20/50/200, ATR, VWMA — computed locally with pandas, deterministic |
| `get_market_snapshot(symbol, as_of)` | Latest bar ≤ as_of, 52w hi/lo, indicator values, % from MAs — "source of truth" for price claims |
| `get_financials(symbol, as_of, statement, freq)` | Income/BS/CF, only periods past the SEBI lag |
| `get_fundamentals_summary(symbol, as_of)` | Valuation ratios (live mode only — `info` is not point-in-time; flagged) |
| `get_company_news(symbol, as_of, days)` | Google News RSS + yfinance news, de-duplicated, ≤ as_of |
| `get_market_context(as_of)` | NIFTY, BANKNIFTY, India VIX, USDINR, Brent, US10Y — levels + 5/20-day change |
| `get_corporate_actions(symbol, as_of)` | Dividends/splits ≤ as_of |
| `get_price_on(symbol, date)` | For settlement only |

### Phase 1 as built (2026-11-05)

Built and tested in the cloud session; see README for the final tool list. Changes from the table above:
- Added `list_nifty50`, `get_market_news` and `get_mode` (LIVE vs HISTORICAL, so agents know when Kite may be used).
- `get_price_on` is **not** an MCP tool: settlement reads prices after the decision date, so it will live in
  `scripts/settle.py` (Phase 4) where agents can't call it.
- Found during build: Yahoo also back-adjusts **EPS and share counts** for later bonuses (RIL FY24 EPS shows 51.45
  vs reported 102.9). The server restores them, like prices.
- Found during build: the MCP Python SDK is v2 (`MCPServer`, not `FastMCP`); expected failures are raised as
  `ToolError` so the agent sees the reason.
- Tests: 57 passing (offline date-fence and indicator tests, plus network tests on RELIANCE/INFY/HDFCBANK dates
  and a price check for all 50 constituents).

## 5. Agents (Phase 2)

Prompts adapted from TradingAgents with attribution, India-adjusted
(T+1 settlement, circuit limits, results season, FII/DII flows mentioned only if data present, INR).

| Agent | Model | Tools |
|---|---|---|
| market-analyst | sonnet | price_history, indicators, snapshot |
| fundamentals-analyst | sonnet | financials, fundamentals_summary, corporate_actions |
| news-analyst | sonnet | company_news, market_context |
| sentiment-analyst | sonnet | company_news, snapshot (volume/gap behaviour) |
| bull-researcher / bear-researcher | sonnet | none — read reports |
| research-manager | opus | none → `research_plan.json` (5-tier rating) |
| trader | sonnet | snapshot (price grounding) → `trader.json` (Buy/Hold/Sell, entry/stop/target) |
| risk-aggressive / -conservative / -neutral | sonnet | none |
| portfolio-manager | opus | Kite holdings/positions/margins **if live** → `decision.json` |

## 6. Phases & acceptance criteria

| # | Deliverable | Done when |
|---|---|---|
| 1 ✅ | MCP data server + look-ahead tests | `pytest` proves no tool returns data after `as_of`; registered in Claude Code; works for 5 Nifty stocks |
| 2 | 12 subagents + schemas + validate.py | Each agent runs standalone on a fixture and produces valid output |
| 3 | `/analyze` skill | End-to-end run writes `runs/SYM/DATE/{reports, debate, decision.json, report.md}` |
| 4 | Memory + settlement + backtest | `settle.py` scores pending decisions vs `^NSEI` after N trading days; backtest over a small grid produces a hit-rate / alpha table |
| 5 | HTML report | One-page report per run |

Suggested order of work: 1 → 3 (with 2 minimal) → 2 refined → 4 → 5.

## 7. Risks / limits

- LLM output varies run-to-run; backtest results on small grids are noise. Treat as research.
- Yahoo is unofficial; schemas/rate limits can change. Cache aggressively; one source of failure.
- Kite session needs daily login (Kite tokens expire daily).
- Cost: a full run ≈ 12+ subagent calls; on a subscription this consumes usage limits; backtests multiply that.

## 8. Decisions (2026-11-05)

| Topic | Decision |
|---|---|
| Architecture | Option C — MCP data server + Claude Code subagents/skill; Agent SDK only later for batch |
| Runtime | Claude Desktop / Claude Code on **EbenezerOne** (Kite MCP connected there) |
| Universe | **NIFTY 50** constituents |
| Holding period / settlement | **5 trading days**, alpha vs NIFTY 50 (`^NSEI`) |
| Kite historical candles | **Available** → preferred price source in live mode; yfinance stays the source for backtests (needs `as_of` clipping) and fallback |
| Screener.in | **Excluded** (ToS) |
| NSE/BSE JSON APIs | Excluded (bot-protected; no circumvention) |
| Orders | Never. Order/GTT tools denied in `.claude/settings.json` |
| Repo | GitHub `prasanthebenezer/tradinganalysis` (private) |

## 9. Next steps (on EbenezerOne)

1. Clone the repo, open it in Claude Code / Claude Desktop.
2. Confirm Kite MCP tools are visible (`get_historical_data`, `get_holdings`, …) and the daily login works.
3. Start Phase 1: `mcp_server/` + `tests/test_no_lookahead.py`, validated on 5 NIFTY 50 names, then all 50.
4. Pin the NIFTY 50 constituent list with an effective date (constituents change semi-annually — backtests should use the list valid on each `as_of` where possible; v1 uses the current list and states that bias).
