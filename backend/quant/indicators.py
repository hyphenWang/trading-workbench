"""技术指标库：全部基于 pandas/numpy 实现，无外部指标依赖。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(int(n)).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=int(n), adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI。"""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - 100 / (1 + rs)
    out = out.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    out = out.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    return out


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=int(signal), adjust=False).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(int(n)).mean()
    sd = close.rolling(int(n)).std(ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + k * sd, "lower": mid - k * sd})


def donchian(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """不含当前 bar 的前 n 根高低点（避免用当根数据产生前视偏差）。"""
    return pd.DataFrame(
        {
            "upper": df["high"].rolling(int(n)).max().shift(1),
            "lower": df["low"].rolling(int(n)).min().shift(1),
        }
    )


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.DataFrame:
    """返回 trend(上下轨基础值)、direction(+1 上升趋势 / -1 下降趋势)、st 线。"""
    atr_ = atr(df, n)
    hl2 = (df["high"] + df["low"]) / 2
    ub = (hl2 + mult * atr_).to_numpy()
    lb = (hl2 - mult * atr_).to_numpy()
    close = df["close"].to_numpy()
    size = len(df)
    f_ub = np.full(size, np.nan)
    f_lb = np.full(size, np.nan)
    st = np.full(size, np.nan)
    direction = np.zeros(size, dtype=int)
    for i in range(size):
        if np.isnan(ub[i]):
            continue
        prev_ub = f_ub[i - 1] if i > 0 and not np.isnan(f_ub[i - 1]) else ub[i]
        prev_lb = f_lb[i - 1] if i > 0 and not np.isnan(f_lb[i - 1]) else lb[i]
        f_ub[i] = ub[i] if (ub[i] < prev_ub or close[i - 1] > prev_ub) else prev_ub
        f_lb[i] = lb[i] if (lb[i] > prev_lb or close[i - 1] < prev_lb) else prev_lb
        if np.isnan(st[i - 1]) or i == 0:
            direction[i] = 1
            st[i] = f_lb[i]
        elif direction[i - 1] == 1:
            if close[i] < f_lb[i]:
                direction[i] = -1
                st[i] = f_ub[i]
            else:
                direction[i] = 1
                st[i] = f_lb[i]
        else:
            if close[i] > f_ub[i]:
                direction[i] = 1
                st[i] = f_lb[i]
            else:
                direction[i] = -1
                st[i] = f_ub[i]
    return pd.DataFrame({"st": st, "direction": direction}, index=df.index)
