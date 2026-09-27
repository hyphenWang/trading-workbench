"""向量化事件回测引擎。

核心纪律（避免前视偏差）：
  信号在第 i 根收盘时计算完成，第 i+1 根以开盘价成交 —— 引擎内部统一
  使用 signal[i-1] 决定第 i 根的动作，策略层只需输出逐 bar 信号序列。

撮合模型：整单位资金比例入场（size_pct）、按比例手续费 fee、按比例滑点
slippage；支持多空；期末未平仓仓位按最后一根收盘价强制平仓并计入交易明细。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _signal_array(sig, n: int) -> np.ndarray:
    if sig is None:
        return np.zeros(n, dtype=bool)
    arr = np.asarray(sig)
    if arr.dtype != bool:
        arr = arr.astype(float)
        arr = np.nan_to_num(arr, nan=0.0) != 0
    if len(arr) != n:
        raise ValueError(f"信号长度 {len(arr)} 与数据长度 {n} 不一致")
    return arr


def run_backtest(
    df: pd.DataFrame,
    long_entry,
    long_exit,
    short_entry=None,
    short_exit=None,
    *,
    fee: float = 0.001,
    slippage: float = 0.0,
    initial_cash: float = 1_000_000.0,
    size_pct: float = 1.0,
) -> dict:
    """df 需含列: time(ms), open, high, low, close。返回 equity/trades/exposure。"""
    n = len(df)
    if n < 2:
        raise ValueError("数据不足（至少需要 2 根 K 线）")
    open_ = df["open"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    times = df["time"].to_numpy()
    le = _signal_array(long_entry, n)
    lx = _signal_array(long_exit, n)
    se = _signal_array(short_entry, n)
    sx = _signal_array(short_exit, n)

    cash = float(initial_cash)
    qty = 0.0  # 正=多头，负=空头
    entry_px = entry_time = 0.0
    entry_i = -1
    equity = np.empty(n)
    equity[0] = cash
    trades: list[dict] = []
    bars_in_pos = 0

    def _close_position(i: int, raw_px: float, is_long: bool) -> None:
        nonlocal cash, qty, bars_in_pos
        px = raw_px * (1 + slippage) if not is_long else raw_px * (1 - slippage)
        q = abs(qty)
        if is_long:
            proceeds = q * px * (1 - fee)
            cost = q * entry_px * (1 + fee)
            cash += proceeds
            pnl = proceeds - cost
        else:
            cover_cost = q * px * (1 + fee)
            proceeds = q * entry_px * (1 - fee)
            cash -= cover_cost
            pnl = proceeds - cover_cost
        trades.append(
            {
                "entry_time": int(entry_time),
                "exit_time": int(times[i]),
                "side": "long" if is_long else "short",
                "entry_price": float(entry_px),
                "exit_price": float(px),
                "bars": int(bars_in_pos),
                "pnl": float(pnl),
                "return_pct": float(pnl / cost * 100 if is_long else pnl / proceeds * 100),
                "closed_at_end": i == n - 1 and raw_px == close[-1],
            }
        )
        qty = 0.0
        bars_in_pos = 0

    for i in range(1, n):
        # 先平仓（信号取上一根 bar 的判定结果，本根开盘成交）
        if qty > 0 and lx[i - 1]:
            _close_position(i, open_[i], is_long=True)
        elif qty < 0 and sx[i - 1]:
            _close_position(i, open_[i], is_long=False)
        # 后开仓
        if qty == 0:
            if le[i - 1]:
                px = open_[i] * (1 + slippage)
                budget = cash * float(size_pct)
                q = budget / (px * (1 + fee))
                cash -= q * px * (1 + fee)
                qty, entry_px, entry_time, entry_i, bars_in_pos = q, px, int(times[i]), i, 1
            elif se[i - 1]:
                px = open_[i] * (1 - slippage)
                budget = cash * float(size_pct)
                q = budget / px
                cash += q * px * (1 - fee)
                qty, entry_px, entry_time, entry_i, bars_in_pos = -q, px, int(times[i]), i, 1
        elif qty != 0:
            bars_in_pos += 1
        equity[i] = cash + qty * close[i]

    # 期末强制平仓（按最后收盘价，含手续费/滑点），保证交易统计完整
    if qty != 0:
        _close_position(n - 1, close[-1], is_long=qty > 0)
        equity[n - 1] = cash

    equity_series = pd.Series(
        equity, index=pd.to_datetime(times, unit="ms", utc=True), name="equity"
    )
    exposure = _exposure_of(le, lx, se, sx)
    return {
        "equity": equity_series,
        "trades": pd.DataFrame(trades),
        "exposure": exposure,
    }


def _exposure_of(le, lx, se, sx) -> float:
    """近似持仓占比：信号驱动的状态机重放。"""
    n = len(le)
    held = 0
    state = 0  # 0 空仓 1 多 -1 空
    for i in range(1, n):
        if state == 1 and lx[i - 1]:
            state = 0
        elif state == -1 and sx[i - 1]:
            state = 0
        if state == 0:
            if le[i - 1]:
                state = 1
            elif se[i - 1]:
                state = -1
        if state != 0:
            held += 1
    return held / max(n - 1, 1)
