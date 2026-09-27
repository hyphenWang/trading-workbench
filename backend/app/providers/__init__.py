"""数据源注册表：把品种全名前缀路由到对应 provider。"""
from __future__ import annotations

import asyncio

from app.models import SymbolInfo
from app.providers.base import Provider
from app.providers.binance import BinanceProvider
from app.providers.cn_provider import AkshareProvider
from app.providers.yahoo_provider import YahooProvider

_binance = BinanceProvider()
_yahoo = YahooProvider()
_ak = AkshareProvider()

_PROVIDERS: list[Provider] = [_binance, _yahoo, _ak]
_BY_PREFIX: dict[str, Provider] = {}
for _p in _PROVIDERS:
    for _prefix in _p.prefixes:
        _BY_PREFIX[_prefix] = _p


def parse_symbol(full_symbol: str) -> tuple[str, str]:
    prefix, _, ticker = full_symbol.partition(":")
    if not prefix or not ticker or prefix not in _BY_PREFIX:
        raise KeyError(
            f"无法解析品种 {full_symbol}（支持前缀: {', '.join(sorted(_BY_PREFIX))}）"
        )
    return prefix, ticker


def get_provider(full_symbol: str) -> Provider:
    return _BY_PREFIX[parse_symbol(full_symbol)[0]]


async def search_all(query: str, limit: int = 30) -> list[SymbolInfo]:
    """并行搜索所有数据源，单个源失败不影响整体。"""

    async def _safe(p: Provider) -> list[SymbolInfo]:
        try:
            return await p.search(query, limit=limit)
        except Exception:
            return []

    results = await asyncio.gather(*(_safe(p) for p in _PROVIDERS))
    seen: set[str] = set()
    merged: list[SymbolInfo] = []
    for hits in results:
        for hit in hits:
            if hit.symbol in seen:
                continue
            seen.add(hit.symbol)
            merged.append(hit)
    return merged[:limit]
