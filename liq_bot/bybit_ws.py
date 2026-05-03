"""
Bybit V5: ликвидации через WebSocket топик allLiquidation.{symbol}

Правильный формат подписки:
  {"op": "subscribe", "args": ["allLiquidation.BTCUSDT", "allLiquidation.ETHUSDT", ...]}

Данные (data — массив):
  s  — символ
  S  — "Buy"  → LONG  ликвидирован
       "Sell" → SHORT ликвидирован
  p  — цена банкротства
  v  — размер ликвидации (монеты)
  USD = p * v

Символы делятся на батчи по BYBIT_BATCH штук — каждый батч отдельное WS соединение.
"""

import asyncio
import json
import logging
import time

import aiohttp

import notifier
import liq_store
import data_store
from config import BYBIT_REST, BYBIT_WS, LIQ_MIN_USD, LIQ_COOLDOWN, WS_RECONNECT, BYBIT_BATCH

logger = logging.getLogger(__name__)

_symbols: list[str] = []
_last_signal: dict[str, float] = {}


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


def _can_signal(symbol: str) -> bool:
    return (time.time() - _last_signal.get(symbol, 0.0)) >= LIQ_COOLDOWN


def _mark(symbol: str) -> None:
    _last_signal[symbol] = time.time()


async def _ws_batch(symbols: list[str], batch_idx: int) -> None:
    """Одно WS соединение для batch символов."""
    # Формируем список топиков
    topics = [f"allLiquidation.{sym}" for sym in symbols]
    total_received = 0
    last_log_time = 0.0

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(BYBIT_WS, heartbeat=20) as ws:
                    # Отправляем подписки чанками по 10 (лимит Bybit)
                    for i in range(0, len(topics), 10):
                        chunk = topics[i : i + 10]
                        await ws.send_str(json.dumps({"op": "subscribe", "args": chunk}))
                    logger.info(
                        f"Bybit LIQ WS batch#{batch_idx}: подключено, {len(symbols)} символов"
                    )

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            total_received += 1
                            try:
                                data = json.loads(msg.data)

                                # Статус каждые 2 минуты
                                now = time.time()
                                if now - last_log_time >= 120:
                                    logger.info(
                                        f"[Bybit LIQ batch#{batch_idx}] живой, "
                                        f"сообщений: {total_received}"
                                    )
                                    last_log_time = now

                                # Первые 2 сообщения батча для диагностики
                                if total_received <= 2:
                                    logger.info(
                                        f"[Bybit LIQ batch#{batch_idx}] "
                                        f"msg #{total_received}: {msg.data[:200]}"
                                    )

                                # Ответ на подписку
                                if "success" in data:
                                    if data.get("success"):
                                        logger.info(
                                            f"Bybit LIQ batch#{batch_idx}: подписка успешна"
                                        )
                                    else:
                                        logger.warning(
                                            f"Bybit LIQ batch#{batch_idx}: "
                                            f"подписка не удалась: {data.get('ret_msg')}"
                                        )
                                    continue

                                # Обрабатываем только allLiquidation топики
                                if not data.get("topic", "").startswith("allLiquidation."):
                                    continue

                                # data["data"] — массив событий
                                events = data.get("data", [])
                                if isinstance(events, dict):
                                    events = [events]

                                for d in events:
                                    symbol   = d.get("s", "")
                                    side_raw = d.get("S", "")
                                    # Bybit: "Buy" = Long ликвидирован, "Sell" = Short
                                    side = "LONG" if side_raw == "Buy" else "SHORT"

                                    try:
                                        usd = float(d["p"]) * float(d["v"])
                                    except (KeyError, ValueError):
                                        continue

                                    # Дебаг: показываем все >= $1000
                                    if usd >= 1000:
                                        logger.info(
                                            f"[DEBUG] Bybit LIQ {side} {symbol}: "
                                            f"${usd:,.0f} (порог ${LIQ_MIN_USD:,})"
                                        )

                                    if usd < LIQ_MIN_USD:
                                        continue
                                    if not _can_signal(symbol):
                                        continue

                                    ratio      = liq_store.record(symbol, usd)
                                    signal_num = data_store.increment_daily_count(
                                        f"liq:bybit:{symbol}"
                                    )
                                    _mark(symbol)
                                    logger.info(
                                        f"Bybit LIQ {side} {symbol}: ${usd:,.0f} #{signal_num}"
                                        + (f" x{ratio}" if ratio else "")
                                    )
                                    asyncio.create_task(
                                        notifier.send(
                                            notifier.format_signal(
                                                symbol, side, usd, "bybit", ratio, signal_num
                                            )
                                        )
                                    )

                            except Exception as e:
                                logger.debug(f"Bybit LIQ batch#{batch_idx} parse: {e}")

                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            logger.warning(
                                f"Bybit LIQ WS batch#{batch_idx}: "
                                f"соединение закрыто ({msg.type})"
                            )
                            break

        except Exception as e:
            logger.warning(
                f"Bybit LIQ WS batch#{batch_idx}: {e} — реконнект через {WS_RECONNECT}с"
            )
            total_received = 0

        await asyncio.sleep(WS_RECONNECT)


async def run_liq_ws() -> None:
    """
    Запускает параллельные WS соединения батчами по BYBIT_BATCH символов каждое.
    """
    if not _symbols:
        logger.warning("Bybit LIQ: символов нет, пропускаем запуск WS")
        return

    batches = [
        _symbols[i : i + BYBIT_BATCH]
        for i in range(0, len(_symbols), BYBIT_BATCH)
    ]
    logger.info(
        f"Bybit LIQ: запуск {len(batches)} WS соединений "
        f"для {len(_symbols)} символов"
    )
    await asyncio.gather(*[_ws_batch(b, idx) for idx, b in enumerate(batches)])
