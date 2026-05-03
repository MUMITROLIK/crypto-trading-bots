"""
Aggregator Screener — комбинированный LONG/SHORT скоринг.

Система баллов:

  LONG (макс ~8):
    +3  OI вырос 5%+ за 15м             — новые деньги заходят
    +1  Цена 15м: +0.5% до +3%          — движение есть но не улетело
    +1  Цена 1ч: 0% до +5%              — восходящий тренд, не перегрет
    +1  Funding >= 0                    — бычий рынок
    +2  L/S ratio < 40% лонгов         — шорты перегружены → squeeze

  SHORT (макс ~12):
    +3  Цена 20м: 10%+                  — памп
    +2  Цена 15м: 5%+                   — быстрый рост
    +2  Цена 1ч: 8%+                    — уже давно пампится, поздно для лонга
    +2  Funding > 0.05%                 — лонги сильно переплачивают
    +2  L/S ratio > 65% лонгов         — толпа в лонгах → ликвидации
    +1  OI растёт при боковой цене      — шорты копятся

  Порог: LONG >= 5, SHORT >= 6
  Фильтр: OI в USD >= MIN_OI_USD
"""

import logging

import binance as bnc
import bybit as bbt
from config import LONG_MIN_SCORE, SHORT_MIN_SCORE, MIN_OI_USD, SIGNAL_COOLDOWN
from data_store import (
    oi_history, price_history, funding_rates,
    ls_ratio, ls_ratio_is_stale, update_ls_ratio,
    value_n_seconds_ago, can_signal, mark_signal, increment_daily_count,
)

logger = logging.getLogger(__name__)


