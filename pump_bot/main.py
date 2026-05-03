"""
Pump Screener Bot — точка входа.

Запуск:
    python main.py

Логика:
  LONG  сигнал: цена выросла >= 2%  за последние 2  мин
  SHORT сигнал: цена выросла >= 10% за последние 20 мин

Warmup: LONG готов через ~2 мин после старта, SHORT — через ~20 мин.
"""

import asyncio
import logging

import binance as bnc
import bybit as bbt
import screener
import notifier
from config import PRICE_POLL_INTERVAL
from data_store import load_daily_counts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


async def signal_loop() -> None:
    # Ждём накопления хотя бы пары точек
    await asyncio.sleep(PRICE_POLL_INTERVAL * 3)

    while True:
        signals = screener.check_all()
        for sig in signals:
            text = notifier.format_signal(sig)
            await notifier.send(text)

        await asyncio.sleep(PRICE_POLL_INTERVAL)


async def main() -> None:
    logger.info("=" * 50)
    logger.info("Pump Screener Bot — запуск")
    logger.info("=" * 50)

    load_daily_counts()

    await asyncio.gather(
        bnc.fetch_symbols(),
        bbt.fetch_symbols(),
    )

    await notifier.send_startup()

    await asyncio.gather(
        bnc.run_price_ws(),      # Binance: реальное время через aiohttp WS
        bnc.run_price_polling(), # Binance: REST резерв каждые 10с
        bbt.run_price_ws(),      # Bybit: реальное время
        bbt.run_price_rest(),    # Bybit: REST резерв
        signal_loop(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
