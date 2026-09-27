"""实时行情枢纽（PubSub）。

职责边界：
  - 上游：Binance WebSocket（聚合连接）+ 各源 REST 轮询兜底，只负责"取到最新 bar"
  - 本地：/ws 上每个客户端连接按 topic 订阅；publish 只向订阅者广播
  - Topic 规则：`{SYMBOL}|{interval}`，如 BINANCE:BTCUSDT|1d，与前端 SocketClient 一致

同一个 topic 无论多少个图表订阅，上游只有一条订阅（WS 流或一个轮询任务）。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time

import websockets
from fastapi import WebSocket

from app.config import BINANCE_WS, REALTIME_WS_ENABLED
from app.models import Bar, INTERVAL_MS
from app.providers import get_provider
from app.providers.binance import BinanceProvider

_BINANCE_STREAM_IDS = {"1m", "5m", "15m", "1h", "4h", "1d", "1w"}


def topic_parts(topic: str) -> tuple[str, str]:
    symbol, _, interval = topic.rpartition("|")
    if not symbol or not interval:
        raise ValueError(f"非法 topic: {topic}")
    return symbol, interval


def stream_id_of(interval: str) -> str:
    if interval not in _BINANCE_STREAM_IDS:
        raise ValueError(f"Binance 不支持周期 {interval}")
    return interval


class Hub:
    def __init__(self) -> None:
        self._subs_by_topic: dict[str, set[WebSocket]] = {}
        self._topics_by_client: dict[WebSocket, set[str]] = {}
        self._poll_tasks: dict[str, asyncio.Task] = {}
        self._bin_streams: set[str] = set()
        self._streams_changed = asyncio.Event()
        self._ws_task: asyncio.Task | None = None

    # ---------- 本地订阅管理 ----------

    async def client_loop(self, ws: WebSocket) -> None:
        await ws.accept()
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                topics = msg.get("topics") or []
                if msg.get("op") == "sub":
                    for t in topics:
                        await self._add(ws, str(t))
                elif msg.get("op") == "unsub":
                    for t in topics:
                        self._remove(ws, str(t))
        except Exception:
            pass
        finally:
            self._drop_client(ws)

    async def _add(self, ws: WebSocket, topic: str) -> None:
        try:
            symbol, interval = topic_parts(topic)
            provider = get_provider(symbol)
        except (KeyError, ValueError):
            return
        self._subs_by_topic.setdefault(topic, set()).add(ws)
        self._topics_by_client.setdefault(ws, set()).add(topic)
        self._ensure_upstream(topic, provider, symbol, interval)

    def _remove(self, ws: WebSocket, topic: str) -> None:
        subs = self._subs_by_topic.get(topic)
        if subs:
            subs.discard(ws)
            if not subs:
                self._subs_by_topic.pop(topic, None)
                self._teardown_upstream(topic)
        topics = self._topics_by_client.get(ws)
        if topics:
            topics.discard(topic)

    def _drop_client(self, ws: WebSocket) -> None:
        for topic in list(self._topics_by_client.get(ws, set())):
            self._remove(ws, topic)
        self._topics_by_client.pop(ws, None)

    # ---------- 上游订阅 ----------

    def _ensure_upstream(
        self, topic: str, provider, symbol: str, interval: str
    ) -> None:
        if provider.realtime_mode == "none":
            return  # 如 akshare 日线源：不提供实时推送
        if topic not in self._poll_tasks:
            self._poll_tasks[topic] = asyncio.create_task(
                self._poll_loop(topic, provider, symbol, interval)
            )
        if (
            provider.realtime_mode == "ws"
            and REALTIME_WS_ENABLED
            and isinstance(provider, BinanceProvider)
        ):
            stream = f"{symbol.split(':', 1)[-1].lower()}@kline_{stream_id_of(interval)}"
            if stream not in self._bin_streams:
                self._bin_streams.add(stream)
                self._streams_changed.set()
                if self._ws_task is None or self._ws_task.done():
                    self._ws_task = asyncio.create_task(self._binance_ws_loop())

    def _teardown_upstream(self, topic: str) -> None:
        task = self._poll_tasks.pop(topic, None)
        if task:
            task.cancel()
        if topic_parts_safe(topic):
            symbol, interval = topic_parts(topic)
            stream = f"{symbol.split(':', 1)[-1].lower()}@kline_{interval}"
            if stream in self._bin_streams:
                self._bin_streams.discard(stream)
                self._streams_changed.set()

    # ---------- 上游实现 1：REST 轮询（兜底，也用于 Yahoo） ----------

    async def _poll_loop(
        self, topic: str, provider, symbol: str, interval: str
    ) -> None:
        interval_ms = INTERVAL_MS.get(interval, 86_400_000)
        # 有 WS 的源降低轮询频率，只作兜底；纯轮询源稍快
        period = 8 if provider.realtime_mode == "ws" else 5
        while True:
            subs = self._subs_by_topic.get(topic)
            if not subs:
                await asyncio.sleep(1)  # 等待被 teardown 取消
                continue
            try:
                now = int(time.time() * 1000)
                bars = await provider.history(
                    symbol, interval, now - 3 * interval_ms, now
                )
                if bars:
                    self.publish(topic, bars[-1])
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # 网络/代理抖动：下一轮再试
            await asyncio.sleep(period)

    # ---------- 上游实现 2：Binance 聚合 WebSocket ----------

    async def _binance_ws_loop(self) -> None:
        failures = 0
        while True:
            if not self._bin_streams:
                await asyncio.sleep(1)
                continue
            url = f"{BINANCE_WS}/stream?streams={'/'.join(sorted(self._bin_streams))}"
            self._streams_changed.clear()
            try:
                async with websockets.connect(url, open_timeout=10) as ws:
                    failures = 0
                    async for raw in ws:
                        self._on_binance_message(raw)
                        if self._streams_changed.is_set():
                            break  # 订阅集合变化，重连以更新 streams 参数
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            failures += 1
            await asyncio.sleep(min(2 * failures, 15))  # 失败也有轮询兜底

    def _on_binance_message(self, raw) -> None:
        try:
            data = json.loads(raw)
            k = data["data"]["k"]
            symbol = f"BINANCE:{k['s']}"
            topic = f"{symbol}|{k['i']}"
            bar = Bar(
                time=int(k["t"]),
                open=float(k["o"]),
                high=float(k["h"]),
                low=float(k["l"]),
                close=float(k["c"]),
                volume=float(k["v"]),
            )
        except Exception:
            return
        self.publish(topic, bar)

    # ---------- 发布 ----------

    def publish(self, topic: str, bar: Bar) -> None:
        subs = self._subs_by_topic.get(topic)
        if not subs:
            return
        payload = {"topic": topic, "bar": bar.model_dump()}
        for ws in list(subs):
            asyncio.ensure_future(self._send(ws, payload))

    async def _send(self, ws: WebSocket, payload: dict) -> None:
        try:
            await ws.send_json(payload)
        except Exception:
            self._drop_client(ws)

    async def start(self) -> None:
        if REALTIME_WS_ENABLED and (self._ws_task is None or self._ws_task.done()):
            self._ws_task = asyncio.create_task(self._binance_ws_loop())


def topic_parts_safe(topic: str) -> bool:
    try:
        topic_parts(topic)
        return True
    except ValueError:
        return False


hub = Hub()
