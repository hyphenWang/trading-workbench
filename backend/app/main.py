"""FastAPI 应用入口。

启动：uv run --directory backend uvicorn app.main:app --port 8000
文档：http://127.0.0.1:8000/docs
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.routers import router
from app.realtime import hub


@asynccontextmanager
async def lifespan(app: FastAPI):
    await hub.start()
    yield


app = FastAPI(title="Local Trading Workbench", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    """本地实时行情推送。协议：{"op":"sub"/"unsub","topics":["BINANCE:BTCUSDT|1d"]}"""
    await hub.client_loop(ws)
