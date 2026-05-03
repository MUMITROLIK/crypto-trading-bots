import json
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
_DAILY_DUMP_FILE = os.path.join(os.path.dirname(__file__), "daily_counts.json")

# ~35 мин при WS обновлении раз в 1с (нужно 30 мин для DUMP окна)
price_history: dict[str, dict[str, deque]] = defaultdict(
    lambda: defaultdict(lambda: deque(maxlen=2500))
)

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


_last_signal_ts: dict[str, float] = {}


def can_signal(key: str, cooldown_sec: int) -> bool:
    return (time.time() - _last_signal_ts.get(key, 0.0)) >= cooldown_sec


def mark_signal(key: str) -> None:
    _last_signal_ts[key] = time.time()


def value_n_seconds_ago(history: deque, seconds: float) -> float | None:
    target = time.time() - seconds
    result = None
    for ts, val in history:
        if ts <= target:
            result = val
        else:
            break
    return result
