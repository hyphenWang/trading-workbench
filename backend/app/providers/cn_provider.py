"""A股 / 港股 / ETF / 指数 / 国内期货行情（基于 akshare，日线级）。

前缀约定（品种全名 `前缀:代码`）：
  CN:600519   A股（东财，前复权）
  HK:00700    港股（东财，前复权）
  ETF:510300  场内基金（东财，前复权）
  IDX:000300  指数
  FUT:RB0     期货主力连续（新浪）；FUT:RB2510 具体合约

akshare 导入较慢，这里做惰性导入；实时推送暂不提供（日线收盘后更新）。
"""
from __future__ import annotations

import asyncio
import os
import time

import pandas as pd

from app.models import Bar, SymbolInfo
from app.providers.base import Provider

# 国内数据源始终直连：requests 默认会走系统代理，代理软件未运行时反而连不通
_CN_DIRECT_HOSTS = (
    "eastmoney.com", "sina.com.cn", "sina.com", "sinaurl.cn",
    "gtimg.cn", "10jqka.com.cn", "eastmoneyapi.com",
)


def _ensure_cn_direct() -> None:
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    hosts = {h.strip() for h in no_proxy.split(",") if h.strip()}
    hosts.update(_CN_DIRECT_HOSTS)
    value = ",".join(sorted(hosts))
    os.environ["NO_PROXY"] = value
    os.environ["no_proxy"] = value


_ensure_cn_direct()

_STATIC: list[SymbolInfo] = []


def _static_symbols() -> list[SymbolInfo]:
    global _STATIC
    if _STATIC:
        return _STATIC
    items = [
        ("CN", "600519", "贵州茅台", "cn", "stock", "SSE"),
        ("CN", "000001", "平安银行", "cn", "stock", "SZSE"),
        ("CN", "300750", "宁德时代", "cn", "stock", "SZSE"),
        ("CN", "601318", "中国平安", "cn", "stock", "SSE"),
        ("CN", "600036", "招商银行", "cn", "stock", "SSE"),
        ("HK", "00700", "腾讯控股", "hk", "stock", "HKEX"),
        ("HK", "09988", "阿里巴巴-W", "hk", "stock", "HKEX"),
        ("ETF", "510300", "沪深300ETF", "etf", "etf", "SSE"),
        ("ETF", "510500", "中证500ETF", "etf", "etf", "SSE"),
        ("ETF", "159915", "创业板ETF", "etf", "etf", "SZSE"),
        ("IDX", "000001", "上证指数", "index", "index", "SSE"),
        ("IDX", "000300", "沪深300", "index", "index", "SSE"),
        ("IDX", "399006", "创业板指", "index", "index", "SZSE"),
        ("FUT", "RB0", "螺纹钢主力", "futures", "futures", "SHFE"),
        ("FUT", "M0", "豆粕主力", "futures", "futures", "DCE"),
        ("FUT", "CU0", "沪铜主力", "futures", "futures", "SHFE"),
        ("FUT", "AU0", "沪金主力", "futures", "futures", "SHFE"),
        ("FUT", "I0", "铁矿石主力", "futures", "futures", "DCE"),
    ]
    _STATIC = [
        SymbolInfo(
            symbol=f"{p}:{code}",
            ticker=code,
            provider="AKSHARE",
            name=name,
            description=f"{p} {code}",
            exchange=exch,
            market=mkt,
            type=typ,
            timezone="Asia/Shanghai",
            pricescale=1 if p == "FUT" else 100,
            has_intraday=False,
            supported_resolutions=["1d"],
            data_status="endofday",
            volume_precision=0,
        )
        for p, code, name, mkt, typ, exch in items
    ]
    return _STATIC


def _exchange_of(prefix: str, code: str) -> str:
    if prefix == "HK":
        return "HKEX"
    if prefix == "FUT":
        return "FUTURES"
    if prefix == "ETF" or prefix == "IDX":
        return "SSE" if code.startswith(("5", "0")) else "SZSE"
    if code.startswith("6") or code.startswith("9"):
        return "SSE"
    if code.startswith(("0", "3")):
        return "SZSE"
    return "CN"


