"""
Логика OI-сигналов.

Условие сигнала (всё должно выполниться одновременно):
  1. OI вырос на >= OI_THRESHOLD_PCT% за последние OI_PERIOD_MIN минут
  2. Цена тоже выросла за тот же период (иначе деньги заходят в шорты)
  3. Цена выросла НЕ БОЛЬШЕ OI_MAX_PRICE_PCT% — фильтр раннего входа:
     OI растёт быстрее цены = деньги заходят ДО пампа, а не во время
  4. Прошёл SIGNAL_COOLDOWN с последнего сигнала по этому символу

Результат: dict с данными для Telegram или None.
"""

import logging

from config import (
    OI_PERIOD_MIN, OI_THRESHOLD_PCT, OI_MIN_PRICE_PCT, OI_MAX_PRICE_PCT,
    OI_MAX_1H_PRICE_PCT, FUNDING_MIN, OI_WATCH_PCT, SIGNAL_COOLDOWN,
    SPIKE_PERIOD_MIN, SPIKE_THRESHOLD_PCT, SPIKE_MAX_PRICE_PCT, SPIKE_COOLDOWN,
)
from data_store import (
    oi_history,
    price_history,
    funding_rates,
    value_n_seconds_ago,
    get_cvd_change,
    can_signal,
    mark_signal,
    increment_daily_count,
    get_daily_count,
)
import cvd_tracker

logger = logging.getLogger(__name__)


def check(exchange: str, symbol: str) -> dict | None:
    oi_hist    = oi_history[exchange].get(symbol)
    price_hist = price_history[exchange].get(symbol)

    # Нужно хотя бы 2 точки чтобы считать изменение
    if not oi_hist or len(oi_hist) < 2:
        return None
    if not price_hist or len(price_hist) < 2:
        return None

    period_sec = OI_PERIOD_MIN * 60

    # --- OI ---
    old_oi = value_n_seconds_ago(oi_hist, period_sec)
    if old_oi is None or old_oi == 0:
        return None

    current_oi = oi_hist[-1][1]
    oi_change_pct = (current_oi - old_oi) / old_oi * 100

    # Запускаем CVD подписку при достижении watch threshold (до основного порога)
    if oi_change_pct >= OI_WATCH_PCT:
        cvd_tracker.start_watch(exchange, symbol)

    if oi_change_pct < OI_THRESHOLD_PCT:
        return None

    # --- Цена ---
    old_price     = value_n_seconds_ago(price_hist, period_sec)
    current_price = price_hist[-1][1]

    if old_price is None or old_price == 0:
        return None

    price_change_pct = (current_price - old_price) / old_price * 100

    # Если цена не растёт — деньги заходят в шорты, нам не интересно
    if price_change_pct <= 0:
        return None

    # Минимальный рост цены: отсекаем шум (0.1-0.3% это не движение, это колебание)
    if price_change_pct < OI_MIN_PRICE_PCT:
        return None

    # Фильтр раннего входа: если цена уже сильно выросла — пропускаем.
    # OI должен расти быстрее цены (накопление ДО пампа, не во время).
    if OI_MAX_PRICE_PCT > 0 and price_change_pct > OI_MAX_PRICE_PCT:
        return None

    # Фильтр "не опоздал ли": если за последний час цена уже сделала большой памп,
    # значит OI высокий — остаток после пампа, а не накопление перед ним.
    old_price_1h = value_n_seconds_ago(price_hist, 3600)
    price_change_1h = None
    if old_price_1h and old_price_1h > 0:
        price_change_1h = round((current_price - old_price_1h) / old_price_1h * 100, 1)

    # Если памп уже был за последний час — поздно
    if OI_MAX_1H_PRICE_PCT > 0 and price_change_1h is not None and price_change_1h > OI_MAX_1H_PRICE_PCT:
        return None

    # Если за последний час цена падала — OI растёт на шортах, не на лонгах
    if price_change_1h is not None and price_change_1h < 0:
        return None

    # --- Funding Rate ---
    fr = funding_rates[exchange].get(symbol)
    if fr is not None and fr < FUNDING_MIN:
        return None

    # --- CVD ---
    # Проверяем два окна:
    # 1. CVD(15м) > 0 — за период OI покупок больше чем продаж
    # 2. CVD(5м) > 0  — покупки СЕЙЧАС активны, не затухают
    # Если 5-мин CVD ≈ 0 или отрицательный — покупательский импульс иссяк, поздно.
    cvd = get_cvd_change(exchange, symbol, window_sec=OI_PERIOD_MIN * 60)
    if cvd is not None and cvd <= 0:
        logger.info(f"[CVD15] {exchange.upper()} {symbol}: {cvd:,.0f} ≤ 0 → продавцы, пропуск")
        return None

    cvd_5m = get_cvd_change(exchange, symbol, window_sec=300)
    if cvd_5m is not None and cvd_5m <= 0:
        logger.info(f"[CVD5] {exchange.upper()} {symbol}: {cvd_5m:,.0f} ≤ 0 → импульс угас, пропуск")
        return None

    # 3. CVD(5м) / CVD(15м) >= 15% — импульс не угасает
    # Если 5м CVD составляет < 15% от 15м CVD — основная покупка была раньше,
    # бот поймал хвост движения, входить поздно.
    if cvd is not None and cvd > 0 and cvd_5m is not None:
        ratio = cvd_5m / cvd
        if ratio < 0.15:
            logger.info(
                f"[CVD ratio] {exchange.upper()} {symbol}: "
                f"5м/15м = {ratio:.0%} ({cvd_5m:,.0f}/{cvd:,.0f}) < 15% → хвост движения, пропуск"
            )
            return None

    # --- Cooldown ---
    cooldown_key = f"{exchange}:{symbol}"
    if not can_signal(cooldown_key, SIGNAL_COOLDOWN):
        return None

    # --- Всё ок, генерируем сигнал ---
    mark_signal(cooldown_key)
    signal_num = increment_daily_count(cooldown_key)

    oi_usd = current_oi * current_price   # переводим монеты → доллары

    logger.info(
        f"СИГНАЛ OI #{signal_num} | {exchange.upper()} {symbol} "
        f"OI+{oi_change_pct:.1f}% цена+{price_change_pct:.1f}%"
        + (f" 1ч:{price_change_1h:+.1f}%" if price_change_1h is not None else "")
    )

    return {
        "exchange":         exchange,
        "symbol":           symbol,
        "signal_num":       signal_num,
        "oi_change_pct":    round(oi_change_pct, 1),
        "price_change_pct": round(price_change_pct, 2),
        "price_change_1h":  price_change_1h,
        "oi_usd":           oi_usd,
        "period_min":       OI_PERIOD_MIN,
        "funding_rate":     fr,      # float или None
        "cvd_15m":          cvd,     # float или None
        "cvd_5m":           cvd_5m,  # float или None
    }


