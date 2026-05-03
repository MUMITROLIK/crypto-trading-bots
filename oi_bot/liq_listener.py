"""
Lightweight liquidation WebSocket listener для OI бота.

Слушает потоки ликвидаций с Binance и Bybit, записывает события
в data_store.liq_events — НЕ шлёт никаких сигналов.
Данные используются агрегатором для скоринга.

Binance: wss://fstream.binance.com/ws/!forceOrder@arr
  SELL → LONG ликвидирован, BUY → SHORT ликвидирован
  USD = ap * z

Bybit: wss://stream.bybit.com/v5/public/linear
  topik allLiquidation.{symbol} (батчи по BYBIT_BATCH)
  Buy → LONG ликвидирован, Sell → SHORT ликвидирован
  USD = p * v
"""

import asyncio
import json
import logging
import time

import aiohttp

from config import BINANCE_WS, BYBIT_WS, BYBIT_BATCH, WS_RECONNECT
from data_store import record_liq

logger = logging.getLogger(__name__)

# Минимальный порог — пишем в store только ликвидации >= $5K
# (агрегатор сам фильтрует по своему порогу)
_LIQ_MIN_USD = 5_000


# ─────────────────────────── Binance ────────────────────────────

async def _binance_liq_ws() -> None:
    """Binance: единый поток !forceOrder@arr."""
    url = f"{BINANCE_WS}/ws/!forceOrder@arr"
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url, heartbeat=30) as ws:
                    logger.info("LiqListener Binance: подключено")
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            break
                        try:
                            data = json.loads(msg.data)
                            events = data if isinstance(data, list) else [data]
                            for event in events:
                                if event.get("e") != "forceOrder":
                                    continue
                                o        = event["o"]
                                symbol   = o["s"]
                                side_raw = o["S"]   # SELL = LONG liq, BUY = SHORT liq
                                side     = "LONG" if side_raw == "SELL" else "SHORT"
                                try:
                                    usd = float(o["ap"]) * float(o["z"])
                                except (KeyError, ValueError):
                                    continue
                                if usd >= _LIQ_MIN_USD:
                                    record_liq("binance", symbol, side, usd)
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"LiqListener Binance: {e} — реконнект через {WS_RECONNECT}с")
        await asyncio.sleep(WS_RECONNECT)


# ─────────────────────────── Bybit ──────────────────────────────

async def _bybit_liq_batch(symbols: list[str], batch_idx: int) -> None:
    """Одно WS соединение для батча символов Bybit."""
    topics = [f"allLiquidation.{sym}" for sym in symbols]
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(BYBIT_WS, heartbeat=20) as ws:
                    for i in range(0, len(topics), 10):
                        await ws.send_str(json.dumps(
                            {"op": "subscribe", "args": topics[i : i + 10]}
                        ))
                    logger.info(f"LiqListener Bybit batch#{batch_idx}: подключено, {len(symbols)} символов")

                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            break
                        try:
                            data = json.loads(msg.data)
                            if not data.get("topic", "").startswith("allLiquidation."):
                                continue
                            events = data.get("data", [])
                            if isinstance(events, dict):
                                events = [events]
                            for d in events:
                                symbol   = d.get("s", "")
                                side_raw = d.get("S", "")
                                # Buy = LONG ликвидирован, Sell = SHORT ликвидирован
                                side = "LONG" if side_raw == "Buy" else "SHORT"
                                try:
                                    usd = float(d["p"]) * float(d["v"])
                                except (KeyError, ValueError):
                                    continue
                                if usd >= _LIQ_MIN_USD:
                                    record_liq("bybit", symbol, side, usd)
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"LiqListener Bybit batch#{batch_idx}: {e} — реконнект через {WS_RECONNECT}с")
        await asyncio.sleep(WS_RECONNECT)


async def run_bybit_liq_ws(symbols: list[str]) -> None:
    """Запускаем батчи WS для всех символов Bybit."""
    if not symbols:
        logger.warning("LiqListener Bybit: символов нет, пропускаем")
        return
    tasks = [
        asyncio.create_task(_bybit_liq_batch(symbols[i : i + BYBIT_BATCH], idx))
        for idx, i in enumerate(range(0, len(symbols), BYBIT_BATCH))
    ]
    await asyncio.gather(*tasks)


async def run_binance_liq_ws() -> None:
    """Запускаем Binance лик-листенер."""
    await _binance_liq_ws()
