import logging

from config import (
    LONG_PERIOD_MIN, LONG_THRESHOLD_PCT,
    SHORT_PERIOD_MIN, SHORT_THRESHOLD_PCT,
    DUMP_PERIOD_MIN, DUMP_THRESHOLD_PCT,
    SIGNAL_COOLDOWN,
)
from data_store import (
    price_history,
    value_n_seconds_ago,
    can_signal,
    mark_signal,
    increment_daily_count,
)

logger = logging.getLogger(__name__)


def _check(exchange: str, symbol: str, period_min: int, threshold_pct: float, direction: str) -> dict | None:
    hist = price_history[exchange].get(symbol)
    if not hist or len(hist) < 2:
        return None

    old_price = value_n_seconds_ago(hist, period_min * 60)
    if old_price is None or old_price == 0:
        return None

    current_price = hist[-1][1]
    change_pct = (current_price - old_price) / old_price * 100

    # dump проверяем на отрицательное изменение
    if direction == "dump":
        if change_pct > -threshold_pct:
            return None
    else:
        if change_pct < threshold_pct:
            return None

    key = f"{direction}:{exchange}:{symbol}"
    if not can_signal(key, SIGNAL_COOLDOWN):
        return None

    mark_signal(key)
    signal_num = increment_daily_count(key)

    logger.info(
        f"{direction.upper()} #{signal_num} | {exchange.upper()} {symbol} "
        f"{change_pct:+.1f}% за {period_min} мин"
    )

    return {
        "direction":  direction,
        "exchange":   exchange,
        "symbol":     symbol,
        "signal_num": signal_num,
        "change_pct": round(change_pct, 2),
        "period_min": period_min,
        "old_price":  old_price,
        "cur_price":  current_price,
    }


def check_all() -> list[dict]:
    results = []
    for exchange in ("binance", "bybit"):
        for symbol in list(price_history[exchange].keys()):
            for direction, period, threshold in (
                ("long",  LONG_PERIOD_MIN,  LONG_THRESHOLD_PCT),
                ("short", SHORT_PERIOD_MIN, SHORT_THRESHOLD_PCT),
                ("dump",  DUMP_PERIOD_MIN,  DUMP_THRESHOLD_PCT),
            ):
                sig = _check(exchange, symbol, period, threshold, direction)
                if sig:
                    results.append(sig)
    return results
