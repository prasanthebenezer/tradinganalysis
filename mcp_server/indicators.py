"""Technical indicators computed locally with pandas, so results are deterministic.

Wilder smoothing is used for RSI and ATR. Inputs must already be fenced at as_of;
these functions only look backwards.
"""

from __future__ import annotations

import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = _wilder(delta.clip(lower=0), n)
    loss = _wilder((-delta).clip(lower=0), n)
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    out = out.where(loss != 0, 100.0)            # no losses in window -> 100
    out = out.where(~((gain == 0) & (loss == 0)), 50.0)  # flat -> 50
    return out.where(gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return pd.DataFrame({"bb_mid": mid, "bb_upper": mid + k * sd, "bb_lower": mid - k * sd})


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    return _wilder(tr, n)


def vwma(df: pd.DataFrame, n: int = 20) -> pd.Series:
    pv = (df["Close"] * df["Volume"]).rolling(n, min_periods=n).sum()
    v = df["Volume"].rolling(n, min_periods=n).sum()
    return pv / v


# name -> (description, function of the OHLCV frame returning a Series)
INDICATORS = {
    "sma_20": ("20-day simple moving average", lambda d: sma(d["Close"], 20)),
    "sma_50": ("50-day simple moving average", lambda d: sma(d["Close"], 50)),
    "sma_200": ("200-day simple moving average", lambda d: sma(d["Close"], 200)),
    "ema_10": ("10-day exponential moving average", lambda d: ema(d["Close"], 10)),
    "ema_20": ("20-day exponential moving average", lambda d: ema(d["Close"], 20)),
    "rsi_14": ("14-day RSI (Wilder)", lambda d: rsi(d["Close"], 14)),
    "macd": ("MACD line (12,26)", lambda d: macd(d["Close"])["macd"]),
    "macd_signal": ("MACD signal (9)", lambda d: macd(d["Close"])["macd_signal"]),
    "macd_hist": ("MACD histogram", lambda d: macd(d["Close"])["macd_hist"]),
    "bb_mid": ("Bollinger middle (20)", lambda d: bollinger(d["Close"])["bb_mid"]),
    "bb_upper": ("Bollinger upper (20, 2σ)", lambda d: bollinger(d["Close"])["bb_upper"]),
    "bb_lower": ("Bollinger lower (20, 2σ)", lambda d: bollinger(d["Close"])["bb_lower"]),
    "atr_14": ("14-day average true range (Wilder)", lambda d: atr(d, 14)),
    "vwma_20": ("20-day volume-weighted moving average", lambda d: vwma(d, 20)),
}


def compute(df: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    unknown = [n for n in names if n not in INDICATORS]
    if unknown:
        raise ValueError(f"unknown indicator(s) {unknown}; choose from {sorted(INDICATORS)}")
    return pd.DataFrame({n: INDICATORS[n][1](df) for n in names}, index=df.index)
