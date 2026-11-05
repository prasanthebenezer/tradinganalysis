"""Daily OHLCV from Yahoo, rebuilt as it stood on as_of."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import yfinance as yf

from .asof import clip_frame, is_live, session_complete, undo_future_splits
from .cache import cached
from .symbols import to_yahoo

LIVE_MAX_AGE_S = 10 * 60
PAST_MAX_AGE_S = 12 * 3600


class NoDataError(LookupError):
    pass


def _download(yahoo_symbol: str) -> tuple[pd.DataFrame, pd.Series]:
    t = yf.Ticker(yahoo_symbol)
    df = t.history(period="max", auto_adjust=False, actions=True)
    if df is None or df.empty:
        raise NoDataError(f"Yahoo returned no price history for {yahoo_symbol}")
    splits = df["Stock Splits"] if "Stock Splits" in df.columns else pd.Series(dtype=float)
    splits = splits[splits > 0]
    return df, splits


def raw_history(yahoo_symbol: str, live: bool) -> tuple[pd.DataFrame, pd.Series]:
    max_age = LIVE_MAX_AGE_S if live else PAST_MAX_AGE_S
    return cached(f"hist:{yahoo_symbol}", max_age, lambda: _download(yahoo_symbol))


@dataclass
class Bars:
    df: pd.DataFrame          # Open High Low Close Volume Dividends Splits, as quoted on as_of
    through: date | None      # date of the last row
    partial_last_bar: bool    # last row is today's session still in progress
    notes: list[str]


def bars_as_of(yahoo_symbol: str, as_of: date, after_nse_close: bool = False) -> Bars:
    """Price history for any Yahoo symbol, fenced at as_of."""
    df, splits = raw_history(yahoo_symbol, live=is_live(as_of))
    df = clip_frame(df, as_of, after_nse_close=after_nse_close)
    notes: list[str] = []
    if df.empty:
        return Bars(df, None, False, [f"no rows on or before {as_of}"])
    restored = undo_future_splits(df, splits, as_of)
    if restored is not df:
        notes.append("prices restored to pre-split quotes (Yahoo back-adjusts for splits dated after as_of)")
    df = restored.rename(columns={"Stock Splits": "Splits"})
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume", "Dividends", "Splits") if c in df.columns]
    df = df[keep]
    through = pd.Timestamp(df.index[-1]).date()
    partial = through == as_of and not after_nse_close and not session_complete(as_of)
    if partial:
        notes.append("last bar is today's session in progress (before 15:30 IST); its Close is not final")
    return Bars(df, through, partial, notes)


def stock_bars(symbol: str, as_of: date) -> Bars:
    return bars_as_of(to_yahoo(symbol), as_of)


def ohlcv_table(df: pd.DataFrame) -> str:
    out = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    out.index = [pd.Timestamp(i).date().isoformat() for i in out.index]
    out.index.name = "Date"
    out[["Open", "High", "Low", "Close"]] = out[["Open", "High", "Low", "Close"]].round(2)
    out["Volume"] = out["Volume"].astype("int64")
    return out.to_csv()
