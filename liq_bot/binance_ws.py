"""
Binance: подписка на !forceOrder@arr — единый поток всех ликвидаций.

side mapping:
  o.S == "SELL" → LONG позиция ликвидирована
  o.S == "BUY"  → SHORT позиция ликвидирована

USD сумма = average_price * cumulative_filled_qty
"""

import asyncio
import json
import logging
import time

import aiohttp

import notifier
import liq_store
import data_store
from config import BINANCE_WS, LIQ_MIN_USD, LIQ_COOLDOWN, WS_RECONNECT

logger = logging.getLogger(__name__)

_last_signal: dict[str, float] = {}


def _can_signal(symbol: str) -> bool:
    return (time.time() - _last_signal.get(symbol, 0.0)) >= LIQ_COOLDOWN


def _mark(symbol: str) -> None:
    _last_signal[symbol] = time.time()


async def run_liq_ws() -> None:
    url = f"{BINANCE_WS}/ws/!forceOrder@arr"
    first_msg = True
    total_received = 0
    last_log_time = 0.0

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url, heartbeat=30) as ws:
                    logger.info("Binance liquidation WS: подключено")

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                total_received += 1

                                if first_msg:
                                    logger.info(f"Binance liquidation WS: первый пакет → {msg.data[:120]}")
                                    first_msg = False

                                # Каждые 2 минуты показываем статус
                                now = time.time()
                                if now - last_log_time >= 120:
                                    logger.info(f"[Binance LIQ] живой, получено сообщений: {total_received}")
                                    last_log_time = now

                                # Binance присылает либо одно событие, либо массив
                                events = data if isinstance(data, list) else [data]

                                for event in events:
                                    if event.get("e") != "forceOrder":
                                        continue

                                    o        = event["o"]
                                    symbol   = o["s"]
                                    side_raw = o["S"]  # SELL = long liq, BUY = short liq
                                    side     = "LONG" if side_raw == "SELL" else "SHORT"

                                    try:
                                        usd = float(o["ap"]) * float(o["z"])
                                    except (KeyError, ValueError):
                                        continue

                                    # Дебаг: показываем все ликвидации >= $1000
                                    if usd >= 1000:
                                        logger.info(f"[DEBUG] Binance LIQ {side} {symbol}: ${usd:,.0f} (порог ${LIQ_MIN_USD:,})")

                                    if usd < LIQ_MIN_USD:
                                        continue
                                    if not _can_signal(symbol):
                                        continue

                                    ratio      = liq_store.record(symbol, usd)
                                    signal_num = data_store.increment_daily_count(f"liq:binance:{symbol}")
                                    _mark(symbol)
                                    logger.info(
                                        f"Binance LIQ {side} {symbol}: ${usd:,.0f} #{signal_num}"
                                        + (f" x{ratio}" if ratio else "")
                                    )
                                    asyncio.create_task(notifier.send(
                                        notifier.format_signal(symbol, side, usd, "binance", ratio, signal_num)
                                    ))

                            except Exception as e:
                                logger.debug(f"Binance LIQ parse: {e}")

                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning(f"Binance LIQ WS: соединение закрыто ({msg.type})")
                            break

        except Exception as e:
            logger.warning(f"Binance LIQ WS: {e} — реконнект через {WS_RECONNECT}с")
            first_msg = True

        await asyncio.sleep(WS_RECONNECT)