class AkshareProvider(Provider):
    prefixes = ("CN", "HK", "ETF", "IDX", "FUT")
    realtime_mode = "none"
    resolutions = ["1d"]

    def __init__(self) -> None:
        self._ak = None
        self._list_cache: list[SymbolInfo] | None = None
        self._list_time = 0.0

    def _module(self):
        if self._ak is None:
            import akshare  # 导入耗时较长，惰性加载

            self._ak = akshare
        return self._ak

    async def search(self, query: str, limit: int = 50) -> list[SymbolInfo]:
        hits = list(_static_symbols())
        if self._list_cache is None or time.time() - self._list_time > 86400:
            try:
                df = await asyncio.to_thread(
                    lambda: self._module().stock_info_a_code_name()
                )
                rows = list(df.itertuples(index=False))
            except Exception:
                rows = []
            if rows:
                extra = [
                    SymbolInfo(
                        symbol=f"CN:{str(r[0]).zfill(6)}",
                        ticker=str(r[0]).zfill(6),
                        provider="AKSHARE",
                        name=str(r[1]),
                        exchange=_exchange_of("CN", str(r[0]).zfill(6)),
                        market="cn",
                        type="stock",
                        timezone="Asia/Shanghai",
                        pricescale=100,
                        has_intraday=False,
                        supported_resolutions=["1d"],
                        data_status="endofday",
                        volume_precision=0,
                    )
                    for r in rows
                ]
                self._list_cache = extra
                self._list_time = time.time()
        if self._list_cache:
            hits = hits + self._list_cache
        q = query.strip().lower()
        if q:
            hits = [h for h in hits if q in h.ticker.lower() or q in h.name.lower()]
        return hits[:limit]

    async def resolve(self, full_symbol: str) -> SymbolInfo:
        prefix, code = full_symbol.split(":", 1)
        for s in _static_symbols():
            if s.symbol == full_symbol:
                return s
        if prefix not in ("CN", "HK", "ETF", "IDX", "FUT"):
            raise KeyError(f"未知品种前缀: {prefix}")
        # CN 支持全量代码表反查名称
        if prefix == "CN" and self._list_cache:
            for s in self._list_cache:
                if s.ticker == code:
                    return s
        name = {"CN": "A股", "HK": "港股", "ETF": "ETF", "IDX": "指数", "FUT": "期货"}.get(prefix, code)
        return SymbolInfo(
            symbol=full_symbol,
            ticker=code,
            provider="AKSHARE",
            name=f"{name} {code}",
            exchange=_exchange_of(prefix, code),
            market={"CN": "cn", "HK": "hk", "ETF": "etf", "IDX": "index", "FUT": "futures"}[prefix],
            type={"CN": "stock", "HK": "stock", "ETF": "etf", "IDX": "index", "FUT": "futures"}[prefix],
            timezone="Asia/Shanghai",
            pricescale=1 if prefix == "FUT" else 100,
            has_intraday=False,
            supported_resolutions=["1d"],
            data_status="endofday",
            volume_precision=0,
        )

    async def history(
        self, full_symbol: str, interval: str, start_ms: int, end_ms: int
    ) -> list[Bar]:
        if interval != "1d":
            raise ValueError("A股/港股/期货数据源当前仅支持日线（1d）")
        prefix, code = full_symbol.split(":", 1)
        start_date = pd.Timestamp(start_ms, unit="ms", tz="UTC").strftime("%Y%m%d")
        end_date = pd.Timestamp(end_ms, unit="ms", tz="UTC").strftime("%Y%m%d")

        def _fetch() -> pd.DataFrame:
            ak = self._module()
            if prefix == "CN":
                # 新浪源最稳（东财 kline 接口有风控）；返回全量日线，后面按区间过滤
                if code.startswith("6"):
                    full = "sh" + code
                elif code.startswith(("0", "3")):
                    full = "sz" + code
                else:
                    full = "bj" + code
                return ak.stock_zh_a_daily(symbol=full, adjust="qfq")
            if prefix == "IDX":
                full = ("sh" if code.startswith("0") else "sz") + code
                return ak.stock_zh_index_daily(symbol=full)
            if prefix == "HK":
                try:
                    return ak.stock_hk_daily(symbol=code, adjust="qfq")
                except Exception:
                    return ak.stock_hk_hist(
                        symbol=code, period="daily", start_date=start_date,
                        end_date=end_date, adjust="qfq",
                    )
            if prefix == "ETF":
                return ak.fund_etf_hist_em(
                    symbol=code, period="daily", start_date=start_date,
                    end_date=end_date, adjust="qfq",
                )
            # 期货：0 结尾的主力连续走新浪接口，其余为具体合约
            if code.endswith("0") and len(code) <= 3:
                return ak.futures_main_sina(
                    symbol=code, start_date=start_date, end_date=end_date
                )
            return ak.futures_zh_daily_sina(symbol=code)

        df = await asyncio.to_thread(_fetch)
        if df is None or df.empty:
            return []
        return _df_to_bars(df, start_ms, end_ms)


def _pick_col(df: pd.DataFrame, *keywords: str) -> str | None:
    """按关键词匹配列名（兼容中文列名与新浪英文列名）。"""
    for col in df.columns:
        s = str(col).lower()
        if all(k.lower() in s for k in keywords):
            return col
    return None


def _df_to_bars(df: pd.DataFrame, start_ms: int, end_ms: int) -> list[Bar]:
    date_col = _pick_col(df, "日期") or _pick_col(df, "date")
    open_col = _pick_col(df, "开") or _pick_col(df, "open")
    high_col = _pick_col(df, "高") or _pick_col(df, "high")
    low_col = _pick_col(df, "低") or _pick_col(df, "low")
    close_col = _pick_col(df, "收") or _pick_col(df, "close")
    vol_col = _pick_col(df, "量") or _pick_col(df, "volume")
    if not all([date_col, open_col, high_col, low_col, close_col]):
        raise ValueError(f"akshare 返回了无法解析的列: {list(df.columns)}")
    bars: list[Bar] = []
    for row in df.itertuples(index=False):
        rec = dict(zip(map(str, df.columns), row))
        ts = pd.Timestamp(str(rec[str(date_col)])[:10])
        # 国内市场时间戳按上海时区周期起点折算成 UTC 毫秒
        t_ms = int(ts.tz_localize("Asia/Shanghai").tz_convert("UTC").timestamp() * 1000)
        if t_ms < start_ms or t_ms > end_ms:
            continue
        vol = float(rec.get(str(vol_col), 0) or 0) if vol_col else 0.0
        bars.append(
            Bar(
                time=t_ms,
                open=float(rec[str(open_col)]),
                high=float(rec[str(high_col)]),
                low=float(rec[str(low_col)]),
                close=float(rec[str(close_col)]),
                volume=vol,
            )
        )
    bars.sort(key=lambda b: b.time)
    return bars
