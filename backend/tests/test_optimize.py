import numpy as np
import pandas as pd
import pytest

from quant.optimize import walk_forward


def _df(n=1400, seed=11):
    rng = np.random.default_rng(seed)
    trend = np.linspace(100, 160, n)
    noise = rng.normal(0, 1.2, n).cumsum() * 0.4
    closes = trend + noise
    times = 1_700_000_000_000 + np.arange(n) * 86_400_000
    return pd.DataFrame({
        "time": times,
        "open": closes,
        "high": closes * 1.01,
        "low": closes * 0.99,
        "close": closes,
        "volume": 1.0,
    })


def test_walk_forward_runs_and_returns_windows():
    out = walk_forward(
        _df(), "crypto", "sma_cross",
        {"fast": [10, 20], "slow": [30, 60]},
        train_bars=400, test_bars=200,
    )
    # start 从 0 每次前进 test_bars：满足 start+train+test<=n 的起点共 5 个
    assert out["n_windows"] == 5
    assert out["n_combos"] == 4
    assert len(out["windows"]) == 5
    for w in out["windows"]:
        assert set(w["params"]) == {"fast", "slow"}
        assert w["test_to"] > w["test_from"]
    assert "oos" in out and "total_return_pct" in out["oos"]
    assert out["oos"]["buy_hold_pct"] is not None


def test_walk_forward_windows_roll_without_overlap():
    out = walk_forward(
        _df(), "crypto", "ema_cross", {"fast": [10], "slow": [30]},
        train_bars=400, test_bars=200,
    )
    wins = out["windows"]
    for a, b in zip(wins, wins[1:]):
        # 测试窗按 bar 顺序首尾衔接：下一窗第一根 = 上一窗最后一根的下一根（日线恰好差一天）
        assert b["test_from"] - a["test_to"] == 86_400_000
        assert b["test_from"] - b["train_to"] == 86_400_000  # 训练窗末根的下一根即测试窗首根


def test_walk_forward_rejects_oversized_grid():
    big_grid = {"fast": [5, 10, 15, 20], "slow": [30, 60, 90, 120]}  # 16 组合
    with pytest.raises(ValueError, match="上限"):
        walk_forward(
            _df(), "crypto", "sma_cross",
            {"fast": list(range(1, 10)), "slow": list(range(10, 100, 10))},
            train_bars=400, test_bars=200,
        )


def test_walk_forward_rejects_insufficient_data():
    with pytest.raises(ValueError, match="数据不足|不足以"):
        walk_forward(
            _df(300), "crypto", "sma_cross", {"fast": [10], "slow": [30]},
            train_bars=400, test_bars=200,
        )
