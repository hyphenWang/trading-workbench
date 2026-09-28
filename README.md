# 本地交易工作台 (Local Trading Workbench)

一个完全运行在本机的交易研究工作台：多市场行情图表 + 专业回测引擎。
数据层、回测层、图表层彼此解耦，任何一层都可以单独替换。

```
┌────────────────────────────────────────────────────────────────┐
│  前端工作台  Vue 3 + Pinia + Lightweight Charts                 │
│  Datafeed(REST 取历史) + PubSub Socket(WS 收实时)               │
└───────────────┬────────────────────────────▲───────────────────┘
        /api/*  │                            │ /ws  实时推送
┌───────────────▼────────────────────────────┴───────────────────┐
│  后端服务  FastAPI                                             │
│  ┌──────────────┐  ┌───────────────────┐  ┌─────────────────┐  │
│  │ 数据源适配器  │  │ 实时行情枢纽(PubSub)│  │ 回测引擎 quant/ │  │
│  │ BINANCE  WS  │  │ 上游订阅 → 本地分发 │  │ 指标/策略/绩效  │  │
│  │ YAHOO   轮询 │  └───────────────────┘  │ CLI + HTTP API  │  │
│  │ AKSHARE 日线 │                          └─────────────────┘  │
│  └──────────────┘                                                │
└──────────────────────────────────────────────────────────────────┘
```

## 支持的市场与数据源

| 前缀 | 市场 | 数据源 | 周期 | 实时 |
|------|------|--------|------|------|
| `BINANCE:` | 加密货币 | Binance 公开 API（无需 Key） | 1m ~ 1w | WebSocket（失败自动回退轮询） |
| `YAHOO:` | 美股/指数/外汇/商品期货 | Yahoo Finance（约15分钟延迟） | 1m ~ 1w（分钟级有跨度限制） | 轮询 |
| `CN:` | A股 | 新浪（前复权日线） | 1d | 无（收盘后更新） |
| `HK:` | 港股 | 新浪/东财（前复权日线） | 1d | 无 |
| `ETF:` | 场内基金 | 东财（前复权日线） | 1d | 无 |
| `IDX:` | 指数 | 新浪 | 1d | 无 |
| `FUT:` | 国内期货（RB0=主力连续） | 新浪 | 1d | 无 |

## 快速开始

依赖：Node 20+、Python 3.11+、[uv](https://docs.astral.sh/uv/)

```bash
# 1. 后端
cd backend
copy .env.example .env      # 如需代理访问 Binance/Yahoo，编辑 .env
uv sync
uv run uvicorn app.main:app --port 8000

# 2. 前端（新开一个终端）
cd frontend
npm install
npm run dev                 # 打开 http://localhost:5173
```

### 网络与代理说明

- **Binance / Yahoo**：直连不通时在 `backend/.env` 配置 `HTTP_PROXY` / `HTTPS_PROXY`。
  httpx 只认环境变量；如果你的代理是 Windows 系统代理（Clash 等），后端启动时会自动
  同步——但仅在该代理端口**可达**时启用，避免代理软件没开导致全部请求失败。
- **A股/港股/期货数据源**：已强制绕过代理直连（国内源走代理反而容易失败）。
- **实时行情**：前端只连接本机后端（`/ws`），上游由后端订阅，浏览器无需任何代理。

### 命令行回测（不打开界面也能用）

```bash
cd backend
uv run python -m quant.cli --symbol BINANCE:BTCUSDT --interval 1d \
    --strategy sma_cross --param fast=20 --param slow=60 \
    --start 2022-01-01 --fee 0.001 --allow-short --save result.json

uv run python -m quant.cli --symbol CN:600519 --strategy bollinger_reversion
```

## 在线演示（GitHub Pages）

前端支持**演示模式**：检测不到本地后端时，自动加载 `frontend/public/demo/` 内置的
历史数据快照（BTCUSDT / 600519 / AAPL），仅展示图表功能。

部署方式：推送本仓库后，在 GitHub 仓库 Settings → Pages → Source 选择
**GitHub Actions**，随后每次推送都会自动部署到
`https://<用户名>.github.io/trading-workbench/`（仓库重命名时需同步修改
`.github/workflows/deploy-pages.yml` 里的 `--base` 参数）。

## 回测引擎（backend/quant）

- **无前视偏差纪律**：信号在第 i 根收盘确认，第 i+1 根开盘价成交（引擎内部强制 `signal[i-1]`）。
- **成本模型**：单边手续费率 + 单边滑点率，按资金比例开仓，支持做空，期末强制平仓保证统计完整。
- **内置策略**（7 个）：SMA 交叉、EMA 交叉、MACD、RSI 超卖回归、唐奇安通道突破、
  布林带均值回归、SuperTrend。
- **指标库**（手写，无外部依赖）：SMA/EMA/RSI(Wilder)/MACD/ATR/布林带/唐奇安通道/SuperTrend。
- **绩效报告**：总收益、年化收益(CAGR)、年化波动、Sharpe、Sortino、最大回撤、胜率、
  盈亏比、平均单笔、持仓时间占比、买入持有对照，以及资金曲线和逐笔交易明细。

## 界面功能

- 品种搜索（全市场统一搜索，如 `BTCUSDT`、`AAPL`、`600519`、`RB0`）
- **自选列表**：左侧栏，本地持久化（localStorage），点击切换品种，60 秒自动刷新最新价与日涨跌
- **双图表引擎可切换**：
  - `轻量`：Lightweight Charts，极简看图
  - `专业`：KLineChart（开源 Apache-2.0），画线工具（线段/射线/水平线/矩形/斐波那契/价格通道等）
    + 内置指标（MA/EMA/BOLL/VOL/MACD/RSI/KDJ 一键叠加），向左滚动自动加载更早历史
- 实时行情：订阅式推送（同一品种/周期只建立一条上游订阅，多图共享）
- 策略回测面板：参数可调、绩效卡片、资金曲线、交易明细
- **参数寻优 (Walk-Forward)**：训练窗网格搜索选参 → 样本外测试窗验证 → 滚动汇总，
  自动输出过拟合诊断（样本外/训练期指标比），防止"调参调到历史上"

## 关于 TradingView Charting Library（已结案）

Advanced Charts 官方免费授权**仅面向企业/商业用途**，明确排除学习、研究、个人项目
（2026-09 申请实测被拒，官方回复建议个人使用 Lightweight Charts）。本项目的"专业"
图表因此采用开源的 KLineChart，体验接近且无授权限制。

如将来以公司/产品身份重新申请（https://www.tradingview.com/advanced-charts/ ），
Datafeed 层接口与 TradingView 规范同构，替换图表组件即可接入，数据层零改动。

## 后续路线图（按优先级建议）

1. ~~策略参数寻优（Walk-Forward）~~ ✅ 已完成（`/api/optimize` + 回测面板）
2. ~~自选列表~~ ✅ 已完成（localStorage 持久化）
3. 多图布局 / 图表窗格拆分
4. **A股分钟级数据**与实时快照（东财 spot 接口轮询）
5. **组合回测 / 风险管理模块**（仓位规则、多标的组合资金曲线）
6. **AI 助手层**：接入 MCP（如 tradingview-mcp-server）做行情问答与策略研发助手
7. **纸面交易（paper trading）**：实时信号 → 模拟撮合 → 持仓跟踪

## 免责声明

本系统仅用于个人学习与研究。行情数据来自第三方公开接口，可能延迟、缺失或出错；
回测结果基于历史数据与简化撮合模型，不代表未来表现，不构成任何投资建议。
