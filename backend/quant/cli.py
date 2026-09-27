"""命令行回测。

示例：
  uv run --directory backend python -m quant.cli \
      --symbol BINANCE:BTCUSDT --interval 1d \
      --strategy sma_cross --param fast=20 --param slow=60 \
      --start 2022-01-01 --allow-short
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import numpy as np
import pandas as pd

from app.models import INTERVAL_MS
from app.providers import get_provider
from quant import engine as bt_engine
from quant import metrics as bt_metrics
from quant import strategies as bt_strategies


def main() -> int:
    parser = argparse.ArgumentParser(description="本地交易工作台 - 命令行回测")
    parser.add_argument("--symbol", required=True, help="品种全名，如 BINANCE:BTCUSDT / CN:600519")
    parser.add_argument("--interval", default="1d", help="周期: 1m/5m/15m/1h/4h/1d/1w")
    parser.add_argument("--strategy", required=True, help=f"策略: {', '.join(bt_strategies.SPECS)}")
    parser.add_argument("--param", action="append", default=[], help="策略参数 k=v，可多次")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--fee", type=float, default=0.001, help="单边手续费率，默认 0.001")
    parser.add_argument("--slippage", type=float, default=0.0, help="单边滑点率")
    parser.add_argument("--cash", type=float, default=1_000_000, help="初始资金")
    parser.add_argument("--size-pct", type=float, default=1.0, help="每次开仓资金比例 0-1")
    parser.add_argument("--allow-short", action="store_true", help="允许做空")
    parser.add_argument("--save", default=None, help="结果保存为 JSON 文件路径")
    args = parser.parse_args()

    params: dict = {}
    for kv in args.param:
        k, _, v = kv.partition("=")
        params[k.strip()] = v.strip()

    provider = get_provider(args.symbol)
    end_ms = (
        int(pd.Timestamp(args.end, tz="UTC").timestamp() * 1000)
        if args.end else int(time.time() * 1000)
    )
    start_ms = (
        int(pd.Timestamp(args.start, tz="UTC").timestamp() * 1000)
        if args.start else end_ms - 3 * 365 * 86_400_000
    )

    try:
        info = asyncio.run(provider.resolve(args.symbol))
        bars = asyncio.run(provider.history(args.symbol, args.interval, start_ms, end_ms))
    except Exception as e:
        print(f"[错误] 获取数据失败: {e}", file=sys.stderr)
        return 1
    if len(bars) < 30:
        print(f"[错误] 历史数据不足（{len(bars)} 根）", file=sys.stderr)
        return 1

    df = pd.DataFrame([b.model_dump() for b in bars])
    signals = bt_strategies.apply_strategy(args.strategy, df, params)
    result = bt_engine.run_backtest(
        df, signals["long_entry"], signals["long_exit"],
        signals["short_entry"] if args.allow_short else None,
        signals["short_exit"] if args.allow_short else None,
        fee=args.fee, slippage=args.slippage,
        initial_cash=args.cash, size_pct=args.size_pct,
    )
    bpy = bt_metrics.estimate_bars_per_year(df["time"].to_numpy(), info.market)
    buy_hold = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1.0)
    stats = bt_metrics.compute_stats(
        result["equity"], result["trades"], bpy,
        exposure=result["exposure"], initial_cash=args.cash,
        buy_hold_return=buy_hold,
    )

    print(f"=== 回测: {args.symbol} {args.interval} {args.strategy} {params or ''} ===")
    print(f"数据区间: {pd.Timestamp(df['time'].iloc[0], unit='ms').date()} "
          f"~ {pd.Timestamp(df['time'].iloc[-1], unit='ms').date()}  ({len(df)} 根)")
    print("-" * 46)
    for key, label in bt_metrics.METRIC_LABELS_ZH.items():
        val = stats.get(key)
        if val is None:
            continue
        if key in ("total_return_pct", "cagr_pct", "max_drawdown_pct", "win_rate_pct",
                   "exposure_pct", "buy_hold_pct", "ann_vol_pct", "avg_trade_ret_pct"):
            print(f"  {label:<10} {val:>12.2f}%")
        else:
            print(f"  {label:<10} {val:>12}")
    trades = result["trades"]
    if not trades.empty:
        print("-" * 46)
        print("最近 5 笔交易:")
        for r in trades.tail(5).to_dict("records"):
            d_in = pd.Timestamp(r["entry_time"], unit="ms").date()
            d_out = pd.Timestamp(r["exit_time"], unit="ms").date()
            print(f"  {d_in} -> {d_out} {r['side']:<5} "
                  f"收益 {r['return_pct']:>7.2f}%  盈亏 {r['pnl']:>12.2f}")

    if args.save:
        equity_pts = [[int(ts.timestamp() * 1000), float(v)] for ts, v in result["equity"].items()]
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump({"metrics": stats, "equity": equity_pts,
                       "trades": trades.to_dict("records")}, f, ensure_ascii=False, indent=2)
        print(f"已保存: {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
