"""
In-memory хранилище для агрегатора.
"""

import json
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DAILY_DUMP_FILE = os.path.join(os.path.dirname(__file__), "daily_counts.json")

# История цен и OI
price_history: dict[str, dict[str, deque]] = defaultdict(
    lambda: defaultdict(lambda: deque(maxlen=4000))
)
oi_history: dict[str, dict[str, deque]] = defaultdict(
    lambda: defaultdict(lambda: deque(maxlen=400))
)

# Текущие funding rates
funding_rates: dict[str, dict[str, float]] = {
    "binance": {},
    "bybit": {},
}

# Long/Short ratio: доля аккаунтов в лонге (0.0–1.0)
# Обновляется по запросу при появлении кандидата на сигнал
ls_ratio: dict[str, dict[str, float]] = {
    "binance": {},
    "bybit": {},
}

# Время последнего обновления L/S ratio (чтобы не запрашивать слишком часто)
_ls_ratio_ts: dict[str, dict[str, float]] = {
    "binance": {},
    "bybit": {},
}
LS_RATIO_TTL = 300  # обновляем L/S ratio не чаще раза в 5 мин

# ---------- Cooldown ----------

_last_signal_ts: dict[str, float] = {}


def can_signal(key: str, cooldown_sec: int) -> bool:
    return (time.time() - _last_signal_ts.get(key, 0.0)) >= cooldown_sec


def mark_signal(key: str) -> None:
    _last_signal_ts[key] = time.time()


def ls_ratio_is_stale(exchange: str, symbol: str) -> bool:
    """True если L/S ratio не обновлялся дольше TTL."""
    last = _ls_ratio_ts[exchange].get(symbol, 0.0)
    return (time.time() - last) >= LS_RATIO_TTL


def update_ls_ratio(exchange: str, symbol: str, value: float) -> None:
    ls_ratio[exchange][symbol] = value
    _ls_ratio_ts[exchange][symbol] = time.time()


# ---------- Счётчики сигналов за день ----------

_daily_counts: dict[str, int] = defaultdict(int)
_daily_date = None


def _reset_if_new_day() -> None:
    global _daily_date
    today = datetime.now(timezone.utc).date()
    if _daily_date != today:
        _daily_counts.clear()
        _daily_date = today


def increment_daily_count(key: str) -> int:
    _reset_if_new_day()
    _daily_counts[key] += 1
    _save_daily_counts()
    return _daily_counts[key]


def _save_daily_counts() -> None:
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
            logger.info(f"Счётчики загружены: {sum(_daily_counts.values())} сигналов")
    except Exception as e:
        logger.warning(f"Не удалось загрузить счётчики: {e}")


# ---------- Вспомогательная функция ----------

def value_n_seconds_ago(history: deque, seconds: float) -> float | None:
    """Значение ближайшее к (now - seconds). История от старого к новому."""
    target = time.time() - seconds
    result = None
    for ts, val in history:
        if ts <= target:
            result = val
        else:
            break
    return result
