"""
OI Screener Bot — точка входа.

Запуск:
    python main.py

Что делает:
  1. Загружает символы с Binance и Bybit
  2. Запускает параллельно:
       - Binance price WebSocket (реальное время)
       - Binance OI REST polling (каждые 30с)
       - Bybit price WebSocket (батчи)
       - Bybit tickers REST polling (OI + цена каждые 30с)
  3. Каждые 30 секунд проверяет все символы на сигнал
  4. При сигнале отправляет сообщение в Telegram
"""

import asyncio
import logging

import binance as bnc
import bybit as bbt
import screener
import notifier
import cvd_tracker
import aggregator
import liq_listener
import trade_tracker
import trade_bot
from config import OI_POLL_INTERVAL, AGG_POLL_INTERVAL
from data_store import (
    oi_history, price_history, value_n_seconds_ago,
    load_oi_cache, save_oi_cache,
    load_price_cache, save_price_cache,
    load_daily_counts,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


async def debug_loop() -> None:
    """Каждые 30с печатаем статистику накопленных данных."""
    await asyncio.sleep(35)
    while True:
        for exchange in ("binance", "bybit"):
            oi_count = len(oi_history[exchange])
            price_count = len(price_history[exchange])
            logger.info(f"[DEBUG] {exchange}: OI символов={oi_count}, цена символов={price_count}")

            # Показываем топ-5 символов с наибольшим изменением OI за 15 мин
            results = []
            for sym, hist in list(oi_history[exchange].items())[:50]:
                if len(hist) < 2:
                    continue
                old = value_n_seconds_ago(hist, 15 * 60)
                if old and old > 0:
                    cur = hist[-1][1]
                    chg = (cur - old) / old * 100
                    results.append((sym, chg))
            results.sort(key=lambda x: x[1], reverse=True)
            if results:
                top = results[:3]
                logger.info(f"[DEBUG] {exchange} топ OI изменений: " +
                            ", ".join(f"{s}={c:.1f}%" for s, c in top))
            else:
                logger.info(f"[DEBUG] {exchange}: нет данных для расчёта изменения OI")

        await asyncio.sleep(30)


async def aggregator_loop() -> None:
    """Каждые AGG_POLL_INTERVAL секунд сопоставляем все индикаторы."""
    await asyncio.sleep(OI_POLL_INTERVAL * 3 + 5)  # ждём первых данных
    while True:
        await aggregator.check_and_send()
        await asyncio.sleep(AGG_POLL_INTERVAL)


async def trade_monitor_loop() -> None:
    """Каждые 30с проверяем открытые сделки — шлём уведомление при TP/SL."""
    await asyncio.sleep(60)  # ждём пока накопятся данные по ценам
    while True:
        notifications = trade_tracker.check_trades()
        for n in notifications:
            text = trade_tracker.format_notification(n)
            await trade_bot.send_notification(text)  # шлём в Trade Bot
        await asyncio.sleep(30)


async def cache_loop() -> None:
    """Каждые 5 минут сохраняем OI, Price историю и трейды на диск."""
    while True:
        await asyncio.sleep(300)
        save_oi_cache()
        save_price_cache()
        trade_tracker.save_trades()


async def signal_loop() -> None:
    """Каждые OI_POLL_INTERVAL секунд проверяем все символы на сигнал."""
    # Даём боту время набрать первые данные (минимум один цикл polling)
    await asyncio.sleep(OI_POLL_INTERVAL + 5)

    while True:
        signals = screener.check_all()
        for sig in signals:
            if sig.get("type") == "spike":
                text = notifier.format_spike(sig)
            else:
                text = notifier.format_signal(sig)
            await notifier.send(text)

        await asyncio.sleep(OI_POLL_INTERVAL)


async def main() -> None:
    logger.info("=" * 50)
    logger.info("OI Screener Bot — запуск")
    logger.info("=" * 50)

    # Загружаем кэш с прошлого запуска
    load_oi_cache()
    load_price_cache()
    load_daily_counts()
    trade_tracker.load_trades()

    # Загружаем символы с обеих бирж
    await asyncio.gather(
        bnc.fetch_symbols(),
        bbt.fetch_symbols(),
    )

    # Уведомляем в Telegram что боты запустились
    await notifier.send_startup()
    await aggregator.send_startup()

    # Запускаем все фоновые задачи
    await asyncio.gather(
        bnc.run_price_ws(),
        bnc.run_price_polling(),
        bnc.run_oi_polling(),
        bnc.run_funding_polling(),
        bbt.run_price_ws(),
        bbt.run_oi_polling(),
        signal_loop(),
        cache_loop(),
        debug_loop(),
        cvd_tracker.cleanup_loop(),
        aggregator_loop(),
        trade_monitor_loop(),
        trade_bot.run(),
        # Лёгкий листенер ликвидаций — только запись в data_store,
        # сигналы НЕ шлёт. Нужен агрегатору для скоринга.
        liq_listener.run_binance_liq_ws(),
        liq_listener.run_bybit_liq_ws(bbt._symbols),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
