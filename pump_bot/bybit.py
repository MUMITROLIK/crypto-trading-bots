import asyncio
import json
import logging
import time

import aiohttp
import websockets

from config import BYBIT_REST, BYBIT_WS, BYBIT_BATCH, PRICE_POLL_INTERVAL, WS_RECONNECT
from data_store import price_history

logger = logging.getLogger(__name__)

_symbols: list[str] = []


async def fetch_symbols() -> list[str]:
    global _symbols
    syms: list[str] = []
    cursor = None

    async with aiohttp.ClientSession() as s:
        while True:
            params: dict = {"category": "linear", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            async with s.get(f"{BYBIT_REST}/v5/market/instruments-info", params=params) as r:
                data = await r.json()

            for item in data["result"]["list"]:
                if (
                    item.get("quoteCoin") == "USDT"
                    and item.get("contractType") == "LinearPerpetual"
                    and item.get("status") == "Trading"
                ):
                    syms.append(item["symbol"])

            cursor = data["result"].get("nextPageCursor") or ""
            if not cursor:
                break

    _symbols = syms
    logger.info(f"Bybit: загружено {len(_symbols)} символов")
    return _symbols


async def run_price_rest() -> None:
    """Резервный REST polling на случай обрыва WS."""
    while True:
        if not _symbols:
            await asyncio.sleep(5)
            continue
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{BYBIT_REST}/v5/market/tickers",
                    params={"category": "linear"},
                ) as r:
                    data = await r.json()

            ts = time.time()
            for item in data.get("result", {}).get("list", []):
                sym = item.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                try:
                    price_str = item.get("lastPrice", "")
                    if price_str:
                        price_history["bybit"][sym].append((ts, float(price_str)))
                except ValueError:
                    pass

        except Exception as e:
            logger.warning(f"Bybit price REST: {e}")

        await asyncio.sleep(PRICE_POLL_INTERVAL)


async def _ws_batch(symbols: list[str]) -> None:
    topics = [f"tickers.{s}" for s in symbols]
    while True:
        try:
            async with websockets.connect(BYBIT_WS, ping_interval=None) as ws:
                for i in range(0, len(topics), 10):
                    await ws.send(json.dumps({"op": "subscribe", "args": topics[i : i + 10]}))

                logger.info(f"Bybit WS: подключено {len(symbols)} символов")

                async def _heartbeat():
                    while True:
                        await asyncio.sleep(20)
                        try:
                            await ws.send(json.dumps({"op": "ping"}))
                        except Exception:
                            break

                hb = asyncio.create_task(_heartbeat())
                try:
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("topic", "").startswith("tickers."):
                            d = msg.get("data", {})
                            sym = d.get("symbol", "")
                            price_str = d.get("lastPrice", "")
                            if sym and price_str:
                                try:
                                    price = float(price_str)
                                    if price > 0:
                                        price_history["bybit"][sym].append((time.time(), price))
                                except ValueError:
                                    pass
                finally:
                    hb.cancel()

        except Exception as e:
            logger.warning(f"Bybit WS batch error: {e} — реконнект через {WS_RECONNECT}с")
            await asyncio.sleep(WS_RECONNECT)


async def run_price_ws() -> None:
    if not _symbols:
        logger.warning("Bybit WS: символы ещё не загружены")
        return

    tasks = [
        asyncio.create_task(_ws_batch(_symbols[i : i + BYBIT_BATCH]))
        for i in range(0, len(_symbols), BYBIT_BATCH)
    ]
    await asyncio.gather(*tasks)
