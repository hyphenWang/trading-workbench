import numpy as np
import pandas as pd
import pytest

from quant.engine import run_backtest


def _df(closes, interval_ms=86_400_000, base=1_700_000_000_000):
    closes = np.asarray(closes, dtype=float)
    times = base + np.arange(len(closes)) * interval_ms
    return pd.DataFrame({
        "time": times,
        "open": closes,
        "high": closes * 1.01,
        "low": closes * 0.99,
        "close": closes,
        "volume": 1.0,
    })


def test_buy_and_hold_no_fee_matches_price_ratio():
    closes = np.linspace(100, 200, 11)
    df = _df(closes)
    entry = np.zeros(len(df), dtype=bool)
    entry[0] = True
    out = run_backtest(df, entry, np.zeros(len(df), dtype=bool), fee=0.0, slippage=0.0)
    # 第 0 根收盘出信号 -> 第 1 根开盘价成交（此处 open==close 序列），期末按最后收盘强平
    expected = closes[-1] / closes[1]
    assert out["equity"].iloc[-1] / 1_000_000 == pytest.approx(expected)


def test_no_lookahead_signal_executes_next_open():
    closes = [100, 100, 110, 120]
    df = _df(closes)
    entry = np.zeros(4, dtype=bool)
    entry[2] = True  # 第 2 根收盘出信号
    out = run_backtest(df, entry, np.zeros(4, dtype=bool), fee=0.0)
    assert len(out["trades"]) == 1
    # 成交价必须是第 3 根开盘价（120），而不是信号当根的 110
    assert out["trades"].iloc[0]["entry_price"] == pytest.approx(120.0)


def test_signal_on_last_bar_never_executes():
    closes = [100, 101, 102, 103]
    df = _df(closes)
    entry = np.zeros(4, dtype=bool)
    entry[3] = True
    out = run_backtest(df, entry, np.zeros(4, dtype=bool), fee=0.0)
    assert out["trades"].empty
    assert out["equity"].iloc[-1] == pytest.approx(1_000_000)


def test_fee_reduces_equity():
    closes = np.linspace(100, 150, 30)
    df = _df(closes)
    entry = np.zeros(30, dtype=bool)
    entry[0] = True
    exit_ = np.zeros(30, dtype=bool)
    exit_[-2] = True
    no_fee = run_backtest(df, entry, exit_, fee=0.0)
    with_fee = run_backtest(df, entry, exit_, fee=0.001)
    assert with_fee["equity"].iloc[-1] < no_fee["equity"].iloc[-1]
    # 两笔交易（开+平），来回各 0.1%
    assert with_fee["equity"].iloc[-1] / no_fee["equity"].iloc[-1] == pytest.approx(1 - 0.002, rel=1e-3)


def test_short_profits_on_decline():
    closes = np.linspace(200, 100, 21)
    df = _df(closes)
    se = np.zeros(21, dtype=bool)
    se[0] = True
    out = run_backtest(
        df,
        np.zeros(21, dtype=bool), np.zeros(21, dtype=bool),
        se, np.zeros(21, dtype=bool),
        fee=0.0,
    )
    assert out["equity"].iloc[-1] > 1_000_000
    assert out["trades"].iloc[0]["side"] == "short"


def test_exit_reenters_multiple_trades():
    closes = [100, 90, 100, 90, 100, 90, 100]
    df = _df(closes)
    n = len(df)
    le = np.array([True, False, True, False, True, False, False])
    lx = np.array([False, True, False, True, False, True, False])
    out = run_backtest(df, le, lx, fee=0.0)
    assert len(out["trades"]) == 3
    # 每个来回：持有 1 根、空仓 1 根
    assert out["exposure"] == pytest.approx(0.5)
