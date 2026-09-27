"""绩效指标计算。所有比率类结果以百分数返回，便于前端直接展示。"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

# 指标 key -> 中文标签（前端也用同一套）
METRIC_LABELS_ZH = {
    "total_return_pct": "总收益",
    "cagr_pct": "年化收益",
    "ann_vol_pct": "年化波动",
    "sharpe": "夏普比率",
    "sortino": "索提诺比率",
    "max_drawdown_pct": "最大回撤",
    "win_rate_pct": "胜率",
    "profit_factor": "盈亏比",
    "n_trades": "交易次数",
    "avg_trade_ret_pct": "平均单笔收益",
    "exposure_pct": "持仓时间占比",
    "buy_hold_pct": "买入持有对照",
}


def estimate_bars_per_year(times_ms: np.ndarray, market: str) -> float:
    """用相邻 bar 的中位间隔估算年化因子（近似值，够用于 Sharpe/CAGR）。

    日线及以上：bars/年 = 年交易日数 / bar 间隔天数；
    小时级及以下：bars/年 = 年交易日数 * 每日交易小时 / bar 间隔小时。
    """
    if len(times_ms) < 3:
        return 252.0
    diffs = np.diff(np.sort(times_ms))
    median_sec = float(np.median(diffs)) / 1000.0
    year_days = {
        "crypto": 365, "fx": 365, "us": 252, "cn": 244,
        "hk": 246, "futures": 244, "index": 244, "etf": 244,
    }.get(market, 252)
    session_hours = {
        "crypto": 24.0, "fx": 24.0, "us": 6.5, "cn": 4.0,
        "hk": 5.5, "futures": 6.75, "index": 4.0, "etf": 4.0,
    }.get(market, 6.5)
    if median_sec >= 20 * 3600:  # 日线 / 周线
        return year_days / max(median_sec / 86_400.0, 1e-6)
    hours_per_bar = max(median_sec / 3600.0, 1e-6)
    return year_days * session_hours / hours_per_bar


def compute_stats(
    equity: pd.Series,
    trades: pd.DataFrame,
    bars_per_year: float,
    exposure: float = 0.0,
    initial_cash: float = 1_000_000.0,
    buy_hold_return: float | None = None,
) -> dict:
    eq = equity.astype(float)
    ret = eq.pct_change().dropna()
    total_return = float(eq.iloc[-1] / initial_cash - 1.0)
    years = max(len(eq) / max(bars_per_year, 1e-9), 1e-9)
    cagr = float((max(eq.iloc[-1], 1e-9) / initial_cash) ** (1.0 / years) - 1.0)

    std = float(ret.std(ddof=0))
    ann_vol = std * math.sqrt(bars_per_year)
    sharpe = (float(ret.mean()) * bars_per_year / (ann_vol)) if std > 0 else 0.0
    downside = ret[ret < 0]
    dstd = float(downside.std(ddof=0)) if len(downside) > 1 else 0.0
    sortino = (float(ret.mean()) * bars_per_year / (dstd * math.sqrt(bars_per_year))) if dstd > 0 else 0.0

    dd = eq / eq.cummax() - 1.0
    max_dd = float(dd.min())

    n_trades = 0 if trades is None or trades.empty else int(len(trades))
    if n_trades:
        pnl = trades["pnl"].astype(float)
        wins = pnl[pnl > 0]
        losses = pnl[pnl <= 0]
        win_rate = float(len(wins) / n_trades)
        gross_win = float(wins.sum())
        gross_loss = float(-losses.sum())
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
        avg_ret = float(trades["return_pct"].astype(float).mean())
    else:
        win_rate, profit_factor, avg_ret = 0.0, 0.0, 0.0

    return {
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "win_rate_pct": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 2) if math.isfinite(profit_factor) else None,
        "n_trades": n_trades,
        "avg_trade_ret_pct": round(avg_ret, 2),
        "exposure_pct": round(exposure * 100, 1),
        "buy_hold_pct": round(buy_hold_return * 100, 2) if buy_hold_return is not None else None,
    }
