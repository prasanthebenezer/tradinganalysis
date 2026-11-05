"""Offline tests for the date fence. No network."""

from datetime import date, datetime

import pandas as pd
import pytest

from mcp_server.asof import (
    IST, AsOfError, clip_frame, is_live, parse_as_of, results_public_on,
    session_complete, undo_future_splits, visible_periods,
)

TODAY = date(2026, 11, 5)


def frame(dates, close=100.0, tz="Asia/Kolkata"):
    idx = pd.DatetimeIndex(pd.to_datetime(dates)).tz_localize(tz)
    n = len(idx)
    return pd.DataFrame({"Open": [close] * n, "High": [close] * n, "Low": [close] * n,
                         "Close": [close] * n, "Volume": [1000] * n, "Dividends": [0.0] * n}, index=idx)


class TestParse:
    def test_valid(self):
        assert parse_as_of("2024-10-01", today=TODAY) == date(2024, 10, 1)

    @pytest.mark.parametrize("bad", ["2024/10/01", "01-10-2024", "2024-13-01", "2024-02-30", "", "today", None])
    def test_rejects_bad_format(self, bad):
        with pytest.raises(AsOfError):
            parse_as_of(bad, today=TODAY)

    def test_rejects_future(self):
        with pytest.raises(AsOfError, match="future"):
            parse_as_of("2026-11-06", today=TODAY)

    def test_today_is_allowed_and_live(self):
        d = parse_as_of("2026-11-05", today=TODAY)
        assert is_live(d, today=TODAY)
        assert not is_live(date(2026, 11, 4), today=TODAY)


class TestSession:
    def test_past_day_complete(self):
        assert session_complete(date(2026, 11, 4), now=datetime(2026, 11, 5, 10, 0, tzinfo=IST))

    def test_today_before_close_partial(self):
        assert not session_complete(date(2026, 11, 5), now=datetime(2026, 11, 5, 15, 29, tzinfo=IST))

    def test_today_after_close_complete(self):
        assert session_complete(date(2026, 11, 5), now=datetime(2026, 11, 5, 15, 30, tzinfo=IST))


class TestClip:
    def test_keeps_as_of_drops_later(self):
        df = frame(["2024-09-30", "2024-10-01", "2024-10-03"])
        out = clip_frame(df, date(2024, 10, 1))
        assert [d.date() for d in out.index] == [date(2024, 9, 30), date(2024, 10, 1)]

    def test_after_close_instruments_exclude_as_of(self):
        df = frame(["2024-09-30", "2024-10-01"], tz="America/New_York")
        out = clip_frame(df, date(2024, 10, 1), after_nse_close=True)
        assert [d.date() for d in out.index] == [date(2024, 9, 30)]


class TestSplits:
    def test_future_split_restores_quote(self):
        df = frame(["2024-09-30", "2024-10-01"], close=1464.82)
        splits = pd.Series([2.0], index=pd.DatetimeIndex(["2024-10-28"]).tz_localize("Asia/Kolkata"))
        out = undo_future_splits(df, splits, date(2024, 10, 1))
        assert out["Close"].iloc[-1] == pytest.approx(2929.64)
        assert out["Volume"].iloc[-1] == 500

    def test_past_split_untouched(self):
        df = frame(["2024-11-01"], close=1300.0)
        splits = pd.Series([2.0], index=pd.DatetimeIndex(["2024-10-28"]).tz_localize("Asia/Kolkata"))
        out = undo_future_splits(df, splits, date(2024, 11, 1))
        assert out["Close"].iloc[-1] == 1300.0

    def test_multiple_future_splits_multiply(self):
        df = frame(["2010-01-04"], close=100.0)
        splits = pd.Series([2.0, 2.0], index=pd.DatetimeIndex(["2017-09-07", "2024-10-28"]).tz_localize("Asia/Kolkata"))
        out = undo_future_splits(df, splits, date(2010, 1, 4))
        assert out["Close"].iloc[-1] == 400.0


class TestResultsLag:
    def test_quarter_45_days(self):
        assert results_public_on(date(2026, 6, 30), annual=False) == date(2026, 8, 14)
        assert results_public_on(date(2025, 12, 31), annual=False) == date(2026, 2, 14)

    def test_march_quarter_60_days(self):
        assert results_public_on(date(2026, 3, 31), annual=False) == date(2026, 5, 30)

    def test_annual_60_days(self):
        assert results_public_on(date(2026, 3, 31), annual=True) == date(2026, 5, 30)

    def test_visible_periods(self):
        cols = [pd.Timestamp("2026-06-30"), pd.Timestamp("2026-03-31"), pd.Timestamp("2025-12-31")]
        assert visible_periods(cols, date(2026, 8, 13), annual=False) == cols[1:]
        assert visible_periods(cols, date(2026, 8, 14), annual=False) == cols
        assert visible_periods(cols, date(2026, 5, 29), annual=False) == cols[2:]
