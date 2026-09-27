"""HTTP API 路由：品种搜索/元信息/历史K线/回测。"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.models import INTERVAL_MS, Bar
from app.providers import get_provider, search_all
from quant import engine as bt_engine
from quant import metrics as bt_metrics
from quant import optimize as bt_optimize
from quant import strategies as bt_strategies

router = APIRouter(prefix="/api")

# 历史请求的进程内缓存（同一 chart/backtest 反复请求时避免打爆上游）
_history_cache: dict[str, tuple[float, list[Bar]]] = {}
_HISTORY_TTL = 60.0


@router.get("/symbols")
async def api_search(query: str = "", limit: int = Query(30, ge=1, le=100)):
    try:
        hits = await search_all(query, limit=limit)
        return {"symbols": [h.model_dump() for h in hits]}
    except Exception as e:  # pragma: no cover
        raise HTTPException(500, f"搜索失败: {e}")


@router.get("/symbol")
async def api_symbol_info(symbol: str):
    try:
        provider = get_provider(symbol)
        info = await provider.resolve(symbol)
        return info.model_dump()
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"解析品种失败: {e}")


@router.get("/history")
async def api_history(
    symbol: str,
    interval: str,
    to: float = Query(..., description="结束时间，Unix 秒"),
    countback: int = Query(500, ge=1, le=5000),
    backtest: bool = Query(False, description="回测模式：忽略 countback，取 from 到 to 全量"),
    from_: float | None = Query(None, alias="from", description="起始时间，Unix 秒"),
):
    try:
        interval_ms = INTERVAL_MS.get(interval)
        if interval_ms is None:
            raise ValueError(f"不支持的周期 {interval}")
        end_ms = int(to * 1000)
        if backtest and from_ is not None:
            start_ms = int(from_ * 1000)
        else:
            # countback 语义：至少给出截止 to 的 countback 根
            start_ms = int(to * 1000) - (countback + 5) * interval_ms
            if from_ is not None:
                start_ms = min(start_ms, int(from_ * 1000))

        cache_key = f"{symbol}|{interval}|{start_ms}|{end_ms}|{backtest}"
        cached = _history_cache.get(cache_key)
        now = time.time()
        if cached and now - cached[0] < _HISTORY_TTL:
            bars = cached[1]
        else:
            provider = get_provider(symbol)
            bars = await provider.history(symbol, interval, start_ms, end_ms)
            if len(_history_cache) > 500:
                _history_cache.clear()
            _history_cache[cache_key] = (now, bars)
        return {
            "bars": [b.model_dump() for b in bars],
            "noData": len(bars) == 0,
            "next_time": bars[0].time if bars else None,
        }
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"获取历史数据失败: {e}")


@router.get("/strategies")
async def api_strategies():
    return {
        "strategies": [
            {
                "name": s.name,
                "label": s.label,
                "description": s.description,
                "supports_short": s.supports_short,
                "params": [
                    {"key": p.key, "label": p.label, "type": p.type, "default": p.default}
                    for p in s.params
                ],
            }
            for s in bt_strategies.SPECS.values()
        ]
    }


class BacktestRequest(BaseModel):
    symbol: str
    interval: str = "1d"
    strategy: str
    params: dict = Field(default_factory=dict)
    start: str | None = None  # YYYY-MM-DD
    end: str | None = None
    fee: float = Field(0.001, ge=0, le=0.05)
    slippage: float = Field(0.0, ge=0, le=0.05)
    initial_cash: float = Field(1_000_000.0, gt=0)
    size_pct: float = Field(1.0, gt=0, le=1.0)
    allow_short: bool = False


@router.post("/backtest")
async def api_backtest(req: BacktestRequest):
    try:
        provider = get_provider(req.symbol)
        info = await provider.resolve(req.symbol)
        end_ms = (
            int(pd.Timestamp(req.end, tz="UTC").timestamp() * 1000)
            if req.end
            else int(time.time() * 1000)
        )
        start_ms = (
            int(pd.Timestamp(req.start, tz="UTC").timestamp() * 1000)
            if req.start
            else end_ms - 3 * 365 * 86_400_000
        )
        bars = await provider.history(req.symbol, req.interval, start_ms, end_ms)
        if len(bars) < 30:
            raise ValueError(
                f"历史数据不足（仅 {len(bars)} 根），无法回测。请检查品种/周期或扩大时间范围。"
            )
        df = pd.DataFrame([b.model_dump() for b in bars])
        signals = bt_strategies.apply_strategy(req.strategy, df, req.params)
        result = bt_engine.run_backtest(
            df,
            signals["long_entry"],
            signals["long_exit"],
            signals["short_entry"] if req.allow_short else None,
            signals["short_exit"] if req.allow_short else None,
            fee=req.fee,
            slippage=req.slippage,
            initial_cash=req.initial_cash,
            size_pct=req.size_pct,
        )
        bpy = bt_metrics.estimate_bars_per_year(
            df["time"].to_numpy(), info.market
        )
        buy_hold = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1.0)
        stats = bt_metrics.compute_stats(
            result["equity"], result["trades"], bpy,
            exposure=result["exposure"],
            initial_cash=req.initial_cash,
            buy_hold_return=buy_hold,
        )
        equity = result["equity"]
        equity_pts = [
            [int(ts.timestamp() * 1000), float(v)] for ts, v in equity.items()
        ]
        trades = (
            []
            if result["trades"].empty
            else [
                {
                    "entry_time": int(r["entry_time"]),
                    "exit_time": int(r["exit_time"]),
                    "side": r["side"],
                    "entry_price": round(float(r["entry_price"]), 8),
                    "exit_price": round(float(r["exit_price"]), 8),
                    "bars": int(r["bars"]),
                    "pnl": round(float(r["pnl"]), 2),
                    "return_pct": round(float(r["return_pct"]), 2),
                }
                for r in result["trades"].to_dict("records")
            ]
        )
        return {
            "symbol": req.symbol,
            "interval": req.interval,
            "strategy": req.strategy,
            "params": req.params,
            "metrics": stats,
            "equity": equity_pts,
            "trades": trades,
            "bar_count": len(df),
            "from": int(df["time"].iloc[0]),
            "to": int(df["time"].iloc[-1]),
        }
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"回测失败: {e}")


class OptimizeRequest(BacktestRequest):
    param_grid: dict[str, list[float]] = Field(default_factory=dict)
    train_bars: int = Field(500, ge=150, le=5000)
    test_bars: int = Field(250, ge=50, le=2000)
    metric: str = "sharpe"


@router.post("/optimize")
async def api_optimize(req: OptimizeRequest):
    """Walk-Forward 参数寻优：训练窗选参 -> 样本外测试 -> 过拟合诊断。"""
    try:
        provider = get_provider(req.symbol)
        info = await provider.resolve(req.symbol)
        end_ms = (
            int(pd.Timestamp(req.end, tz="UTC").timestamp() * 1000)
            if req.end
            else int(time.time() * 1000)
        )
        start_ms = (
            int(pd.Timestamp(req.start, tz="UTC").timestamp() * 1000)
            if req.start
            else end_ms - 5 * 365 * 86_400_000
        )
        bars = await provider.history(req.symbol, req.interval, start_ms, end_ms)
        df = pd.DataFrame([b.model_dump() for b in bars])
        if len(df) < req.train_bars + 2 * req.test_bars:
            raise ValueError(
                f"历史数据不足（{len(df)} 根），至少需要 训练+2×测试 = "
                f"{req.train_bars + 2 * req.test_bars} 根"
            )
        # 网格参数类型规整
        grid = {
            k: [float(v) for v in vs] for k, vs in (req.param_grid or {}).items() if vs
        }
        result = bt_optimize.walk_forward(
            df, info.market, req.strategy, grid,
            train_bars=req.train_bars, test_bars=req.test_bars,
            fee=req.fee, slippage=req.slippage, allow_short=req.allow_short,
            initial_cash=req.initial_cash, size_pct=req.size_pct,
            metric=req.metric,
        )
        result["symbol"] = req.symbol
        result["interval"] = req.interval
        result["strategy"] = req.strategy
        result["bar_count"] = len(df)
        return result
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"寻优失败: {e or type(e).__name__}")
