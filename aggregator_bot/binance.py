"""
Binance Futures для агрегатора:
  - WS  !miniTicker@arr       → price_history (реальное время)
  - REST /fapi/v1/openInterest → oi_history (батчи по 20, каждые 10с)
  - REST /fapi/v1/premiumIndex → funding_rates (каждые 60с)
  - REST /futures/data/globalLongShortAccountRatio → ls_ratio (по запросу)
"""

import asyncio
import json
import logging
import time

import aiohttp

from config import BINANCE_REST, BINANCE_WS, OI_POLL_INTERVAL, WS_RECONNECT
from data_store import price_history, oi_history, funding_rates

logger = logging.getLogger(__name__)

_symbols: list[str] = []


async def fetch_symbols() -> list[str]:
    global _symbols
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{BINANCE_REST}/fapi/v1/exchangeInfo") as r:
            data = await r.json()
    _symbols = [
        sym["symbol"] for sym in data["symbols"]
        if sym["contractType"] == "PERPETUAL"
        and sym["quoteAsset"] == "USDT"
        and sym["status"] == "TRADING"
    ]
    logger.info(f"Binance: загружено {len(_symbols)} символов")
    return _symbols


async def run_price_ws() -> None:
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
                                for ticker in tickers:
                                    sym = ticker.get("s", "")
                                    if not sym.endswith("USDT"):
                                        continue
                                    try:
                                        price = float(ticker["c"])
                                        if price > 0:
                                            price_history["binance"][sym].append((ts, price))
                                    except (KeyError, ValueError):
                                        pass
                                if first_msg:
                                    logger.info("Binance price WS: первый пакет получен")
                                    first_msg = False
                            except Exception:
                                pass
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
        except Exception as e:
            logger.warning(f"Binance price WS: {e} — реконнект через {WS_RECONNECT}с")
            first_msg = True
        await asyncio.sleep(WS_RECONNECT)


async def run_price_polling() -> None:
    """REST резерв на случай обрыва WS."""
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
        await asyncio.sleep(OI_POLL_INTERVAL)


async def _poll_oi_once(session: aiohttp.ClientSession, symbol: str) -> None:
    try:
        async with session.get(
            f"{BINANCE_REST}/fapi/v1/openInterest",
            params={"symbol": symbol},
        ) as r:
            if r.status != 200:
                return
            data = await r.json()
        oi_history["binance"][symbol].append((time.time(), float(data["openInterest"])))
    except Exception:
        pass


async def run_oi_polling() -> None:
    BATCH = 20
    while True:
        if not _symbols:
            await asyncio.sleep(5)
            continue
        async with aiohttp.ClientSession() as session:
            for i in range(0, len(_symbols), BATCH):
                batch = _symbols[i:i + BATCH]
                await asyncio.gather(*[_poll_oi_once(session, sym) for sym in batch])
                await asyncio.sleep(0.05)
        await asyncio.sleep(OI_POLL_INTERVAL)


async def run_funding_polling() -> None:
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{BINANCE_REST}/fapi/v1/premiumIndex") as r:
                    if r.status != 200:
                        await asyncio.sleep(30)
                        continue
                    items = await r.json()
            for item in items:
                sym = item.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                try:
                    funding_rates["binance"][sym] = float(item["lastFundingRate"])
                except (KeyError, ValueError):
                    pass
        except Exception as e:
            logger.warning(f"Binance funding polling: {e}")
        await asyncio.sleep(60)


async def fetch_ls_ratio(symbol: str) -> float | None:
    """
    Long/Short Account Ratio с Binance.
    Возвращает longAccount (0.0–1.0) — доля аккаунтов в лонге.
    None если данных нет (мелкий символ или ошибка).
    """
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{BINANCE_REST}/futures/data/globalLongShortAccountRatio",
                params={"symbol": symbol, "period": "5m", "limit": 1},
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
        if data and isinstance(data, list):
            return float(data[0]["longAccount"])
    except Exception:
        pass
    return None
