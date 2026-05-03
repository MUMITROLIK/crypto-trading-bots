"""
Binance Futures:
  - WS  !miniTicker@arr         → price_history["binance"]  (реальное время)
  - REST /fapi/v1/ticker/24hr   → price_history["binance"]  (резерв, каждые 30с)
  - REST /fapi/v1/openInterest  → oi_history["binance"]     (батчи по 20 символов)
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
    """Загружаем список активных USDT перпов с Binance (с retry)."""
    global _symbols
    for attempt in range(5):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{BINANCE_REST}/fapi/v1/exchangeInfo",
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as r:
                    data = await r.json()

            if "symbols" not in data:
                logger.warning(f"Binance exchangeInfo: неожиданный ответ: {str(data)[:200]}")
                await asyncio.sleep(5)
                continue

            _symbols = [
                sym["symbol"]
                for sym in data["symbols"]
                if sym.get("contractType") == "PERPETUAL"
                and sym.get("quoteAsset") == "USDT"
                and sym.get("status") == "TRADING"
            ]
            logger.info(f"Binance: загружено {len(_symbols)} символов")
            return _symbols

        except Exception as e:
            logger.warning(f"Binance fetch_symbols попытка {attempt+1}/5: {e}")
            await asyncio.sleep(5)

    logger.error("Binance: не удалось загрузить символы после 5 попыток, продолжаем без них")
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


async def _poll_oi_once(session: aiohttp.ClientSession, symbol: str) -> None:
    """OI для одного символа."""
    try:
        async with session.get(
            f"{BINANCE_REST}/fapi/v1/openInterest",
            params={"symbol": symbol},
        ) as r:
            if r.status != 200:
                return
            data = await r.json()
        oi_history["binance"][symbol].append((time.time(), float(data["openInterest"])))
    except Exception as e:
        logger.debug(f"Binance OI {symbol}: {e}")


async def run_price_polling() -> None:
    """REST резерв на случай обрыва WS — каждые OI_POLL_INTERVAL секунд."""
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{BINANCE_REST}/fapi/v1/ticker/24hr") as r:
                    if r.status != 200:
                        await asyncio.sleep(5)
                        continue
                    items = await r.json()

            ts = time.time()
            count = 0
            for item in items:
                sym = item.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                try:
                    price = float(item["lastPrice"])
                    if price > 0:
                        price_history["binance"][sym].append((ts, price))
                        count += 1
                except (KeyError, ValueError):
                    pass
            logger.debug(f"Binance price REST резерв: {count} цен")

        except Exception as e:
            logger.warning(f"Binance price REST: {e}")

        await asyncio.sleep(OI_POLL_INTERVAL)


async def run_funding_polling() -> None:
    """
    Polling funding rates: /fapi/v1/premiumIndex — один запрос = все символы.
    Обновляем раз в минуту (funding меняется медленно, раз в 8 часов начисляется).
    """
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{BINANCE_REST}/fapi/v1/premiumIndex") as r:
                    if r.status != 200:
                        await asyncio.sleep(30)
                        continue
                    items = await r.json()

            count = 0
            for item in items:
                sym = item.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                try:
                    fr = float(item["lastFundingRate"])
                    funding_rates["binance"][sym] = fr
                    count += 1
                except (KeyError, ValueError):
                    pass
            logger.debug(f"Binance funding rates обновлены: {count} символов")

        except Exception as e:
            logger.warning(f"Binance funding polling: {e}")

        await asyncio.sleep(60)  # раз в минуту достаточно


async def fetch_ls_ratio(symbol: str) -> float | None:
    """Long/Short Account Ratio с Binance. Возвращает longAccount (0.0–1.0) или None."""
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


async def run_oi_polling() -> None:
    """
    Параллельный polling OI: батчи по 20 символов одновременно.
    535 / 20 = ~27 батчей × ~300мс = ~8 секунд на цикл.
    """
    BATCH = 20
    while True:
        if not _symbols:
            await asyncio.sleep(5)
            continue

        async with aiohttp.ClientSession() as session:
            for i in range(0, len(_symbols), BATCH):
                batch = _symbols[i : i + BATCH]
                await asyncio.gather(*[_poll_oi_once(session, sym) for sym in batch])
                await asyncio.sleep(0.05)

        await asyncio.sleep(OI_POLL_INTERVAL)