async def _score_symbol(exchange: str, symbol: str) -> dict | None:
    oi_hist    = oi_history[exchange].get(symbol)
    price_hist = price_history[exchange].get(symbol)

    if not oi_hist or len(oi_hist) < 2:
        return None
    if not price_hist or len(price_hist) < 2:
        return None

    current_oi    = oi_hist[-1][1]
    current_price = price_hist[-1][1]

    # Фильтр по минимальному OI в USD
    oi_usd = current_oi * current_price
    if oi_usd < MIN_OI_USD:
        return None

    # --- Изменение OI за 15м ---
    old_oi = value_n_seconds_ago(oi_hist, 900)
    oi_change_15m = None
    if old_oi and old_oi > 0:
        oi_change_15m = (current_oi - old_oi) / old_oi * 100

    # --- Изменение цены ---
    old_price_15m = value_n_seconds_ago(price_hist, 900)
    old_price_20m = value_n_seconds_ago(price_hist, 1200)
    old_price_1h  = value_n_seconds_ago(price_hist, 3600)

    price_change_15m = (current_price - old_price_15m) / old_price_15m * 100 \
        if old_price_15m and old_price_15m > 0 else None
    price_change_20m = (current_price - old_price_20m) / old_price_20m * 100 \
        if old_price_20m and old_price_20m > 0 else None
    price_change_1h  = (current_price - old_price_1h) / old_price_1h * 100 \
        if old_price_1h and old_price_1h > 0 else None

    # --- Funding ---
    fr = funding_rates[exchange].get(symbol)

    # ===== СКОРИНГ =====
    score_long  = 0
    score_short = 0
    reasons_long:  list[str] = []
    reasons_short: list[str] = []

    # OI change
    if oi_change_15m is not None:
        if oi_change_15m >= 5:
            score_long += 3
            reasons_long.append(f"OI +{oi_change_15m:.1f}% за 15м")
        elif oi_change_15m >= 2 and price_change_15m is not None and price_change_15m <= 0.3:
            # OI растёт, цена стоит → шорты накапливаются
            score_short += 1
            reasons_short.append(f"OI +{oi_change_15m:.1f}% при цене {price_change_15m:+.1f}%")

    # Цена 15м
    if price_change_15m is not None:
        if 0.5 <= price_change_15m <= 3.0:
            score_long += 1
            reasons_long.append(f"Цена 15м +{price_change_15m:.1f}%")
        elif price_change_15m >= 5.0:
            score_short += 2
            reasons_short.append(f"Быстрый памп 15м +{price_change_15m:.1f}%")

    # Цена 20м (для шорта)
    if price_change_20m is not None and price_change_20m >= 10.0:
        score_short += 3
        reasons_short.append(f"Памп 20м +{price_change_20m:.1f}%")

    # Цена 1ч
    if price_change_1h is not None:
        if 0.0 <= price_change_1h <= 5.0:
            score_long += 1
            reasons_long.append(f"1ч +{price_change_1h:.1f}%")
        elif price_change_1h >= 8.0:
            score_short += 2
            reasons_short.append(f"1ч +{price_change_1h:.1f}% (уже разогрет)")

    # Funding
    if fr is not None:
        fr_pct = fr * 100
        if fr_pct >= 0:
            score_long += 1
            reasons_long.append(f"Funding +{fr_pct:.4f}%")
        if fr_pct > 0.05:
            score_short += 2
            reasons_short.append(f"Funding +{fr_pct:.4f}% (перегрев лонгов)")

    # Не тратим запрос на L/S если базовый счёт слишком мал
    base_score = max(score_long, score_short)
    if base_score < 3:
        return None

    # --- L/S ratio (запрашиваем только если данных нет или они устарели) ---
    if ls_ratio_is_stale(exchange, symbol):
        fetcher = bnc.fetch_ls_ratio if exchange == "binance" else bbt.fetch_ls_ratio
        val = await fetcher(symbol)
        if val is not None:
            update_ls_ratio(exchange, symbol, val)

    ls_val = ls_ratio[exchange].get(symbol)
    ls_str = None

    if ls_val is not None:
        long_pct = ls_val * 100
        ls_str = f"{long_pct:.0f}%"
        if long_pct < 40.0:
            score_long += 2
            reasons_long.append(f"L/S: {long_pct:.0f}% лонгов (шорты перегружены)")
        elif long_pct > 65.0:
            score_short += 2
            reasons_short.append(f"L/S: {long_pct:.0f}% лонгов (толпа в лонгах)")

    # ===== РЕШЕНИЕ =====
    direction: str | None = None
    score = 0
    reasons: list[str] = []

    if score_long >= LONG_MIN_SCORE and score_long >= score_short:
        direction = "long"
        score = score_long
        reasons = reasons_long
    elif score_short >= SHORT_MIN_SCORE:
        direction = "short"
        score = score_short
        reasons = reasons_short

    if direction is None:
        return None

    # Cooldown
    key = f"agg:{exchange}:{symbol}:{direction}"
    if not can_signal(key, SIGNAL_COOLDOWN):
        return None

    mark_signal(key)
    signal_num = increment_daily_count(f"agg:{exchange}:{symbol}")

    logger.info(
        f"{'🟢 LONG' if direction == 'long' else '🔴 SHORT'} #{signal_num} "
        f"| {exchange.upper()} {symbol} score={score} | {', '.join(reasons)}"
    )

    return {
        "direction":    direction,
        "exchange":     exchange,
        "symbol":       symbol,
        "signal_num":   signal_num,
        "score":        score,
        "reasons":      reasons,
        "oi_usd":       oi_usd,
        "price":        current_price,
        "oi_change":    round(oi_change_15m, 1) if oi_change_15m is not None else None,
        "price_15m":    round(price_change_15m, 2) if price_change_15m is not None else None,
        "price_1h":     round(price_change_1h, 1) if price_change_1h is not None else None,
        "funding":      fr,
        "ls_ratio":     ls_str,
    }


async def check_all() -> list[dict]:
    results = []
    for exchange in ("binance", "bybit"):
        for symbol in list(oi_history[exchange].keys()):
            sig = await _score_symbol(exchange, symbol)
            if sig:
                results.append(sig)
    return results
