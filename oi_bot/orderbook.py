"""
Order Book analyzer — ищет крупные стенки в стакане.

Трейдер использует это для:
- Определения сопротивления (крупные sell-ордера выше цены)
- Определения поддержки (крупные buy-ордера ниже цены)
- Выбора точки TP (ставит лимитку перед стенкой)

Binance: GET /fapi/v1/depth?symbol=X&limit=20
Bybit:   GET /v5/market/orderbook?symbol=X&category=linear&limit=20

Кэш 30 секунд на символ — не спамим API.
"""

import logging
import math
import time

import aiohttp

from config import BINANCE_REST, BYBIT_REST

logger = logging.getLogger(__name__)

_CACHE_TTL   = 30       # секунд кэш
_DEPTH       = 20       # уровней стакана
_WALL_MULT   = 3.0      # стенка = ордер в 3x больше среднего
_WALL_MIN_USD = 8_000   # минимум $8K чтобы считать стенкой

_cache: dict[str, tuple[float, dict]] = {}


# ── Fetch ────────────────────────────────────────────────────────────────

async def _fetch_binance(symbol: str) -> dict | None:
    url = f"{BINANCE_REST}/fapi/v1/depth?symbol={symbol}&limit={_DEPTH}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=3)) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                return {
                    "bids": [(float(p), float(q)) for p, q in data.get("bids", [])],
                    "asks": [(float(p), float(q)) for p, q in data.get("asks", [])],
                }
    except Exception as e:
        logger.debug(f"OB binance {symbol}: {e}")
        return None


async def _fetch_bybit(symbol: str) -> dict | None:
    url = (f"{BYBIT_REST}/v5/market/orderbook"
           f"?symbol={symbol}&category=linear&limit={_DEPTH}")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=3)) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                result = data.get("result", {})
                return {
                    "bids": [(float(p), float(q)) for p, q in result.get("b", [])],
                    "asks": [(float(p), float(q)) for p, q in result.get("a", [])],
                }
    except Exception as e:
        logger.debug(f"OB bybit {symbol}: {e}")
        return None


# ── Wall detection ────────────────────────────────────────────────────────

def _find_walls(levels: list[tuple[float, float]],
                current_price: float) -> list[dict]:
    """
    Возвращает крупные стенки из одной стороны стакана.
    Стенка = ордер >= WALL_MULT × средний размер И >= WALL_MIN_USD.
    """
    if len(levels) < 3:
        return []

    total_usd = sum(p * q for p, q in levels)
    avg_usd   = total_usd / len(levels)
    walls = []

    for price, qty in levels:
        usd = price * qty
        if usd >= avg_usd * _WALL_MULT and usd >= _WALL_MIN_USD:
            pct = (price - current_price) / current_price * 100
            walls.append({"price": price, "usd": usd, "pct": pct})

    return walls


async def get_walls(exchange: str,
                    symbol: str,
                    current_price: float) -> dict:
    """
    Возвращает ближайшие крупные стенки выше и ниже цены.

    Результат:
        {
          "ask_walls": [{"price": float, "usd": float, "pct": float}, ...],
          "bid_walls": [{"price": float, "usd": float, "pct": float}, ...],
        }
    ask_walls — сопротивление (выше, pct > 0)
    bid_walls — поддержка    (ниже,  pct < 0)
    """
    key    = f"{exchange}:{symbol}"
    cached = _cache.get(key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return cached[1]

    fetch = _fetch_binance if exchange == "binance" else _fetch_bybit
    raw   = await fetch(symbol)

    result: dict = {"ask_walls": [], "bid_walls": []}
    if raw:
        ask_walls = _find_walls(raw["asks"], current_price)
        bid_walls = _find_walls(raw["bids"], current_price)
        # Ближайшие к цене — сортируем по дистанции
        ask_walls.sort(key=lambda x: x["pct"])        # ближе сверху
        bid_walls.sort(key=lambda x: -x["pct"])       # ближе снизу
        result = {
            "ask_walls": ask_walls[:2],
            "bid_walls": bid_walls[:2],
        }

    _cache[key] = (time.time(), result)
    return result


# ── Volume Profile (time-at-price) ────────────────────────────────────────

def get_volume_zones(price_hist,
                     n: int = 3,
                     n_buckets: int = 40) -> list[float]:
    """
    Аппроксимация Volume Profile по истории цен.
    «Время на уровне» ≈ «объём на уровне» — работает для ликвидных монет.

    price_hist — deque[(ts, price), ...]
    Возвращает N ценовых уровней с наибольшей концентрацией.
    """
    if not price_hist or len(price_hist) < 10:
        return []

    prices = [p for _, p in price_hist]
    p_min, p_max = min(prices), max(prices)
    spread = p_max - p_min
    if spread < 1e-12:
        return []

    bucket_size = spread / n_buckets
    counts = [0] * n_buckets

    for p in prices:
        idx = min(int((p - p_min) / bucket_size), n_buckets - 1)
        counts[idx] += 1

    # Топ-N бакетов по количеству точек (= время на уровне)
    top_idx = sorted(range(n_buckets), key=lambda i: -counts[i])[:n]
    zones = sorted([p_min + (i + 0.5) * bucket_size for i in top_idx])
    return zones


# ── Helpers ───────────────────────────────────────────────────────────────

def fmt_usd(v: float) -> str:
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


def fmt_price(price: float) -> str:
    """Форматирует цену под количество значимых цифр монеты."""
    if price <= 0:
        return str(price)
    mag = math.floor(math.log10(price))
    decimals = max(0, 4 - mag)
    return f"{price:.{decimals}f}"