def check_spike(exchange: str, symbol: str) -> dict | None:
    """
    Fast Spike детектор — ловит резкие OI спайки за 5 минут.
    Более ранний сигнал чем основной OI бот.
    CVD не используется (нет времени накопить при резком спайке).
    Требует ручной проверки перед входом.
    """
    oi_hist    = oi_history[exchange].get(symbol)
    price_hist = price_history[exchange].get(symbol)

    if not oi_hist or len(oi_hist) < 2:
        return None
    if not price_hist or len(price_hist) < 2:
        return None

    period_sec = SPIKE_PERIOD_MIN * 60  # 300 секунд

    # --- OI за 5 минут ---
    old_oi = value_n_seconds_ago(oi_hist, period_sec)
    if old_oi is None or old_oi == 0:
        return None

    current_oi    = oi_hist[-1][1]
    oi_change_pct = (current_oi - old_oi) / old_oi * 100

    if oi_change_pct < SPIKE_THRESHOLD_PCT:
        return None

    # --- Цена за 5 минут ---
    old_price     = value_n_seconds_ago(price_hist, period_sec)
    current_price = price_hist[-1][1]

    if old_price is None or old_price == 0:
        return None

    price_change_pct = (current_price - old_price) / old_price * 100

    # Цена должна расти заметно (< 0.3% = шум или шорты)
    if price_change_pct <= 0.3:
        return None

    # Цена не должна уже улететь — входим в начале, не в конце
    if price_change_pct > SPIKE_MAX_PRICE_PCT:
        return None

    # --- Часовой контекст ---
    old_price_1h    = value_n_seconds_ago(price_hist, 3600)
    price_change_1h = None
    if old_price_1h and old_price_1h > 0:
        price_change_1h = round((current_price - old_price_1h) / old_price_1h * 100, 1)

    # Если час в минусе — OI растёт на шортах, не на лонгах
    if price_change_1h is not None and price_change_1h < 0:
        return None

    # Если час уже сильно выросли — памп уже прошёл
    if price_change_1h is not None and price_change_1h > 10:
        return None

    # --- Funding Rate ---
    fr = funding_rates[exchange].get(symbol)
    if fr is not None and fr < FUNDING_MIN:
        return None

    # --- Cooldown spike (30 мин) ---
    spike_key = f"{exchange}:{symbol}:spike"
    if not can_signal(spike_key, SPIKE_COOLDOWN):
        return None

    # Не шлём spike если основной OI сигнал был недавно (30 мин)
    oi_key = f"{exchange}:{symbol}"
    if not can_signal(oi_key, SPIKE_COOLDOWN):
        return None

    mark_signal(spike_key)
    signal_num = increment_daily_count(oi_key)

    oi_usd = current_oi * current_price

    logger.info(
        f"⚡ SPIKE #{signal_num} | {exchange.upper()} {symbol} "
        f"OI+{oi_change_pct:.1f}% за 5м, цена+{price_change_pct:.1f}%"
    )

    return {
        "type":             "spike",
        "exchange":         exchange,
        "symbol":           symbol,
        "signal_num":       signal_num,
        "oi_change_pct":    round(oi_change_pct, 1),
        "price_change_pct": round(price_change_pct, 2),
        "price_change_1h":  price_change_1h,
        "oi_usd":           oi_usd,
        "period_min":       SPIKE_PERIOD_MIN,
        "funding_rate":     fr,
    }


def check_all() -> list[dict]:
    """Проверяем сигналы по всем символам на обеих биржах."""
    results = []
    for exchange in ("binance", "bybit"):
        for symbol in list(oi_history[exchange].keys()):
            sig = check(exchange, symbol)
            if sig:
                results.append(sig)
            spike = check_spike(exchange, symbol)
            if spike:
                results.append(spike)
    return results
