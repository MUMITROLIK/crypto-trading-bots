"""
Bybit Futures (Linear Perpetuals):
  - REST /v5/market/tickers (все символы за 1 вызов) → price + OI
  - WebSocket tickers.SYMBOL (батчи) → price_history["bybit"] в реальном времени

Стратегия:
  Цена  — из WS (реальное время, батчи по BYBIT_BATCH символов)
  OI    — из REST polling каждые OI_POLL_INTERVAL секунд (1 вызов = все символы)
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
    """Загружаем список активных USDT Linear Perpetuals с Bybit (с retry)."""
    global _symbols
    for attempt in range(5):
        try:
            syms: list[str] = []
            cursor = None

            async with aiohttp.ClientSession() as s:
                while True:
                    params: dict = {"category": "linear", "limit": 200}
                    if cursor:
                        params["cursor"] = cursor
                    async with s.get(
                        f"{BYBIT_REST}/v5/market/instruments-info",
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as r:
                        data = await r.json()

                    result = data.get("result", {})
                    if not result or "list" not in result:
                        logger.warning(f"Bybit instruments-info: неожиданный ответ: {str(data)[:200]}")
                        break

                    for item in result["list"]:
                        if (
                            item.get("quoteCoin") == "USDT"
                            and item.get("contractType") == "LinearPerpetual"
                            and item.get("status") == "Trading"
                        ):
                            syms.append(item["symbol"])

                    cursor = result.get("nextPageCursor") or ""
                    if not cursor:
                        break

            if syms:
                _symbols = syms
                logger.info(f"Bybit: загружено {len(_symbols)} символов")
                return _symbols

            logger.warning(f"Bybit fetch_symbols: пустой список, попытка {attempt+1}/5")
            await asyncio.sleep(5)

        except Exception as e:
            logger.warning(f"Bybit fetch_symbols попытка {attempt+1}/5: {e}")
            await asyncio.sleep(5)

    logger.error("Bybit: не удалось загрузить символы после 5 попыток, продолжаем без них")
    return _symbols


async def run_oi_polling() -> None:
    """
    Один REST вызов /v5/market/tickers (без symbol) возвращает сразу все тикеры.
    Берём openInterest и записываем в oi_history["bybit"].
    Обновляем price_history["bybit"] как дополнительный источник цены (резерв).
    """
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

                oi_str    = item.get("openInterest", "")
                price_str = item.get("lastPrice", "")
                fr_str    = item.get("fundingRate", "")

                try:
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
    """Одно WS соединение для батча символов — обновляем price_history в реальном времени."""
    topics = [f"tickers.{s}" for s in symbols]
    while True:
        try:
            async with websockets.connect(BYBIT_WS, ping_interval=None) as ws:
                # Подписываемся порциями по 10 (ограничение Bybit)
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
                        # Данные приходят как snapshot (первый раз) и delta (изменения)
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
                            fr_str = d.get("fundingRate", "")
                            if fr_str:
                                try:
                                    funding_rates["bybit"][sym] = float(fr_str)
                                except ValueError:
                                    pass
                finally:
                    hb.cancel()

        except Exception as e:
            logger.warning(f"Bybit WS batch error: {e} — реконнект через {WS_RECONNECT}с")
            await asyncio.sleep(WS_RECONNECT)


async def fetch_ls_ratio(symbol: str) -> float | None:
    """Long/Short Account Ratio с Bybit. Возвращает buyRatio (0.0–1.0) или None."""
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


async def run_price_ws() -> None:
    """Запускаем батчи WS соединений для всех символов."""
    if not _symbols:
        logger.warning("Bybit WS: символы ещё не загружены")
        return

    tasks = [
        asyncio.create_task(_ws_batch(_symbols[i : i + BYBIT_BATCH]))
        for i in range(0, len(_symbols), BYBIT_BATCH)
    ]
    await asyncio.gather(*tasks)
