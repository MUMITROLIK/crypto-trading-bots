"""
Bybit Futures для агрегатора:
  - REST /v5/market/tickers  → price + OI + funding (каждые 10с)
  - WS tickers.SYMBOL        → price_history в реальном времени
  - REST /v5/market/account-ratio → ls_ratio (по запросу)
"""

import asyncio
import json
import logging
import time

import aiohttp
import websockets

from config import BYBIT_REST, BYBIT_WS, BYBIT_BATCH, OI_POLL_INTERVAL, WS_RECONNECT
from data_store import price_history, oi_history, funding_rates

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


async def run_oi_polling() -> None:
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
                    oi_str    = item.get("openInterest", "")
                    price_str = item.get("lastPrice", "")
                    fr_str    = item.get("fundingRate", "")
                    if oi_str:
                        oi_history["bybit"][sym].append((ts, float(oi_str)))
                    if price_str:
                        price_history["bybit"][sym].append((ts, float(price_str)))
                    if fr_str:
                        funding_rates["bybit"][sym] = float(fr_str)
                except ValueError:
                    pass
        except Exception as e:
            logger.warning(f"Bybit OI/ticker REST: {e}")
        await asyncio.sleep(OI_POLL_INTERVAL)


async def _ws_batch(symbols: list[str]) -> None:
    topics = [f"tickers.{s}" for s in symbols]
    while True:
        try:
            async with websockets.connect(BYBIT_WS, ping_interval=None) as ws:
                for i in range(0, len(topics), 10):
                    await ws.send(json.dumps({"op": "subscribe", "args": topics[i:i + 10]}))
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
                            if not sym:
                                continue
                            ts = time.time()
                            price_str = d.get("lastPrice", "")
                            if price_str:
                                try:
                                    price = float(price_str)
                                    if price > 0:
                                        price_history["bybit"][sym].append((ts, price))
                                except ValueError:
                                    pass
                            oi_str = d.get("openInterest", "")
                            if oi_str:
                                try:
                                    oi = float(oi_str)
                                    if oi > 0:
                                        oi_history["bybit"][sym].append((ts, oi))
                                except ValueError:
                                    pass
                finally:
                    hb.cancel()
        except Exception as e:
            logger.warning(f"Bybit WS batch: {e} — реконнект через {WS_RECONNECT}с")
            await asyncio.sleep(WS_RECONNECT)


async def run_price_ws() -> None:
    if not _symbols:
        logger.warning("Bybit WS: символы не загружены")
        return
    tasks = [
        asyncio.create_task(_ws_batch(_symbols[i:i + BYBIT_BATCH]))
        for i in range(0, len(_symbols), BYBIT_BATCH)
    ]
    await asyncio.gather(*tasks)


async def fetch_ls_ratio(symbol: str) -> float | None:
    """
    Long/Short Account Ratio с Bybit.
    Возвращает buyRatio (0.0–1.0) — доля аккаунтов в лонге.
    None если данных нет.
    """
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{BYBIT_REST}/v5/market/account-ratio",
                params={"category": "linear", "symbol": symbol, "period": "1h", "limit": 1},
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        items = data.get("result", {}).get("list", [])
        if items:
            return float(items[0]["buyRatio"])
    except Exception:
        pass
    return None
