"""The no-look-ahead rules. Everything that touches a date goes through here.

Conventions
-----------
* ``as_of`` is a calendar date in India. A decision dated ``as_of`` is assumed
  to be made after the NSE close (15:30 IST) that day, so that day's bar and
  news are visible.
* Instruments that close after the NSE (US yields, Brent, FX) are visible only
  up to the day *before* ``as_of``: their bar for ``as_of`` closes after
  15:30 IST.
* Yahoo rewrites old prices after every split/bonus. Prices are rebuilt as
  they stood on ``as_of`` by reversing splits dated after it.
* Yahoo gives no filing dates for Indian results. A period is treated as
  public only after the SEBI LODR Reg. 33 deadline: 45 days after quarter
  end, 60 days for the March quarter and the annual results.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
NSE_CLOSE = time(15, 30)
EARLIEST = date(2000, 1, 1)

QUARTER_LAG_DAYS = 45
ANNUAL_LAG_DAYS = 60

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AsOfError(ValueError):
    """An as_of date the server refuses to serve."""


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def parse_as_of(value: str, today: date | None = None) -> date:
    """Strict YYYY-MM-DD, not in the future (IST), not before 2000."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise AsOfError(f"as_of must be YYYY-MM-DD, got {value!r}")
    try:
        d = date.fromisoformat(value.strip())
    except ValueError as exc:
        raise AsOfError(f"as_of is not a real date: {value!r}") from exc
    today = today or today_ist()
    if d > today:
        raise AsOfError(f"as_of {d} is after today in India ({today}); future data does not exist")
    if d < EARLIEST:
        raise AsOfError(f"as_of {d} is before {EARLIEST}; not supported")
    return d


def is_live(as_of: date, today: date | None = None) -> bool:
    """True when as_of is today in India: live-only sources may be used."""
    return as_of == (today or today_ist())


def session_complete(as_of: date, now: datetime | None = None) -> bool:
    """False while the NSE session for as_of is still open (its bar is partial)."""
    now = now or now_ist()
    if as_of < now.date():
        return True
    return now.time() >= NSE_CLOSE


def _index_dates(index: pd.Index) -> pd.Index:
    """Calendar dates of a DatetimeIndex in the instrument's own timezone."""
    idx = pd.DatetimeIndex(index)
    return pd.Index(idx.date)


def clip_frame(df: pd.DataFrame, as_of: date, after_nse_close: bool = False) -> pd.DataFrame:
    """Rows dated on/before as_of (or strictly before, for instruments closing after NSE)."""
    if df.empty:
        return df
    dates = _index_dates(df.index)
    mask = dates < as_of if after_nse_close else dates <= as_of
    return df.loc[mask]


def undo_future_splits(df: pd.DataFrame, splits: pd.Series, as_of: date) -> pd.DataFrame:
    """Rebuild prices as they were quoted on as_of.

    Yahoo divides every price before a split by the split ratio. For a frame
    already clipped to as_of, every row sits before each split dated after
    as_of, so multiplying by the product of those ratios restores the quote.
    """
    if df.empty or splits is None or splits.empty:
        return df
    s = splits[splits > 0]
    future = s[_index_dates(s.index) > as_of] if not s.empty else s
    if future.empty:
        return df
    factor = float(future.prod())
    out = df.copy()
    for col in ("Open", "High", "Low", "Close", "Adj Close", "Dividends"):
        if col in out.columns:
            out[col] = out[col] * factor
    if "Volume" in out.columns:
        out["Volume"] = (out["Volume"] / factor).round()
    return out


def results_public_on(period_end: date, annual: bool) -> date:
    """Earliest date a period's results are treated as public (SEBI LODR Reg. 33 deadline)."""
    lag = ANNUAL_LAG_DAYS if (annual or period_end.month == 3) else QUARTER_LAG_DAYS
    return period_end + timedelta(days=lag)


def visible_periods(period_ends, as_of: date, annual: bool) -> list:
    """The statement period columns whose results were public by as_of."""
    out = []
    for p in period_ends:
        pe = pd.Timestamp(p).date()
        if results_public_on(pe, annual) <= as_of:
            out.append(p)
    return out


def header(tool: str, as_of: date, subject: str, through: date | None, source: str, notes: list[str] | None = None) -> str:
    """First lines of every tool result, so agents always see the date fence."""
    through_s = through.isoformat() if through else "no data"
    lines = [f"[{tool}] {subject} | as_of={as_of.isoformat()} | data_through={through_s} | source={source}"]
    for n in notes or []:
        lines.append(f"note: {n}")
    return "\n".join(lines)
