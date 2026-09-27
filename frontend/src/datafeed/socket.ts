/**
 * PubSub + WebSocket 封装（与文章中的 SocketClient 同一设计）。
 *
 * Topic = `${symbol}|${resolution}`，如 `BINANCE:BTCUSDT|1d`。
 * WebSocket 只负责收发；channelToSubscription 负责登记、查找和分发：
 *  - 首次出现的 Topic：登记并发送 SUBSCRIBE 给本地后端
 *  - 已存在的 Topic：只追加 callback（多个图表/系列共享一条上游订阅）
 *  - 取消：按 subscriberUID 删除；最后一个订阅者离开才发送 UNSUBSCRIBE
 * 断线自动重连，重连后对全部 Topic 重新订阅。
 */
import type { Bar } from '../api'

type Handler = { id: string; callback: (bar: Bar) => void }
type Subscription = { lastBar: Bar | null; handlers: Handler[] }
type StatusListener = (status: 'connecting' | 'connected' | 'disconnected') => void

export class SocketClient {
  private ws: WebSocket | null = null
  private channelToSubscription = new Map<string, Subscription>()
  private statusListeners = new Set<StatusListener>()
  private reconnectDelay = 1000
  private closedByUser = false

  connect(): void {
    this.closedByUser = false
    this.open()
  }

  private open(): void {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    this.emitStatus('connecting')
    this.ws = new WebSocket(`${proto}://${location.host}/ws`)

    this.ws.addEventListener('open', () => {
      this.reconnectDelay = 1000
      this.emitStatus('connected')
      // 重连后恢复全部本地订阅
      for (const topic of this.channelToSubscription.keys()) this.sendOp('sub', topic)
    })

    this.ws.addEventListener('message', (event) => this.publish(event.data as string))

    this.ws.addEventListener('close', () => {
      this.emitStatus('disconnected')
      if (!this.closedByUser) {
        setTimeout(() => this.open(), this.reconnectDelay)
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, 15000)
      }
    })
  }

  subscribeOnStream(
    symbolInfo: { symbol: string },
    resolution: string,
    callback: (bar: Bar) => void,
    subscriberUID: string,
    lastBar: Bar | null,
  ): void {
    const topic = this.getTopic(symbolInfo.symbol, resolution)
    const current = this.channelToSubscription.get(topic)
    if (current) {
      // 已有 Topic：只增加本地订阅者
      current.handlers.push({ id: subscriberUID, callback })
      return
    }
    // 新 Topic：登记并向上游订阅
    this.channelToSubscription.set(topic, { lastBar, handlers: [{ id: subscriberUID, callback }] })
    this.sendOp('sub', topic)
  }

  unsubscribeFromStream(subscriberUID: string): void {
    for (const [topic, sub] of this.channelToSubscription) {
      sub.handlers = sub.handlers.filter((h) => h.id !== subscriberUID)
      // 没有订阅者了才取消上游订阅
      if (!sub.handlers.length) {
        this.sendOp('unsub', topic)
        this.channelToSubscription.delete(topic)
      }
    }
  }

  unsubscribeAll(): void {
    for (const topic of Array.from(this.channelToSubscription.keys())) {
      this.sendOp('unsub', topic)
    }
    this.channelToSubscription.clear()
  }

  onStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener)
    return () => this.statusListeners.delete(listener)
  }

  private publish(raw: string): void {
    let topic: string, bar: Bar
    try {
      const msg = JSON.parse(raw)
      topic = msg.topic
      bar = msg.bar
    } catch {
      return
    }
    const sub = this.channelToSubscription.get(topic)
    if (!sub) return
    sub.lastBar = bar
    for (const handler of sub.handlers) handler.callback(bar)
  }

  private getTopic(symbol: string, resolution: string): string {
    return `${symbol}|${resolution}`
  }

  private sendOp(op: 'sub' | 'unsub', topic: string): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ op, topics: [topic] }))
    }
  }

  private emitStatus(s: 'connecting' | 'connected' | 'disconnected'): void {
    this.statusListeners.forEach((fn) => fn(s))
  }
}

export const socket = new SocketClient()
