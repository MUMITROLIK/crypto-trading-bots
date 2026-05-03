"""
Aggregator Bot — точка входа.

Что делает:
  Собирает данные с Binance + Bybit (цена, OI, funding, L/S ratio)
  и каждые 30с проверяет все символы по скоринговой системе.
  При накоплении достаточно баллов отправляет LONG или SHORT сигнал.

Запуск:
  python main.py
"""

import asyncio
import logging

import binance as bnc
import bybit as bbt
import screener
import notifier
from config import POLL_INTERVAL, OI_POLL_INTERVAL
from data_store import load_daily_counts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


async def signal_loop() -> None:
    """Каждые POLL_INTERVAL секунд проверяем все символы."""
    # Ждём первых данных (минимум 3 цикла polling)
    await asyncio.sleep(OI_POLL_INTERVAL * 3 + 5)
    logger.info("Signal loop запущен")

    while True:
        try:
            signals = await screener.check_all()
            for sig in signals:
                text = notifier.format_signal(sig)
                await notifier.send(text)
            if signals:
                logger.info(f"Отправлено {len(signals)} сигналов")
        except Exception as e:
            logger.error(f"Signal loop: {e}")

        await asyncio.sleep(POLL_INTERVAL)


async def main() -> None:
    logger.info("=" * 50)
    logger.info("Aggregator Bot — запуск")
    logger.info("=" * 50)

    load_daily_counts()

    await asyncio.gather(
        bnc.fetch_symbols(),
        bbt.fetch_symbols(),
    )

    await notifier.send_startup()

    await asyncio.gather(
        bnc.run_price_ws(),
        bnc.run_price_polling(),
        bnc.run_oi_polling(),
        bnc.run_funding_polling(),
        bbt.run_oi_polling(),
        bbt.run_price_ws(),
        signal_loop(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Агрегатор остановлен")
