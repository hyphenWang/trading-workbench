"""Binance 现货行情：免费公开 API，无需 Key，支持实时 WebSocket。"""
from __future__ import annotations

import time

import httpx

from app.config import BINANCE_BASE
from app.models import INTERVALS, Bar, SymbolInfo
from app.providers.base import Provider

_QUOTE_WHITELIST = ("USDT", "USDC", "FDUSD")


class BinanceProvider(Provider):
    prefixes = ("BINANCE",)
    realtime_mode = "ws"
    resolutions = INTERVALS

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=BINANCE_BASE, timeout=15)
        self._info_cache: dict = {"t": 0.0, "symbols": {}}

    async def _exchange_info(self) -> dict[str, dict]:
        now = time.time()
        if not self._info_cache["symbols"] or now - self._info_cache["t"] > 3600:
            resp = await self._client.get("/api/v3/exchangeInfo")
            resp.raise_for_status()
            data = {s["symbol"]: s for s in resp.json()["symbols"]}
            self._info_cache = {"t": now, "symbols": data}
        return self._info_cache["symbols"]

    async def search(self, query: str, limit: int = 30) -> list[SymbolInfo]:
        try:
            info = await self._exchange_info()
        except Exception:
            return []  # 网络不通时搜索降级为空，不影响其他数据源
        q = query.strip().upper()
        hits: list[SymbolInfo] = []
        for s in sorted(info.values(), key=lambda x: x["symbol"]):
            if s.get("status") != "TRADING" or s.get("quoteAsset") not in _QUOTE_WHITELIST:
                continue
            if q and q not in s["symbol"] and q not in s.get("baseAsset", ""):
                continue
            hits.append(
                SymbolInfo(
                    symbol=f"BINANCE:{s['symbol']}",
                    ticker=s["symbol"],
                    provider="BINANCE",
                    name=s["symbol"],
                    description=f"{s['baseAsset']} / {s['quoteAsset']}",
                    exchange="BINANCE",
                    market="crypto",
                    type="crypto",
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def resolve(self, full_symbol: str) -> SymbolInfo:
        ticker = full_symbol.split(":", 1)[-1].upper()
        info = await self._exchange_info()
        s = info.get(ticker)
        if not s:
            raise KeyError(f"未知交易对: {ticker}")
        tick = next((f for f in s["filters"] if f["filterType"] == "PRICE_FILTER"), None)
        tick_size = float(tick["tickSize"]) if tick else 0.01
        pricescale = max(1, round(1 / tick_size)) if tick_size > 0 else 100
        return SymbolInfo(
            symbol=f"BINANCE:{ticker}",
            ticker=ticker,
            provider="BINANCE",
            name=ticker,
            description=f"{s['baseAsset']} / {s['quoteAsset']}",
            exchange="BINANCE",
            market="crypto",
            type="crypto",
            session="24x7",
            timezone="Etc/UTC",
            pricescale=pricescale,
            has_intraday=True,
            supported_resolutions=INTERVALS,
            data_status="streaming",
            volume_precision=4,
        )

    async def history(
        self, full_symbol: str, interval: str, start_ms: int, end_ms: int
    ) -> list[Bar]:
        if interval not in INTERVALS:
            raise ValueError(f"Binance 不支持周期 {interval}")
        ticker = full_symbol.split(":", 1)[-1].upper()
        bars: list[Bar] = []
        cursor = end_ms
        while cursor > start_ms and len(bars) < 10_000:
            resp = await self._client.get(
                "/api/v3/klines",
                params={
                    "symbol": ticker,
                    "interval": interval,
                    "endTime": cursor,
                    "limit": 1000,
                },
            )
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                break
            chunk = [
                Bar(
                    time=int(r[0]),
                    open=float(r[1]),
                    high=float(r[2]),
                    low=float(r[3]),
                    close=float(r[4]),
                    volume=float(r[5]),
                )
                for r in rows
                if int(r[0]) <= end_ms
            ]
            bars = chunk + bars
            cursor = chunk[0].time - 1
            if len(rows) < 1000:
                break
        return [b for b in bars if b.time >= start_ms]
