"""
Liquidation Screener Bot — точка входа.

Запуск:
    python main.py

Логика:
  Слушаем WebSocket потоки ликвидаций в реальном времени.
  При ликвидации >= $20,000 мгновенно отправляем сигнал в Telegram.
  Cooldown 30с на символ — не дублируем мелкие серии ликвидаций.

Warmup: нет, сигналы идут сразу после подключения WS.
"""

import asyncio
import logging

import binance_ws as bnc
import bybit_ws as bbt
import notifier
import data_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


async def main() -> None:
    logger.info("=" * 50)
    logger.info("Liquidation Screener Bot — запуск")
    logger.info("=" * 50)

    data_store.load_daily_counts()

    await bbt.fetch_symbols()

    await notifier.send_startup()

    await asyncio.gather(
        bnc.run_liq_ws(),
        bbt.run_liq_ws(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
