"""Yahoo Finance 行情：美股 / 指数 / 外汇 / 部分加密与商品期货。

免费可用但行情有延迟（约 15 分钟）；分钟级数据有历史跨度限制。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from app.models import Bar, SymbolInfo
from app.providers.base import Provider

# yfinance 原生周期映射；4h 不支持
_INTERVAL_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "1d": "1d", "1w": "1wk"}
# yfinance 对分钟级数据的最大回看跨度（毫秒）
_MAX_SPAN_MS = {
    "1m": 7 * 86_400_000,
    "5m": 60 * 86_400_000,
    "15m": 60 * 86_400_000,
    "1h": 730 * 86_400_000,
}

_STATIC = [
    "AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN", "META", "BRK-B",
    "SPY", "QQQ", "DIA", "IWM",
    "BTC-USD", "ETH-USD", "SOL-USD",
    "EURUSD=X", "USDJPY=X", "USDCNH=X", "GBPUSD=X",
    "GC=F", "SI=F", "CL=F", "ES=F", "NQ=F",
    "^GSPC", "^NDX", "^DJI", "^HSI", "^N225",
]


def _kind(ticker: str) -> str:
    t = ticker.upper()
    if t.endswith("=X"):
        return "forex"
    if t.endswith("=F"):
        return "futures"
    if t.startswith("^"):
        return "index"
    if "-USD" in t:
        return "crypto"
    return "stock"


class YahooProvider(Provider):
    prefixes = ("YAHOO",)
    realtime_mode = "poll"
    resolutions = ["1m", "5m", "15m", "1h", "1d", "1w"]

    def __init__(self) -> None:
        self._resolve_cache: dict[str, SymbolInfo] = {}

    async def search(self, query: str, limit: int = 30) -> list[SymbolInfo]:
        q = query.strip().upper()
        out: list[SymbolInfo] = []
        for t in _STATIC:
            if q and q not in t:
                continue
            try:
                out.append(await self.resolve(f"YAHOO:{t}"))
            except Exception:
                continue
            if len(out) >= limit:
                break
        return out

    async def resolve(self, full_symbol: str) -> SymbolInfo:
        ticker = full_symbol.split(":", 1)[-1].upper()
        cached = self._resolve_cache.get(ticker)
        if cached:
            return cached
        kind = _kind(ticker)
        fx = kind == "forex"
        info = SymbolInfo(
            symbol=f"YAHOO:{ticker}",
            ticker=ticker,
            provider="YAHOO",
            name=ticker,
            description={"forex": "外汇", "futures": "商品/指数期货", "index": "指数",
                         "crypto": "加密货币", "stock": "美股"}.get(kind, ticker),
            exchange="YAHOO",
            market={"forex": "fx", "futures": "futures", "index": "us",
                    "crypto": "crypto", "stock": "us"}.get(kind, "us"),
            type=kind if kind != "index" else "index",
            session="24x7" if kind in ("forex", "crypto") else "us-session",
            timezone="America/New_York" if kind in ("stock", "futures", "index") else "Etc/UTC",
            pricescale=100_000 if fx else 100,
            has_intraday=True,
            supported_resolutions=self.resolutions,
            data_status="streaming",  # 实际为延迟行情
            volume_precision=0 if fx else 2,
        )
        self._resolve_cache[ticker] = info
        return info

    async def history(
        self, full_symbol: str, interval: str, start_ms: int, end_ms: int
    ) -> list[Bar]:
        native = _INTERVAL_MAP.get(interval)
        if native is None:
            raise ValueError(f"Yahoo 数据源不支持周期 {interval}（可用: 1m/5m/15m/1h/1d/1w）")
        ticker = full_symbol.split(":", 1)[-1].upper()
        # 钳制分钟级数据的跨度，超限 yfinance 会直接报错
        max_span = _MAX_SPAN_MS.get(interval)
        if max_span and end_ms - start_ms > max_span:
            start_ms = end_ms - max_span

        def _fetch() -> pd.DataFrame:
            start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
            end = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
            return yf.Ticker(ticker).history(
                start=start, end=end, interval=native, auto_adjust=False
            )

        df = await asyncio.to_thread(_fetch)
        if df is None or df.empty:
            return []
        idx = df.index
        if getattr(idx, "tz", None) is None:
            idx = idx.tz_localize("UTC")
        else:
            idx = idx.tz_convert("UTC")
        bars: list[Bar] = []
        for ts, row in zip(idx, df.itertuples(index=False)):
            t_ms = int(ts.timestamp() * 1000)
            if t_ms < start_ms or t_ms > end_ms:
                continue
            vol = float(getattr(row, "Volume", 0) or 0)
            if pd.isna(vol):
                vol = 0.0
            bars.append(
                Bar(
                    time=t_ms,
                    open=float(row.Open),
                    high=float(row.High),
                    low=float(row.Low),
                    close=float(row.Close),
                    volume=vol,
                )
            )
        bars.sort(key=lambda b: b.time)
        return bars
