import asyncio
import json
import logging
import time

import aiohttp

from config import BINANCE_REST, BINANCE_WS, PRICE_POLL_INTERVAL, WS_RECONNECT
from data_store import price_history

logger = logging.getLogger(__name__)

_symbols: list[str] = []


async def fetch_symbols() -> list[str]:
    global _symbols
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{BINANCE_REST}/fapi/v1/exchangeInfo") as r:
            data = await r.json()

    _symbols = [
        sym["symbol"]
        for sym in data["symbols"]
        if sym["contractType"] == "PERPETUAL"
        and sym["quoteAsset"] == "USDT"
        and sym["status"] == "TRADING"
    ]
    logger.info(f"Binance: загружено {len(_symbols)} символов")
    return _symbols


async def run_price_ws() -> None:
    """
    Binance !miniTicker@arr — один поток для ВСЕХ символов, обновление ~1с.
    Используем aiohttp WebSocket вместо websockets чтобы избежать проблем
    с размером сообщений (500+ монет = большой JSON).
    """
    url = f"{BINANCE_WS}/ws/!miniTicker@arr"
    first_msg = True

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url, heartbeat=30) as ws:
                    logger.info("Binance price WS: подключено")

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                tickers = json.loads(msg.data)
                                if not isinstance(tickers, list):
                                    continue

                                ts = time.time()
                                count = 0
                                for ticker in tickers:
                                    sym = ticker.get("s", "")
                                    if not sym.endswith("USDT"):
                                        continue
                                    try:
                                        price = float(ticker["c"])
                                        if price > 0:
                                            price_history["binance"][sym].append((ts, price))
                                            count += 1
                                    except (KeyError, ValueError):
                                        pass

                                if first_msg:
                                    logger.info(f"Binance price WS: первый пакет — {count} цен")
                                    first_msg = False

                            except Exception as e:
                                logger.debug(f"Binance WS parse: {e}")

                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning(f"Binance price WS: соединение закрыто ({msg.type})")
                            break

        except Exception as e:
            logger.warning(f"Binance price WS: {e} — реконнект через {WS_RECONNECT}с")
            first_msg = True

        await asyncio.sleep(WS_RECONNECT)


async def run_price_polling() -> None:
    """REST резерв на случай обрыва WS — каждые PRICE_POLL_INTERVAL секунд."""
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{BINANCE_REST}/fapi/v1/ticker/24hr") as r:
                    if r.status != 200:
                        await asyncio.sleep(5)
                        continue
                    items = await r.json()

            ts = time.time()
            for item in items:
                sym = item.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                try:
                    price = float(item["lastPrice"])
                    if price > 0:
                        price_history["binance"][sym].append((ts, price))
                except (KeyError, ValueError):
                    pass

        except Exception as e:
            logger.warning(f"Binance price REST: {e}")

        await asyncio.sleep(PRICE_POLL_INTERVAL)
