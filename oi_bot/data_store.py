"""
Глобальное in-memory хранилище для всех данных бота.

Структура:
  price_history[exchange][symbol] = deque[(timestamp, price), ...]
  oi_history[exchange][symbol]    = deque[(timestamp, oi_coins), ...]

Всё обновляется из binance.py / bybit.py.
Screener читает отсюда для расчёта сигналов.
"""

import json
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_OI_DUMP_FILE    = os.path.join(os.path.dirname(__file__), "oi_cache.json")
_PRICE_DUMP_FILE = os.path.join(os.path.dirname(__file__), "price_cache.json")
_DAILY_DUMP_FILE = os.path.join(os.path.dirname(__file__), "daily_counts.json")

# ---------- Исторические данные ----------

price_history: dict[str, dict[str, deque]] = defaultdict(
    lambda: defaultdict(lambda: deque(maxlen=4000))  # ~1ч при WS обновлении раз в 1с
)

oi_history: dict[str, dict[str, deque]] = defaultdict(
    lambda: defaultdict(lambda: deque(maxlen=400))   # ~1ч при polling раз в 10с
)

# Текущие funding rates (обновляются каждую минуту)
# Значение: float, например 0.0001 = +0.01% (лонги платят), -0.0001 = -0.01% (шорты платят)
funding_rates: dict[str, dict[str, float]] = {
    "binance": {},
    "bybit": {},
}

# Long/Short ratio: доля аккаунтов в лонге (0.0–1.0)
# Обновляется по запросу агрегатора (не чаще раза в AGG_LS_TTL секунд)
ls_ratio: dict[str, dict[str, float]] = {
    "binance": {},
    "bybit": {},
}
_ls_ratio_ts: dict[str, dict[str, float]] = {
    "binance": defaultdict(float),
    "bybit":   defaultdict(float),
}


def ls_ratio_is_stale(exchange: str, symbol: str, ttl: float) -> bool:
    return (time.time() - _ls_ratio_ts[exchange][symbol]) >= ttl


def update_ls_ratio(exchange: str, symbol: str, value: float) -> None:
    ls_ratio[exchange][symbol] = value
    _ls_ratio_ts[exchange][symbol] = time.time()

# ---------- Liquidation events (для агрегатора) ----------
# Хранит последние ликвидации: (timestamp, side, usd)
# Только запись — сигналы шлёт liq_bot, мы просто читаем для скоринга

liq_events: dict[str, dict[str, deque]] = defaultdict(
    lambda: defaultdict(lambda: deque(maxlen=100))
)


def record_liq(exchange: str, symbol: str, side: str, usd: float) -> None:
    """Записываем ликвидацию. side = 'LONG' или 'SHORT'."""
    liq_events[exchange][symbol].append((time.time(), side, usd))


def get_recent_liqs(exchange: str, symbol: str, window_sec: float = 300) -> list:
    """Возвращает ликвидации за последние window_sec секунд."""
    hist = liq_events[exchange].get(symbol)
    if not hist:
        return []
    cutoff = time.time() - window_sec
    return [(ts, side, usd) for ts, side, usd in hist if ts >= cutoff]


# ---------- CVD (Cumulative Volume Delta) ----------
# Хранит накопленный CVD: sum(buy_qty - sell_qty) с момента подписки
# Обновляется из cvd_tracker.py по каждой сделке

cvd_history: dict[str, dict[str, deque]] = defaultdict(
    lambda: defaultdict(lambda: deque(maxlen=3000))  # ~30 мин при 1 сделке/сек
)
_cvd_running: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))


def add_trade(exchange: str, symbol: str, qty: float, is_buy: bool,
              price: float = 0.0) -> None:
    """Добавляем сделку — пересчитываем CVD и Footprint."""
    delta = qty if is_buy else -qty
    _cvd_running[exchange][symbol] += delta
    cvd_history[exchange][symbol].append((time.time(), _cvd_running[exchange][symbol]))
    # Footprint: записываем объём по ценовому уровню
    if price > 0:
        _record_footprint(exchange, symbol, price, qty, is_buy)


def reset_cvd(exchange: str, symbol: str) -> None:
    """Сбрасываем CVD при старте новой подписки."""
    _cvd_running[exchange][symbol] = 0.0
    cvd_history[exchange][symbol].clear()


