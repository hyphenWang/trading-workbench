"""数据源适配器基类。

所有 provider 返回的 Bar.time 一律为 UTC 毫秒、按时间升序排列；
品种全名使用 `前缀:代码` 形式（如 BINANCE:BTCUSDT、CN:600519、FUT:RB0），
由 registry 负责把前缀路由到对应 provider。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import Bar, SymbolInfo


class Provider(ABC):
    # 前缀 -> provider 由 registry 建立；一个 provider 可注册多个前缀（如 A股/HK/ETF/IDX/FUT）
    prefixes: tuple[str, ...] = ()

    realtime_mode: str = "none"  # ws | poll | none
    resolutions: list[str] = ["1d"]

    @abstractmethod
    async def search(self, query: str, limit: int = 30) -> list[SymbolInfo]:
        """按关键词搜索品种，返回全名 SymbolInfo 列表。"""

    @abstractmethod
    async def resolve(self, full_symbol: str) -> SymbolInfo:
        """解析品种全名 -> SymbolInfo；未知品种抛 KeyError。"""

    @abstractmethod
    async def history(
        self, full_symbol: str, interval: str, start_ms: int, end_ms: int
    ) -> list[Bar]:
        """拉取历史 K 线，升序返回；数据不可得时抛异常或返回空列表。"""
