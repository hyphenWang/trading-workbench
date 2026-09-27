"""统一的数据模型：所有数据源适配器都必须产出这里定义的格式。"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel

# 全局统一的周期表示（provider 内部再映射为各家原生格式）
INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


class Bar(BaseModel):
    """一根 K 线。time 为 UTC 毫秒时间戳（周期起点）。"""

    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class SymbolInfo(BaseModel):
    """交易品种元信息，同时承载前端 resolveSymbol 需要的字段。"""

    symbol: str  # 全名，如 BINANCE:BTCUSDT
    ticker: str  # 数据源内部代码，如 BTCUSDT
    provider: str  # 数据源标识，如 BINANCE / YAHOO / AKSHARE
    name: str
    description: str = ""
    exchange: str = ""
    market: Literal["crypto", "us", "cn", "hk", "fx", "futures", "index", "etf"] = "us"
    type: str = "stock"  # tradingview 语义: stock / crypto / forex / futures / index
    session: str = "24x7"  # 仅作展示用途
    timezone: str = "Etc/UTC"
    pricescale: int = 100  # 价格精度：10^n，100 表示 0.01
    minmov: int = 1
    has_intraday: bool = True
    supported_resolutions: list[str] = INTERVALS
    data_status: str = "streaming"  # streaming | endofday
    volume_precision: int = 2


class SearchHit(BaseModel):
    symbol: str
    name: str
    exchange: str
    provider: str
    type: str