def get_cvd_change(exchange: str, symbol: str, window_sec: float = 900) -> float | None:
    """
    Возвращает изменение CVD за последние window_sec секунд.
    Положительное = покупатели доминируют.
    Отрицательное = продавцы доминируют.
    None если данных меньше 30 секунд (слишком рано судить).
    """
    hist = cvd_history[exchange].get(symbol)
    if not hist or len(hist) < 5:
        return None

    now = time.time()
    if now - hist[0][0] < 30:
        return None  # менее 30 секунд данных — не считаем

    current_cvd = hist[-1][1]
    target = now - window_sec
    old_cvd = None
    for ts, val in hist:
        if ts <= target:
            old_cvd = val
        else:
            break

    # Если данных меньше window_sec — возвращаем всё накопленное с начала
    return current_cvd - old_cvd if old_cvd is not None else current_cvd


# ---------- Footprint (дельта по ценовым уровням) ----------
# Храним сделки потоком: (ts, bucket_price, buy_usd, sell_usd)
# bucket_price = цена округлённая до ~0.2% разрешения
# Агрегатор запрашивает дельту в окне ±1.5% от текущей цены

_footprint_trades: dict[str, dict[str, deque]] = defaultdict(
    lambda: defaultdict(lambda: deque(maxlen=5000))  # ~1ч активной торговли
)


def _price_bucket(price: float) -> float:
    """
    Округляет цену до 3 значимых цифр — это ~0.1-0.5% разрешение.
    Работает для любых монет: PEPE=$0.0000123, BTC=$60000.
    """
    import math as _m
    if price <= 0:
        return price
    mag = 10 ** (_m.floor(_m.log10(price)) - 2)   # 3 значимые цифры
    return round(price / mag) * mag


def _record_footprint(exchange: str, symbol: str,
                      price: float, qty: float, is_buy: bool) -> None:
    """Записываем сделку в footprint поток."""
    bucket = _price_bucket(price)
    usd = price * qty
    buy_usd  = usd if is_buy else 0.0
    sell_usd = usd if not is_buy else 0.0
    _footprint_trades[exchange][symbol].append(
        (time.time(), bucket, buy_usd, sell_usd)
    )


def get_footprint(exchange: str, symbol: str,
                  current_price: float,
                  window_sec: float = 300,
                  zone_pct: float = 1.5) -> dict[float, dict]:
    """
    Возвращает footprint — дельту покупок/продаж по уровням цены.
    Только уровни в ±zone_pct% от current_price за последние window_sec.

    Результат: {bucket_price: {"buy": $, "sell": $, "delta": $, "pct": %}}
    Положительная дельта = покупатели доминируют на этом уровне.
    Отрицательная дельта = продавцы.
    """
    trades = _footprint_trades[exchange].get(symbol)
    if not trades:
        return {}

    cutoff   = time.time() - window_sec
    p_lo     = current_price * (1 - zone_pct / 100)
    p_hi     = current_price * (1 + zone_pct / 100)

    buckets: dict[float, list] = {}
    for ts, bucket, buy_usd, sell_usd in trades:
        if ts < cutoff:
            continue
        if not (p_lo <= bucket <= p_hi):
            continue
        if bucket not in buckets:
            buckets[bucket] = [0.0, 0.0]
        buckets[bucket][0] += buy_usd
        buckets[bucket][1] += sell_usd

    result = {}
    for bucket, (buy, sell) in buckets.items():
        pct = (bucket - current_price) / current_price * 100
        result[bucket] = {
            "buy":   buy,
            "sell":  sell,
            "delta": buy - sell,
            "pct":   pct,
        }
    return result


def get_footprint_bias(exchange: str, symbol: str,
                       current_price: float,
                       window_sec: float = 300) -> float | None:
    """
    Суммарная дельта покупок/продаж в ±1.5% от цены за window_sec.
    + = покупатели доминируют на текущих уровнях (бычий footprint)
    - = продавцы доминируют (медвежий footprint)
    None если мало данных.
    """
    fp = get_footprint(exchange, symbol, current_price,
                       window_sec=window_sec, zone_pct=1.5)
    if not fp:
        return None
    total_buy  = sum(v["buy"]  for v in fp.values())
    total_sell = sum(v["sell"] for v in fp.values())
    if total_buy + total_sell < 100:   # меньше $100 — слишком мало данных
        return None
    return total_buy - total_sell

# ---------- Счётчики сигналов за день ----------

_daily_counts: dict[str, int] = defaultdict(int)   # ключ: "exchange:symbol"
_daily_date = None


def _reset_if_new_day() -> None:
    global _daily_date
    today = datetime.now(timezone.utc).date()
    if _daily_date != today:
        _daily_counts.clear()
        _daily_date = today


def get_daily_count(key: str) -> int:
    _reset_if_new_day()
    return _daily_counts[key]


def increment_daily_count(key: str) -> int:
    _reset_if_new_day()
    _daily_counts[key] += 1
    save_daily_counts()
    return _daily_counts[key]


