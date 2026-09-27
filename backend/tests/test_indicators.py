import numpy as np
import pandas as pd
import pytest

from quant import indicators as ta


def _close(values) -> pd.Series:
    return pd.Series(values, dtype=float)


def test_sma_exact():
    s = _close([1, 2, 3, 4, 5])
    out = ta.sma(s, 3)
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[4] == pytest.approx(4.0)


def test_ema_converges():
    s = _close([10.0] * 50 + [20.0] * 200)
    out = ta.ema(s, 10)
    assert out.iloc[-1] == pytest.approx(20.0, abs=1e-6)


def test_rsi_bounds_and_extremes():
    up = _close(np.linspace(1, 100, 60))
    down = _close(np.linspace(100, 1, 60))
    rsi_up = ta.rsi(up, 14)
    rsi_down = ta.rsi(down, 14)
    assert rsi_up.iloc[-1] == pytest.approx(100.0)
    assert rsi_down.iloc[-1] == pytest.approx(0.0)
    flat = _close([5.0] * 40)
    assert ta.rsi(flat, 14).iloc[-1] == pytest.approx(50.0)


def test_macd_columns():
    m = ta.macd(_close(np.sin(np.linspace(0, 10, 200)) + 10))
    assert list(m.columns) == ["macd", "signal", "hist"]
    assert (m["hist"] - (m["macd"] - m["signal"])).abs().max() < 1e-10


def test_atr_positive():
    rng = np.random.default_rng(7)
    df = pd.DataFrame({
        "high": 100 + rng.random(100),
        "low": 98 + rng.random(100),
        "close": 99 + rng.random(100),
    })
    out = ta.atr(df, 14)
    assert out.dropna().gt(0).all()


def test_supertrend_directions():
    up_df = pd.DataFrame({
        "open": np.linspace(1, 50, 50),
        "high": np.linspace(1.5, 50.5, 50),
        "low": np.linspace(0.5, 49.5, 50),
        "close": np.linspace(1, 50, 50),
    })
    st = ta.supertrend(up_df, 10, 3.0)
    assert st["direction"].iloc[-1] == 1
    down_df = up_df.iloc[::-1].reset_index(drop=True)
    st2 = ta.supertrend(down_df, 10, 3.0)
    assert st2["direction"].iloc[-1] == -1
