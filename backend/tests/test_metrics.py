import numpy as np
import pandas as pd
import pytest

from quant.metrics import compute_stats, estimate_bars_per_year


def _equity(values):
    times = pd.date_range("2024-01-01", periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=times, dtype=float)


def test_stats_uptrend_positive_sharpe():
    eq = _equity(np.linspace(1_000_000, 1_200_000, 253))
    trades = pd.DataFrame([{"pnl": 1000.0, "return_pct": 0.1}])
    stats = compute_stats(eq, trades, bars_per_year=252, exposure=0.5,
                          initial_cash=1_000_000, buy_hold_return=0.2)
    assert stats["total_return_pct"] == pytest.approx(20.0)
    assert stats["sharpe"] > 0
    assert stats["max_drawdown_pct"] == pytest.approx(0.0)
    assert stats["n_trades"] == 1


def test_stats_drawdown():
    eq = _equity([1_000_000] * 5 + [900_000] * 5 + [950_000] * 5)
    stats = compute_stats(eq, pd.DataFrame(), bars_per_year=252)
    assert stats["max_drawdown_pct"] == pytest.approx(-10.0)
    assert stats["n_trades"] == 0


def test_bars_per_year_estimation():
    day_ms = 86_400_000
    daily = np.array([1_700_000_000_000 + i * day_ms for i in range(100)])
    assert 240 < estimate_bars_per_year(daily, "cn") < 250
    assert 360 < estimate_bars_per_year(daily, "crypto") < 366
    weekly = np.array([1_700_000_000_000 + i * 7 * day_ms for i in range(100)])
    assert 35 < estimate_bars_per_year(weekly, "us") < 37  # 252 交易日 / 7
    hour_ms = 3_600_000
    hourly_us = np.array([1_700_000_000_000 + i * hour_ms for i in range(100)])
    assert 1630 < estimate_bars_per_year(hourly_us, "us") < 1640
