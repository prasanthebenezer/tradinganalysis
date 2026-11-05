"""Financial statements (fenced by the SEBI results deadline) and live-only valuation."""

from __future__ import annotations

from datetime import date

import pandas as pd
import yfinance as yf

from .asof import AsOfError, is_live, results_public_on, visible_periods, _index_dates
from .cache import cached
from .prices import raw_history
from .symbols import to_yahoo

CRORE = 1e7
STATEMENTS = {
    ("income", "quarterly"): "quarterly_income_stmt",
    ("income", "annual"): "income_stmt",
    ("balance", "quarterly"): "quarterly_balance_sheet",
    ("balance", "annual"): "balance_sheet",
    ("cashflow", "quarterly"): "quarterly_cashflow",
    ("cashflow", "annual"): "cashflow",
}


def _is_per_share(row: str) -> bool:
    r = row.lower()
    return "eps" in r or "per share" in r


def _is_share_count(row: str) -> bool:
    r = row.lower()
    return "shares" in r or "share issued" in r


def _is_ratio(row: str) -> bool:
    return "rate" in row.lower()


def _future_split_factor(symbol: str, as_of: date) -> float:
    _, splits = raw_history(to_yahoo(symbol), live=is_live(as_of))
    if splits is None or splits.empty:
        return 1.0
    future = splits[_index_dates(splits.index) > as_of]
    return float(future.prod()) if not future.empty else 1.0


def statement(symbol: str, kind: str, freq: str, as_of: date) -> tuple[pd.DataFrame, list[str]]:
    """Statement columns whose results were public by as_of, in ₹ crore.

    Per-share rows stay in ₹ and share counts stay in units, both restored to
    their values before any split dated after as_of.
    """
    attr = STATEMENTS.get((kind, freq))
    if attr is None:
        raise ValueError("statement must be income|balance|cashflow and freq quarterly|annual")
    ysym = to_yahoo(symbol)
    df = cached(f"stmt:{ysym}:{attr}", 24 * 3600, lambda: getattr(yf.Ticker(ysym), attr))
    notes: list[str] = []
    if df is None or df.empty:
        return pd.DataFrame(), [f"Yahoo has no {freq} {kind} statement for {symbol}"]
    annual = freq == "annual"
    cols = sorted(visible_periods(df.columns, as_of, annual), reverse=True)
    hidden = [c for c in df.columns if c not in cols]
    if hidden:
        nxt = min(pd.Timestamp(c).date() for c in hidden)
        notes.append(
            f"{len(hidden)} later period(s) hidden: results treated as public only after the SEBI deadline "
            f"(e.g. period {nxt} -> {results_public_on(nxt, annual)})"
        )
    if not cols:
        notes.append("no period was public by as_of in Yahoo's data (Yahoo keeps ~5 quarters / ~5 years)")
        return pd.DataFrame(), notes
    out = df[cols].dropna(how="all")
    factor = _future_split_factor(symbol, as_of)
    rows = {}
    for row, vals in out.iterrows():
        v = vals.astype(float)
        if _is_per_share(row):
            rows[f"{row} (₹)"] = v * factor
        elif _is_share_count(row):
            rows[f"{row} (count)"] = v / factor
        elif _is_ratio(row):
            rows[row] = v
        else:
            rows[f"{row} (₹ cr)"] = v / CRORE
    res = pd.DataFrame(rows).T.round(2)
    res.columns = [pd.Timestamp(c).date().isoformat() for c in res.columns]
    if factor != 1.0:
        notes.append(f"per-share and share-count rows restored for splits/bonuses after as_of (factor {factor:g})")
    return res, notes


SUMMARY_FIELDS = [
    ("sector", "Sector"), ("industry", "Industry"), ("marketCap", "Market cap (₹ cr)"),
    ("currentPrice", "Price (₹)"), ("trailingPE", "Trailing P/E"), ("forwardPE", "Forward P/E"),
    ("priceToBook", "Price/Book"), ("dividendYield", "Dividend yield (%)"),
    ("returnOnEquity", "ROE"), ("returnOnAssets", "ROA"), ("debtToEquity", "Debt/Equity (%)"),
    ("profitMargins", "Net margin"), ("operatingMargins", "Operating margin"),
    ("revenueGrowth", "Revenue growth (yoy, latest qtr)"), ("earningsGrowth", "Earnings growth (yoy, latest qtr)"),
    ("beta", "Beta"), ("fiftyTwoWeekHigh", "52w high (₹)"), ("fiftyTwoWeekLow", "52w low (₹)"),
    ("heldPercentInsiders", "Held by insiders/promoters"), ("heldPercentInstitutions", "Held by institutions"),
]


def summary(symbol: str, as_of: date) -> list[tuple[str, object]]:
    """Current valuation snapshot. Yahoo keeps no history of these, so live only."""
    if not is_live(as_of):
        raise AsOfError(
            "get_fundamentals_summary is live-only: Yahoo's valuation fields are today's values, "
            "so they would leak the future into a past as_of. Use get_financials instead."
        )
    ysym = to_yahoo(symbol)
    info = cached(f"info:{ysym}", 3600, lambda: yf.Ticker(ysym).info) or {}
    out = []
    for key, label in SUMMARY_FIELDS:
        v = info.get(key)
        if v is None:
            continue
        if key == "marketCap":
            v = round(v / CRORE, 0)
        elif isinstance(v, float):
            v = round(v, 4)
        out.append((label, v))
    return out
