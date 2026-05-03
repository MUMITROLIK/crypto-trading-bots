"""
CVD Tracker — динамические подписки на торговые потоки.

Логика:
  1. screener обнаружил OI >= OI_WATCH_PCT% → вызывает start_watch()
  2. Открываем WS на торговый поток символа (aggTrade/publicTrade)
  3. Каждая сделка → data_store.add_trade() → CVD накапливается
  4. screener проверяет CVD перед отправкой сигнала
  5. После CVD_TIMEOUT секунд без сигнала → auto-отписка

Binance: wss://fstream.binance.com/ws/{symbol}@aggTrade
  m=False → покупатель агрессор (buy), m=True → продавец агрессор (sell)

Bybit: wss://stream.bybit.com/v5/public/linear, топик publicTrade.{symbol}
  S="Buy" → покупатель агрессор, S="Sell" → продавец агрессор
"""

import asyncio
import json
import logging
import time

import aiohttp

import data_store
from config import BINANCE_WS, BYBIT_WS, CVD_TIMEOUT, WS_RECONNECT

logger = logging.getLogger(__name__)

# (exchange, symbol) → время старта подписки
_watching: dict[tuple, float] = {}
# (exchange, symbol) → asyncio.Task
_tasks: dict[tuple, asyncio.Task] = {}


def is_watching(exchange: str, symbol: str) -> bool:
    return (exchange, symbol) in _watching


def start_watch(exchange: str, symbol: str) -> None:
    """Запускаем CVD подписку если ещё не запущена."""
    key = (exchange, symbol)
    if key in _watching:
        return
    data_store.reset_cvd(exchange, symbol)
    _watching[key] = time.time()
    task = asyncio.create_task(_run(exchange, symbol))
    _tasks[key] = task
    logger.info(f"CVD watch: старт {exchange} {symbol}")


def stop_watch(exchange: str, symbol: str) -> None:
    """Останавливаем CVD подписку."""
    key = (exchange, symbol)
    _watching.pop(key, None)
    task = _tasks.pop(key, None)
    if task and not task.done():
        task.cancel()
    logger.debug(f"CVD watch: стоп {exchange} {symbol}")


def watching_count() -> int:
    return len(_watching)


async def _run(exchange: str, symbol: str) -> None:
    """Цикл с реконнектом для торгового потока."""
    try:
        while True:
            try:
                if exchange == "binance":
                    await _binance_stream(symbol)
                else:
                    await _bybit_stream(symbol)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"CVD {exchange} {symbol}: {e} — реконнект через {WS_RECONNECT}с")
            await asyncio.sleep(WS_RECONNECT)
    except asyncio.CancelledError:
        pass


async def _binance_stream(symbol: str) -> None:
    """Binance aggTrade: m=False → покупка, m=True → продажа."""
    url = f"{BINANCE_WS}/ws/{symbol.lower()}@aggTrade"
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url, heartbeat=30) as ws:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    d = json.loads(msg.data)
                    try:
                        price  = float(d["p"])
                        qty    = float(d["q"])
                        is_buy = not d["m"]   # m=True → продавец агрессор
                        if qty > 0:
                            data_store.add_trade("binance", symbol, qty, is_buy, price)
                    except (KeyError, ValueError):
                        pass
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break


async def _bybit_stream(symbol: str) -> None:
    """Bybit publicTrade: S=Buy → покупка, S=Sell → продажа."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(BYBIT_WS, heartbeat=20) as ws:
            await ws.send_str(json.dumps({
                "op": "subscribe",
                "args": [f"publicTrade.{symbol}"]
            }))
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    d = json.loads(msg.data)
                    if d.get("topic") == f"publicTrade.{symbol}":
                        for trade in d.get("data", []):
                            try:
                                price  = float(trade["p"])
                                qty    = float(trade["v"])
                                is_buy = trade["S"] == "Buy"
                                if qty > 0:
                                    data_store.add_trade("bybit", symbol, qty, is_buy, price)
                            except (KeyError, ValueError):
                                pass
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break


async def cleanup_loop() -> None:
    """Каждые 2 минуты убираем подписки старше CVD_TIMEOUT секунд."""
    while True:
        await asyncio.sleep(120)
        now = time.time()
        stale = [
            (ex, sym) for (ex, sym), ts in list(_watching.items())
            if now - ts > CVD_TIMEOUT
        ]
        for ex, sym in stale:
            logger.info(f"CVD timeout: отписка {ex} {sym}")
            stop_watch(ex, sym)
        if _watching:
            logger.debug(f"CVD активных подписок: {len(_watching)}")