def save_daily_counts() -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        with open(_DAILY_DUMP_FILE, "w") as f:
            json.dump({"date": today, "counts": dict(_daily_counts)}, f)
    except Exception as e:
        logger.warning(f"Не удалось сохранить счётчики: {e}")


def load_daily_counts() -> None:
    if not os.path.exists(_DAILY_DUMP_FILE):
        return
    try:
        with open(_DAILY_DUMP_FILE) as f:
            data = json.load(f)
        today = datetime.now(timezone.utc).date().isoformat()
        if data.get("date") == today:
            _daily_counts.update(data.get("counts", {}))
            total = sum(_daily_counts.values())
            logger.info(f"Счётчики сигналов загружены: {total} сигналов за сегодня")
    except Exception as e:
        logger.warning(f"Не удалось загрузить счётчики: {e}")


# ---------- Cooldown (защита от дублей) ----------

_last_signal_ts: dict[str, float] = {}   # ключ: "exchange:symbol"


def can_signal(key: str, cooldown_sec: int) -> bool:
    last = _last_signal_ts.get(key, 0.0)
    return (time.time() - last) >= cooldown_sec


def mark_signal(key: str) -> None:
    _last_signal_ts[key] = time.time()


# ---------- JSON persistence для OI истории ----------

def save_oi_cache() -> None:
    """Сохраняем OI историю в JSON файл."""
    try:
        data: dict = {}
        for exchange, symbols in oi_history.items():
            data[exchange] = {
                sym: list(hist) for sym, hist in symbols.items() if hist
            }
        with open(_OI_DUMP_FILE, "w") as f:
            json.dump(data, f)
        total = sum(len(v) for v in data.values())
        logger.debug(f"OI cache сохранён: {total} символов")
    except Exception as e:
        logger.warning(f"Не удалось сохранить OI cache: {e}")


def load_oi_cache() -> None:
    """Загружаем OI историю из JSON файла при старте."""
    if not os.path.exists(_OI_DUMP_FILE):
        return
    try:
        with open(_OI_DUMP_FILE) as f:
            data = json.load(f)
        cutoff = time.time() - 120 * 60  # выбрасываем данные старше 2 часов
        loaded = 0
        for exchange, symbols in data.items():
            for sym, entries in symbols.items():
                fresh = [(ts, val) for ts, val in entries if ts >= cutoff]
                if fresh:
                    oi_history[exchange][sym].extend(fresh)
                    loaded += 1
        logger.info(f"OI cache загружен: {loaded} символов")
    except Exception as e:
        logger.warning(f"Не удалось загрузить OI cache: {e}")


# ---------- JSON persistence для Price истории ----------

def save_price_cache() -> None:
    """Сохраняем историю цен в JSON файл (с прореживанием до 1 точки в 30с)."""
    try:
        data: dict = {}
        now = time.time()
        cutoff = now - 130 * 60  # только последние ~2 часа

        for exchange, symbols in price_history.items():
            data[exchange] = {}
            for sym, hist in symbols.items():
                if not hist:
                    continue
                # Прореживаем: одна точка каждые 30 секунд
                sampled: list = []
                last_ts = 0.0
                for ts, val in hist:
                    if ts < cutoff:
                        continue
                    if ts - last_ts >= 30:
                        sampled.append([ts, val])
                        last_ts = ts
                if sampled:
                    data[exchange][sym] = sampled

        with open(_PRICE_DUMP_FILE, "w") as f:
            json.dump(data, f)
        total = sum(len(v) for v in data.values())
        logger.debug(f"Price cache сохранён: {total} символов")
    except Exception as e:
        logger.warning(f"Не удалось сохранить price cache: {e}")


def load_price_cache() -> None:
    """Загружаем историю цен из JSON файла при старте."""
    if not os.path.exists(_PRICE_DUMP_FILE):
        return
    try:
        with open(_PRICE_DUMP_FILE) as f:
            data = json.load(f)
        cutoff = time.time() - 130 * 60  # выбрасываем данные старше 2 часов
        loaded = 0
        for exchange, symbols in data.items():
            for sym, entries in symbols.items():
                fresh = [(ts, val) for ts, val in entries if ts >= cutoff]
                if fresh:
                    price_history[exchange][sym].extend(fresh)
                    loaded += 1
        logger.info(f"Price cache загружен: {loaded} символов")
    except Exception as e:
        logger.warning(f"Не удалось загрузить price cache: {e}")


# ---------- Вспомогательная функция ----------

def value_n_seconds_ago(history: deque, seconds: float) -> float | None:
    """
    Возвращает значение из deque[(ts, val)] ближайшее к моменту (now - seconds).
    Предполагает порядок от старого к новому.
    """
    target = time.time() - seconds
    result = None
    for ts, val in history:
        if ts <= target:
            result = val
        else:
            break
    return result
