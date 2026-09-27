"""Walk-Forward 参数寻优。

流程（防止"调参调到历史上过拟合"）：
  1. 把历史数据按"训练窗 -> 测试窗"滚动切分（每次前进 test_bars 根）；
  2. 每个训练窗内，对参数网格的每个组合跑回测，按指定指标选出最优参数；
  3. 用最优参数在紧随其后的测试窗（样本外）回测，记录结果；
  4. 汇总所有测试窗 = 纯样本外绩效；对比训练/测试指标判断过拟合程度。

约束：参数组合数 <= 64；窗口数 <= 12；训练窗最少 min_train 根。
"""
from __future__ import annotations

import itertools

import pandas as pd

from quant import engine as bt_engine
from quant import metrics as bt_metrics
from quant import strategies as bt_strategies

MAX_COMBOS = 64
MAX_WINDOWS = 12
MIN_TRAIN_BARS = 150
SUPPORTED_METRICS = {"sharpe", "total_return_pct", "cagr_pct"}


def walk_forward(
    df: pd.DataFrame,
    market: str,
    strategy_name: str,
    param_grid: dict[str, list[float]],
    train_bars: int = 500,
    test_bars: int = 250,
    *,
    fee: float = 0.001,
    slippage: float = 0.0,
    allow_short: bool = False,
    initial_cash: float = 1_000_000.0,
    size_pct: float = 1.0,
    metric: str = "sharpe",
) -> dict:
    if metric not in SUPPORTED_METRICS:
        raise ValueError(f"不支持的优化指标 {metric}（可用: {sorted(SUPPORTED_METRICS)}）")
    keys = list(param_grid.keys())
    if not keys:
        raise ValueError("参数网格为空")
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*[param_grid[k] for k in keys])]
    if len(combos) > MAX_COMBOS:
        raise ValueError(f"参数组合数 {len(combos)} 超过上限 {MAX_COMBOS}，请精简网格")
    if train_bars < MIN_TRAIN_BARS:
        raise ValueError(f"训练窗口至少 {MIN_TRAIN_BARS} 根 K 线")
    if test_bars < 50:
        raise ValueError("测试窗口至少 50 根 K 线")

    n = len(df)
    start = 0
    windows: list[dict] = []
    test_equities: list[pd.Series] = []

    while start + train_bars + test_bars <= n and len(windows) < MAX_WINDOWS:
        train_df = df.iloc[start : start + train_bars]
        test_df = df.iloc[start + train_bars : start + train_bars + test_bars]
        bpy_train = bt_metrics.estimate_bars_per_year(train_df["time"].to_numpy(), market)

        best_params: dict | None = None
        best_metric = -float("inf")
        for params in combos:
            sig = bt_strategies.apply_strategy(strategy_name, train_df, params)
            res = bt_engine.run_backtest(
                train_df, sig["long_entry"], sig["long_exit"],
                sig["short_entry"] if allow_short else None,
                sig["short_exit"] if allow_short else None,
                fee=fee, slippage=slippage,
                initial_cash=initial_cash, size_pct=size_pct,
            )
            stats = bt_metrics.compute_stats(
                res["equity"], res["trades"], bpy_train,
                exposure=res["exposure"], initial_cash=initial_cash,
            )
            m = stats.get(metric)
            if m is None:
                continue
            if m > best_metric:
                best_metric, best_params = float(m), params

        if best_params is None:
            raise ValueError("训练窗内所有参数组合都无法产生有效指标（数据质量问题？）")

        # 用训练窗选出的最优参数跑样本外测试窗
        bpy_test = bt_metrics.estimate_bars_per_year(test_df["time"].to_numpy(), market)
        sig_te = bt_strategies.apply_strategy(strategy_name, test_df, best_params)
        res_te = bt_engine.run_backtest(
            test_df, sig_te["long_entry"], sig_te["long_exit"],
            sig_te["short_entry"] if allow_short else None,
            sig_te["short_exit"] if allow_short else None,
            fee=fee, slippage=slippage,
            initial_cash=initial_cash, size_pct=size_pct,
        )
        buy_hold = float(test_df["close"].iloc[-1] / test_df["close"].iloc[0] - 1.0)
        stats_te = bt_metrics.compute_stats(
            res_te["equity"], res_te["trades"], bpy_test,
            exposure=res_te["exposure"], initial_cash=initial_cash,
            buy_hold_return=buy_hold,
        )
        windows.append(
            {
                "train_from": int(train_df["time"].iloc[0]),
                "train_to": int(train_df["time"].iloc[-1]),
                "test_from": int(test_df["time"].iloc[0]),
                "test_to": int(test_df["time"].iloc[-1]),
                "params": best_params,
                "train_metric": round(best_metric, 2),
                "test_metric": stats_te.get(metric),
                "test_return_pct": stats_te["total_return_pct"],
                "test_sharpe": stats_te["sharpe"],
                "test_max_drawdown_pct": stats_te["max_drawdown_pct"],
                "test_buy_hold_pct": stats_te["buy_hold_pct"],
            }
        )
        test_equities.append(res_te["equity"])
        start += test_bars

    if not windows:
        raise ValueError(
            f"数据不足以完成一次训练+测试（需要至少 {train_bars + test_bars} 根，当前 {n} 根），"
            "请扩大历史范围或缩小窗口"
        )

    # 汇总纯样本外资金曲线（各测试窗首尾相接，时间连续）
    combined = pd.concat(test_equities)
    combined = combined[~combined.index.duplicated(keep="last")]
    bpy_all = bt_metrics.estimate_bars_per_year(df["time"].to_numpy(), market)
    oos_span = df.iloc[train_bars : (train_bars + test_bars * len(windows))]
    oos_bh = float(oos_span["close"].iloc[-1] / oos_span["close"].iloc[0] - 1.0)
    oos_stats = bt_metrics.compute_stats(
        combined, pd.DataFrame(), bpy_all,
        exposure=0.0,  # 样本外合计不做暴露统计
        initial_cash=initial_cash,
        buy_hold_return=oos_bh,
    )

    # 过拟合诊断：测试均值 / 训练均值
    train_vals = [w["train_metric"] for w in windows if w["train_metric"] is not None]
    test_vals = [w["test_metric"] for w in windows if w["test_metric"] is not None]
    ratio = None
    if train_vals and test_vals and sum(train_vals) != 0:
        ratio = round((sum(test_vals) / len(test_vals)) / (sum(train_vals) / len(train_vals)), 2)

    return {
        "n_combos": len(combos),
        "n_windows": len(windows),
        "metric": metric,
        "overfit_ratio": round(ratio, 2) if ratio is not None else None,
        "oos": oos_stats,
        "windows": windows,
    }
