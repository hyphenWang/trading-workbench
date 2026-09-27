"""内置策略库。

每个策略输出四组逐 bar 信号（布尔序列，索引与 df 对齐）：
  long_entry / long_exit / short_entry / short_exit
信号只表达"这根收盘时想做什么"，成交由引擎推迟到下一根开盘。
short_* 仅在允许做空时使用；多数策略通过对称反转生成空头信号。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from quant import indicators as ta


@dataclass
class ParamSpec:
    key: str
    label: str
    type: str  # int | float
    default: float | int


@dataclass
class StrategySpec:
    name: str
    label: str
    description: str = ""
    params: list[ParamSpec] = field(default_factory=list)
    supports_short: bool = True


def _cross_up(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def _cross_down(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))


def _mirrored(long_entry: pd.Series, long_exit: pd.Series) -> dict:
    """把多头规则对称映射为空头（逆序进出）。"""
    return {"short_entry": long_exit, "short_exit": long_entry}


SPECS: dict[str, StrategySpec] = {
    "sma_cross": StrategySpec(
        "sma_cross", "双均线交叉 (SMA)",
        "快线上穿慢线做多，下穿平仓/做空",
        [ParamSpec("fast", "快线周期", "int", 20), ParamSpec("slow", "慢线周期", "int", 60)],
    ),
    "ema_cross": StrategySpec(
        "ema_cross", "双均线交叉 (EMA)",
        "EMA 快慢线交叉",
        [ParamSpec("fast", "快线周期", "int", 12), ParamSpec("slow", "慢线周期", "int", 50)],
    ),
    "macd": StrategySpec(
        "macd", "MACD",
        "DIF 上穿 DEA 做多，下穿平仓/做空",
        [ParamSpec("fast", "快线", "int", 12), ParamSpec("slow", "慢线", "int", 26),
         ParamSpec("signal", "信号线", "int", 9)],
    ),
    "rsi_reversion": StrategySpec(
        "rsi_reversion", "RSI 超卖回归",
        "RSI 自超卖区上穿时买入，进入超买区离场",
        [ParamSpec("period", "RSI 周期", "int", 14),
         ParamSpec("buy_below", "超卖阈值", "int", 30),
         ParamSpec("exit_above", "超买阈值", "int", 70)],
    ),
    "donchian_breakout": StrategySpec(
        "donchian_breakout", "唐奇安通道突破",
        "收盘价突破前 N 根最高价做多，跌破前 N 根最低价离场",
        [ParamSpec("window", "通道窗口", "int", 20)],
    ),
    "bollinger_reversion": StrategySpec(
        "bollinger_reversion", "布林带均值回归",
        "价格自下轨外回收升穿下轨时买入，触及中轨离场",
        [ParamSpec("window", "周期", "int", 20), ParamSpec("k", "标准差倍数", "float", 2.0)],
    ),
    "supertrend": StrategySpec(
        "supertrend", "SuperTrend",
        "趋势方向翻多买入，翻空离场/做空",
        [ParamSpec("period", "ATR 周期", "int", 10),
         ParamSpec("multiplier", "倍数", "float", 3.0)],
    ),
}


def _int(params: dict, key: str, default) -> int:
    return int(round(float(params.get(key, default))))


def _float(params: dict, key: str, default) -> float:
    return float(params.get(key, default))


def apply_strategy(name: str, df: pd.DataFrame, params: dict) -> dict[str, pd.Series]:
    if name not in SPECS:
        raise KeyError(f"未知策略: {name}")
    close = df["close"]

    if name == "sma_cross":
        fast = ta.sma(close, _int(params, "fast", 20))
        slow = ta.sma(close, _int(params, "slow", 60))
        long_entry = _cross_up(fast, slow)
        long_exit = _cross_down(fast, slow)
    elif name == "ema_cross":
        fast = ta.ema(close, _int(params, "fast", 12))
        slow = ta.ema(close, _int(params, "slow", 50))
        long_entry = _cross_up(fast, slow)
        long_exit = _cross_down(fast, slow)
    elif name == "macd":
        m = ta.macd(close, _int(params, "fast", 12), _int(params, "slow", 26), _int(params, "signal", 9))
        long_entry = _cross_up(m["macd"], m["signal"])
        long_exit = _cross_down(m["macd"], m["signal"])
    elif name == "rsi_reversion":
        r = ta.rsi(close, _int(params, "period", 14))
        buy_th = _int(params, "buy_below", 30)
        exit_th = _int(params, "exit_above", 70)
        long_entry = _cross_up(r, pd.Series(float(buy_th), index=df.index))
        long_exit = r > exit_th
    elif name == "donchian_breakout":
        w = _int(params, "window", 20)
        ch = ta.donchian(df, w)
        long_entry = close > ch["upper"]
        long_exit = close < ch["lower"]
        # 反向：跌破下轨做空 / 升破上轨平空
        return {
            "long_entry": (long_entry.fillna(False)).astype(bool),
            "long_exit": (long_exit.fillna(False)).astype(bool),
            "short_entry": (long_exit.fillna(False)).astype(bool),
            "short_exit": (long_entry.fillna(False)).astype(bool),
        }
    elif name == "bollinger_reversion":
        b = ta.bollinger(close, _int(params, "window", 20), _float(params, "k", 2.0))
        long_entry = _cross_up(close, b["lower"])
        long_exit = close >= b["mid"]
        short_entry = _cross_down(close, b["upper"])
        short_exit = close <= b["mid"]
        return {
            "long_entry": long_entry.fillna(False).astype(bool),
            "long_exit": long_exit.fillna(False).astype(bool),
            "short_entry": short_entry.fillna(False).astype(bool),
            "short_exit": short_exit.fillna(False).astype(bool),
        }
    else:  # supertrend
        st = ta.supertrend(df, _int(params, "period", 10), _float(params, "multiplier", 3.0))
        up = st["direction"] == 1
        down = st["direction"] == -1
        long_entry = up & (st["direction"].shift(1) == -1)
        long_exit = down & (st["direction"].shift(1) == 1)
        return {
            "long_entry": long_entry.fillna(False).astype(bool),
            "long_exit": long_exit.fillna(False).astype(bool),
            "short_entry": long_exit.fillna(False).astype(bool),
            "short_exit": long_entry.fillna(False).astype(bool),
        }

    short = _mirrored(long_entry, long_exit)
    return {
        "long_entry": long_entry.fillna(False).astype(bool),
        "long_exit": long_exit.fillna(False).astype(bool),
        "short_entry": short["short_entry"].fillna(False).astype(bool),
        "short_exit": short["short_exit"].fillna(False).astype(bool),
    }
