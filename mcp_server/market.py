"""Market backdrop: Indian indices plus global prices that move Indian stocks."""

from __future__ import annotations

from datetime import date

import pandas as pd

from .prices import NoDataError, bars_as_of

# (label, Yahoo symbol, closes after the NSE?)
INSTRUMENTS = [
    ("NIFTY 50", "^NSEI", False),
    ("NIFTY BANK", "^NSEBANK", False),
    ("India VIX", "^INDIAVIX", False),
    ("USD/INR", "USDINR=X", True),
    ("Brent crude (USD)", "BZ=F", True),
    ("US 10Y yield (%)", "^TNX", True),
]


def _pct(series: pd.Series, n: int) -> float | None:
    if len(series) <= n:
        return None
    return round((series.iloc[-1] / series.iloc[-1 - n] - 1) * 100, 2)


def context(as_of: date) -> tuple[pd.DataFrame, list[str]]:
    rows, notes = [], []
    for label, ysym, after_close in INSTRUMENTS:
        try:
            b = bars_as_of(ysym, as_of, after_nse_close=after_close)
        except NoDataError:
            notes.append(f"{label}: no data")
            continue
        except Exception as exc:  # network
            notes.append(f"{label}: unavailable ({exc.__class__.__name__})")
            continue
        if b.df.empty:
            notes.append(f"{label}: no data on or before as_of")
            continue
        c = b.df["Close"].dropna()
        rows.append({"instrument": label, "symbol": ysym, "date": b.through.isoformat(),
                     "close": round(float(c.iloc[-1]), 2), "chg_5d_%": _pct(c, 5), "chg_20d_%": _pct(c, 20),
                     "partial": b.partial_last_bar})
    notes.append("USD/INR, Brent and US10Y close after the NSE, so their latest shown bar is the day before as_of")
    return pd.DataFrame(rows), notes
