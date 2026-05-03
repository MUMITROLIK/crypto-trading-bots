"""
Хранилище истории ликвидаций для расчёта "объёма в X раз".

Для каждого символа храним последние N ликвидаций.
Отношение = текущая_сумма / среднее_по_истории.
"""

from collections import defaultdict, deque

# Последние 50 ликвидаций на символ (для расчёта среднего)
_liq_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))


def record(symbol: str, usd: float) -> float | None:
    """
    Записываем ликвидацию и возвращаем отношение к среднему.
    None если истории меньше 3 событий (среднее ненадёжно).
    """
    hist = _liq_history[symbol]
    avg = sum(hist) / len(hist) if hist else None
    hist.append(usd)

    if avg is None or len(hist) < 3:
        return None

    return round(usd / avg, 1)
