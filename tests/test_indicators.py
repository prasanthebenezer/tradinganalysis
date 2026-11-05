"""Offline indicator tests on synthetic prices."""

import numpy as np
import pandas as pd
import pytest

from mcp_server import indicators as ind


def ohlcv(close, spread=0.0, volume=1000):
    close = pd.Series(close, dtype=float, index=pd.date_range("2024-01-01", periods=len(close)))
    return pd.DataFrame({"Open": close, "High": close + spread, "Low": close - spread,
                         "Close": close, "Volume": float(volume)})


def test_sma_and_warmup():
    s = pd.Series(range(1, 11), dtype=float)
    out = ind.sma(s, 5)
    assert out.iloc[:4].isna().all()
    assert out.iloc[4] == 3.0 and out.iloc[-1] == 8.0


def test_ema_matches_recursion():
    s = pd.Series([10, 11, 12, 11, 13, 14, 13, 15], dtype=float)
    n, a = 3, 2 / 4
    expect = [s.iloc[0]]
    for x in s.iloc[1:]:
        expect.append(a * x + (1 - a) * expect[-1])
    out = ind.ema(s, n)
    assert out.iloc[n - 1:].tolist() == pytest.approx(expect[n - 1:])


def test_rsi_extremes():
    up = pd.Series(np.arange(1, 40), dtype=float)
    assert ind.rsi(up).iloc[-1] == 100.0
    down = pd.Series(np.arange(40, 1, -1), dtype=float)
    assert ind.rsi(down).iloc[-1] == pytest.approx(0.0)
    flat = pd.Series([5.0] * 30)
    assert ind.rsi(flat).iloc[-1] == 50.0


def test_rsi_bounded():
    rng = np.random.default_rng(0)
    s = pd.Series(100 + rng.standard_normal(300).cumsum())
    r = ind.rsi(s).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_macd_zero_on_flat():
    m = ind.macd(pd.Series([50.0] * 60)).dropna()
    assert np.allclose(m.values, 0.0)


def test_bollinger_collapses_on_flat():
    b = ind.bollinger(pd.Series([20.0] * 25)).iloc[-1]
    assert b["bb_upper"] == b["bb_mid"] == b["bb_lower"] == 20.0


def test_atr_constant_range():
    df = ohlcv([100.0] * 40, spread=2.0)
    assert ind.atr(df).iloc[-1] == pytest.approx(4.0)


def test_vwma_equal_volume_is_sma():
    df = ohlcv(np.linspace(100, 120, 30))
    assert ind.vwma(df).iloc[-1] == pytest.approx(ind.sma(df["Close"], 20).iloc[-1])


def test_indicators_only_look_back():
    """Changing a future price must not change an earlier indicator value."""
    rng = np.random.default_rng(1)
    base = 100 + rng.standard_normal(260).cumsum()
    a, b = ohlcv(base), ohlcv(np.r_[base[:-1], base[-1] * 1.5])
    names = list(ind.INDICATORS)
    ca, cb = ind.compute(a, names), ind.compute(b, names)
    pd.testing.assert_frame_equal(ca.iloc[:-1], cb.iloc[:-1])


def test_unknown_indicator():
    with pytest.raises(ValueError, match="unknown"):
        ind.compute(ohlcv([1.0] * 5), ["rsi_99"])
