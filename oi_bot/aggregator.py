"""
Aggregator — читает данные уже собранные OI ботом (shared memory),
никаких дополнительных API запросов не делает.
Проверяет каждые 5 секунд, шлёт в отдельный Telegram бот.

Логика — паттерны опытного трейдера:

  ── SHORT (главная стратегия) ──────────────────── макс ~19
  Трейдер шортит после пампа, когда толпа в лонгах переплачивает фандинг.
  Обязательно: памп был (цена 1ч или 20м выросла).

    +3  Большой памп 1ч: +15%+          — монета сильно разогрета
    +2  Памп 1ч: +8-14%                 — памп в фоне
    +3  Памп 20м: +10%+                 — свежий памп, ранний вход
    +1  Рост 20м: +5-9%                 — начало пампа
    +2  Быстрый рост 15м: +5%+          — агрессивный памп сейчас
    +4  OI +3% в боковике после пампа   — КЛЮЧЕВОЙ ПАТТЕРН:
                                          деньги набираются пока цена стоит
                                          = распределение перед сливом
    +2  OI +3% в боковике (без пампа)   — слабее, без контекста
    +3  L/S > 63% лонгов                — толпа в лонгах, ошибка масс
    +2  L/S 57-63% лонгов               — перекос к лонгам
    +2  Funding > 0.05%                 — лонги переплачивают
    +1  Funding > 0.02%                 — лёгкий перегрев
    +2  LONG ликвидации за 5м           — лонги уже льются
    +2  CVD < 0                         — продавцы доминируют

  ── LONG (паттерн отскока от ликвидационной зоны) ─ макс ~14
  Трейдер редко лонгует — только от зон крупных ликвидаций шортов.

    +3  OI +5%+ за 15м с ростом цены    — новые деньги + движение
    +2  SHORT ликвидации за 5м          — шортов выносит → отскок вверх
    +1  Цена подтверждает отскок        — price_15m > 0 при наличии short liq
    +2  CVD > 0                         — покупатели доминируют
    +1  Цена 15м: +0.3-4%              — движение есть, не перегрето
    +1  Тренд 1ч: 0-6%                  — восходящий контекст
    +3  L/S < 38% лонгов                — шорты перегружены → squeeze
    +2  L/S 38-43% лонгов               — дисбаланс шортов
    +1  Funding умеренный 0-0.08%       — бычий, но не перегретый рынок

  Порог: LONG >= AGG_LONG_MIN_SCORE, SHORT >= AGG_SHORT_MIN_SCORE
"""

import logging
import time

import aiohttp

import binance as bnc
import bybit as bbt
import trade_tracker
import orderbook as ob
from config import (
    AGG_BOT_TOKEN, AGG_CHAT_ID,
    AGG_LONG_MIN_SCORE, AGG_SHORT_MIN_SCORE,
    AGG_MIN_OI_USD, AGG_COOLDOWN, AGG_LS_TTL,
)
from data_store import (
    oi_history, price_history, funding_rates,
    ls_ratio, ls_ratio_is_stale, update_ls_ratio,
    get_recent_liqs, get_cvd_change,
    get_footprint_bias,
    value_n_seconds_ago,
)

logger = logging.getLogger(__name__)

# Отдельный cooldown для агрегатора (не мешаем cooldown OI бота)
_agg_last_signal: dict[str, float] = {}


def _can_signal(key: str) -> bool:
    return (time.time() - _agg_last_signal.get(key, 0.0)) >= AGG_COOLDOWN


def _mark_signal(key: str) -> None:
    _agg_last_signal[key] = time.time()


_agg_daily: dict[str, int] = {}
_agg_date = None


def _daily_count(key: str) -> int:
    global _agg_date
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    if _agg_date != today:
        _agg_daily.clear()
        _agg_date = today
    _agg_daily[key] = _agg_daily.get(key, 0) + 1
    return _agg_daily[key]


def _fmt_usd(val: float) -> str:
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.2f}B"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.2f}M"
    if val >= 1_000:
        return f"${val / 1_000:.1f}K"
    return f"${val:.0f}"


def _coinglass_url(exchange: str, symbol: str) -> str:
    label = "Binance" if exchange == "binance" else "Bybit"
    return f"https://www.coinglass.com/tv/{label}_{symbol}"


def _short_symbol(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def _liq_threshold(oi_usd: float) -> float:
    """
    Динамический порог суммы ликвидаций для скоринга.
    Для мемкоинов (малый OI) достаточно и $10K — это уже значимо.
    """
    if oi_usd < 2_000_000:       # мемкоин / микро  (OI < $2M)
        return 10_000
    elif oi_usd < 20_000_000:    # мелкая монета    (OI $2M–$20M)
        return 20_000
    elif oi_usd < 200_000_000:   # средняя монета   (OI $20M–$200M)
        return 50_000
    else:                        # крупная (BTC/ETH) (OI > $200M)
        return 100_000


def _liq_sums(exchange: str, symbol: str, window_sec: float = 300) -> tuple[float, float]:
    """
    (long_liq_usd, short_liq_usd) за последние window_sec секунд.
    long_liq  = ликвидации LONG позиций  → медвежий сигнал
    short_liq = ликвидации SHORT позиций → бычий сигнал
    """
    liqs = get_recent_liqs(exchange, symbol, window_sec)
    long_usd  = sum(usd for _, side, usd in liqs if side == "LONG")
    short_usd = sum(usd for _, side, usd in liqs if side == "SHORT")
    return long_usd, short_usd


async def _score(exchange: str, symbol: str) -> dict | None:
    oi_hist    = oi_history[exchange].get(symbol)
    price_hist = price_history[exchange].get(symbol)

    if not oi_hist or len(oi_hist) < 2:
        return None
    if not price_hist or len(price_hist) < 2:
        return None

    current_oi    = oi_hist[-1][1]
    current_price = price_hist[-1][1]

    oi_usd = current_oi * current_price
    if oi_usd < AGG_MIN_OI_USD:
        return None

    # OI change 15m
    old_oi = value_n_seconds_ago(oi_hist, 900)
    oi_change_15m = (current_oi - old_oi) / old_oi * 100 \
        if old_oi and old_oi > 0 else None

    # Price changes
    def pct(old):
        return (current_price - old) / old * 100 if old and old > 0 else None

    price_15m = pct(value_n_seconds_ago(price_hist, 900))
    price_20m = pct(value_n_seconds_ago(price_hist, 1200))
    price_1h  = pct(value_n_seconds_ago(price_hist, 3600))

    fr = funding_rates[exchange].get(symbol)

    # ===== СКОРИНГ =====
    sl, ss = 0, 0
    rl, rs = [], []

    # ── OI изменение ──
    # Приоритет: если памп уже был (1ч) + OI растёт в боковике → SHORT.
    # Только если пампа нет и цена реально движется → LONG.
    if oi_change_15m is not None:
        _sideways_after_pump = (
            price_15m is not None and abs(price_15m) <= 1.5 and
            price_1h  is not None and price_1h >= 8
        )

        if _sideways_after_pump and oi_change_15m >= 3:
            # Ключевой SHORT паттерн: памп в прошлом + OI набирается в боковике
            # Деньги заходят пока цена стоит = распределение перед сливом
            ss += 4; rs.append(f"OI +{oi_change_15m:.1f}% в боковике после пампа 1ч")

        elif oi_change_15m >= 5 and price_15m is not None and price_15m >= 0.5:
            # Классический LONG: OI большой рост + цена реально растёт (не боковик)
            sl += 3; rl.append(f"OI +{oi_change_15m:.1f}% за 15м + рост цены")

        elif oi_change_15m >= 3 and price_15m is not None and abs(price_15m) <= 1.5:
            # OI в боковике без предыдущего пампа — слабый SHORT сигнал
            ss += 2; rs.append(f"OI +{oi_change_15m:.1f}% в боковике")

    # ── Цена 15м ──
    if price_15m is not None:
        if 0.3 <= price_15m <= 4.0:
            sl += 1; rl.append(f"Цена 15м +{price_15m:.1f}%")
        elif price_15m >= 5.0:
            ss += 2; rs.append(f"Быстрый памп 15м +{price_15m:.1f}%")

    # ── Цена 20м (свежий памп → ранний SHORT) ──
    if price_20m is not None:
        if price_20m >= 10.0:
            ss += 3; rs.append(f"Памп 20м +{price_20m:.1f}%")
        elif price_20m >= 5.0:
            ss += 1; rs.append(f"Рост 20м +{price_20m:.1f}%")

    # ── Цена 1ч ──
    if price_1h is not None:
        if 0.0 <= price_1h <= 6.0:
            sl += 1; rl.append(f"Тренд 1ч +{price_1h:.1f}%")
        elif price_1h >= 15.0:
            ss += 3; rs.append(f"Большой памп 1ч +{price_1h:.1f}%")
        elif price_1h >= 8.0:
            ss += 2; rs.append(f"Памп 1ч +{price_1h:.1f}%")

    # ── Funding ──
    if fr is not None:
        fr_pct = fr * 100
        # Умеренный положительный funding = бычий контекст для лонга
        if 0.0 <= fr_pct <= 0.08:
            sl += 1; rl.append(f"Funding +{fr_pct:.4f}%")
        # Высокий funding = лонги переплачивают = короткий SHORT
        if fr_pct > 0.05:
            ss += 2; rs.append(f"Funding +{fr_pct:.4f}% (лонги переплачивают)")
        elif fr_pct > 0.02:
            ss += 1; rs.append(f"Funding +{fr_pct:.4f}%")

    # ── CVD (15 мин) ──
    cvd = get_cvd_change(exchange, symbol, window_sec=900)
    if cvd is not None:
        if cvd > 0:
            sl += 2; rl.append(f"CVD +{cvd:.0f} (покупатели)")
        elif cvd < 0:
            ss += 2; rs.append(f"CVD {cvd:.0f} (продавцы)")

    # ── Ликвидации за 5 мин (динамический порог) ──
    liq_thr = _liq_threshold(oi_usd)
    long_liq, short_liq = _liq_sums(exchange, symbol, window_sec=300)

    # SHORT лики выносят → отскок вверх → LONG сигнал
    if short_liq >= liq_thr:
        sl += 2; rl.append(f"SHORT лики {_fmt_usd(short_liq)} за 5м")
        # Если цена уже идёт вверх при этом — отскок подтверждён
        if price_15m is not None and price_15m > 0:
            sl += 1; rl.append("Цена подтверждает отскок")
        # Если CVD тоже положительный — покупатели подхватили после ликвидаций
        # (не добавляем отдельный балл — CVD сам по себе выше даёт +2)

    # LONG лики льются → SHORT продолжается
    if long_liq >= liq_thr:
        ss += 2; rs.append(f"LONG лики {_fmt_usd(long_liq)} за 5м")

    # ── Паттерн отскока для LONG: цена упала → начала разворачиваться ──
    # Трейдер открывал лонги когда монета падала к зоне ликвидаций и отскакивала.
    # Признаки: цена за 1ч отрицательная (падение) + CVD разворачивается
    # + короткие лики значительные (выбивают шортистов снизу)
    if (price_1h is not None and -15 <= price_1h <= -3 and
            short_liq >= liq_thr and cvd is not None and cvd > 0):
        sl += 2; rl.append(f"Отскок от падения: 1ч {price_1h:.1f}% + SHORT лики + CVD↑")

    # Быстрый выход если совсем мало очков
    if max(sl, ss) < 3:
        return None

    # ── L/S ratio — запрашиваем только если устарел (раз в AGG_LS_TTL) ──
    if ls_ratio_is_stale(exchange, symbol, AGG_LS_TTL):
        fetcher = bnc.fetch_ls_ratio if exchange == "binance" else bbt.fetch_ls_ratio
        val = await fetcher(symbol)
        if val is not None:
            update_ls_ratio(exchange, symbol, val)

    ls_val = ls_ratio[exchange].get(symbol)
    ls_str = None
    if ls_val is not None:
        lp = ls_val * 100
        ls_str = f"{lp:.0f}%"
        # SHORT: толпа в лонгах = скоро их ликвидируют
        if lp > 63:
            ss += 3; rs.append(f"L/S: {lp:.0f}% лонгов (толпа в лонгах)")
        elif lp > 57:
            ss += 2; rs.append(f"L/S: {lp:.0f}% лонгов (перекос к лонгам)")
        # LONG: шорты перегружены = скоро squeeze вверх
        elif lp < 38:
            sl += 3; rl.append(f"L/S: {lp:.0f}% лонгов (шорты перегружены)")
        elif lp < 43:
            sl += 2; rl.append(f"L/S: {lp:.0f}% лонгов (дисбаланс шортов)")

    # ── Footprint (дельта по ценовым уровням) ──
    # Если на текущих уровнях цены доминируют продавцы — подтверждает SHORT.
    # Если покупатели — подтверждает LONG.
    fp_bias = get_footprint_bias(exchange, symbol, current_price, window_sec=300)
    if fp_bias is not None:
        if fp_bias < -1000:    # продавцы доминируют на уровне (> $1K дельта)
            ss += 1; rs.append(f"Footprint: продавцы {_fmt_usd(-fp_bias)} на уровне")
        elif fp_bias > 1000:   # покупатели доминируют
            sl += 1; rl.append(f"Footprint: покупатели {_fmt_usd(fp_bias)} на уровне")

    # ── Order Book — стенки (используем только для отображения, +1 если подтверждает) ──
    walls = await ob.get_walls(exchange, symbol, current_price)
    ask_wall = walls["ask_walls"][0] if walls["ask_walls"] else None
    bid_wall = walls["bid_walls"][0] if walls["bid_walls"] else None
    # Стенка продаж близко выше = сопротивление → подтверждает SHORT
    if ask_wall and 0 < ask_wall["pct"] <= 4:
        ss += 1; rs.append(f"Стенка продаж +{ask_wall['pct']:.1f}% ({ob.fmt_usd(ask_wall['usd'])})")
    # Стенка покупок близко ниже = поддержка → подтверждает LONG
    if bid_wall and -4 <= bid_wall["pct"] < 0:
        sl += 1; rl.append(f"Стенка покупок {bid_wall['pct']:.1f}% ({ob.fmt_usd(bid_wall['usd'])})")

    # ── SHORT: обязательное условие — был памп ──
    # Трейдер НИКОГДА не шортит без пампа. Если пампа не было — игнорируем SHORT.
    if ss >= AGG_SHORT_MIN_SCORE:
        pump_detected = (
            (price_20m is not None and price_20m >= 7.0) or
            (price_1h  is not None and price_1h  >= 7.0)
        )
        if not pump_detected:
            logger.debug(f"SHORT {symbol}: скор {ss} — памп не обнаружен, пропускаем")
            ss = 0

    # ── Решение ──
    direction = None
    score, reasons = 0, []

    if sl >= AGG_LONG_MIN_SCORE and sl >= ss:
        direction, score, reasons = "long", sl, rl
    elif ss >= AGG_SHORT_MIN_SCORE:
        direction, score, reasons = "short", ss, rs

    if direction is None:
        return None

    # Кулдаун по символу+направлению БЕЗ биржи —
    # чтобы одна монета не давала 2 сигнала (Binance + Bybit одновременно)
    cooldown_key = f"agg:{symbol}:{direction}"
    if not _can_signal(cooldown_key):
        return None

    # Блокируем повторный вход если недавно был SL по этой монете (2 часа)
    if trade_tracker.in_sl_penalty(symbol, direction):
        return None

    _mark_signal(cooldown_key)
    num = _daily_count(f"agg:{symbol}")

    logger.info(
        f"{'🟢 LONG' if direction == 'long' else '🔴 SHORT'} #{num} "
        f"| {exchange.upper()} {symbol} score={score} | {', '.join(reasons)}"
    )

    # Volume Profile — зоны где цена тусовалась дольше всего
    vol_zones = ob.get_volume_zones(price_hist, n=3)

    return {
        "direction":    direction,
        "exchange":     exchange,
        "symbol":       symbol,
        "signal_num":   num,
        "score":        score,
        "reasons":      reasons,
        "oi_usd":       oi_usd,
        "funding":      fr,
        "ls_ratio":     ls_str,
        "ls_val_pct":   round(ls_val * 100, 1) if ls_val is not None else None,  # числовой %
        "entry":        current_price,
        "oi_change":    round(oi_change_15m, 1) if oi_change_15m is not None else None,
        "price_15m":    round(price_15m, 2)     if price_15m is not None     else None,
        "price_20m":    round(price_20m, 2)     if price_20m is not None     else None,
        "price_1h":     round(price_1h, 1)      if price_1h is not None      else None,
        "long_liq_usd": long_liq  if long_liq  >= liq_thr else None,
        "short_liq_usd":short_liq if short_liq >= liq_thr else None,
        "cvd":          round(cvd, 0) if cvd is not None else None,
        "ask_wall":     ask_wall,   # {"price", "usd", "pct"} или None
        "bid_wall":     bid_wall,
        "vol_zones":    vol_zones,  # [price1, price2, price3]
        "fp_bias":      round(fp_bias, 0) if fp_bias is not None else None,
    }


def _format(sig: dict) -> str:
    from datetime import datetime, timezone
    is_long   = sig["direction"] == "long"
    dir_label = "🟢 LONG" if is_long else "🔴 SHORT"
    exch      = "Binance" if sig["exchange"] == "binance" else "ByBit"
    url       = _coinglass_url(sig["exchange"], sig["symbol"])
    name      = _short_symbol(sig["symbol"])
    t         = datetime.now(timezone.utc).strftime("%H:%M UTC")

    max_score = 14 if is_long else 19
    conf      = min(10, round(sig["score"] / max_score * 10))
    bar       = "█" * conf + "░" * (10 - conf)

    reasons = "\n".join(f"  ✅ {r}" for r in sig["reasons"])

    ls_line  = f"👥 Лонгов: {sig['ls_ratio']}\n" if sig.get("ls_ratio") else ""

    fr = sig.get("funding")
    fr_line = ""
    if fr is not None:
        fp = fr * 100
        fr_line = f"{'🟢' if fp >= 0 else '🔴'} Funding: {fp:+.4f}%\n"

    liq_line = ""
    if sig.get("short_liq_usd"):
        liq_line += f"💥 SHORT лики: {_fmt_usd(sig['short_liq_usd'])} за 5м\n"
    if sig.get("long_liq_usd"):
        liq_line += f"💥 LONG лики: {_fmt_usd(sig['long_liq_usd'])} за 5м\n"

    cvd_line = ""
    if sig.get("cvd") is not None:
        arrow    = "↑" if sig["cvd"] > 0 else "↓"
        cvd_line = f"📈 CVD: {sig['cvd']:+.0f} {arrow}\n"

    # Footprint bias
    fp_line = ""
    if sig.get("fp_bias") is not None:
        fp = sig["fp_bias"]
        if abs(fp) >= 1000:
            fp_emoji = "🟢" if fp > 0 else "🔴"
            fp_label = "покупатели" if fp > 0 else "продавцы"
            fp_line = f"{fp_emoji} Footprint: {fp_label} {_fmt_usd(abs(fp))}\n"

    # Order Book стенки
    walls_line = ""
    ask_wall = sig.get("ask_wall")
    bid_wall = sig.get("bid_wall")
    if ask_wall and 0 < ask_wall["pct"] <= 4:
        walls_line += f"🧱 Стенка продаж: {ob.fmt_price(ask_wall['price'])} (+{ask_wall['pct']:.1f}%, {ob.fmt_usd(ask_wall['usd'])})\n"
    if bid_wall and -4 <= bid_wall["pct"] < 0:
        walls_line += f"🛡 Стенка покупок: {ob.fmt_price(bid_wall['price'])} ({bid_wall['pct']:.1f}%, {ob.fmt_usd(bid_wall['usd'])})\n"

    # Volume Profile зоны
    vol_line = ""
    vol_zones = sig.get("vol_zones", [])
    if vol_zones:
        zones_str = " / ".join(ob.fmt_price(z) for z in vol_zones)
        vol_line = f"📊 Volume зоны: {zones_str}\n"

    # TP/SL блок
    tgt = sig.get("targets", {})
    tp_sl_line = ""
    if tgt:
        p = trade_tracker._price_fmt
        tp_sl_line = (
            f"\n📍 Вход: {p(sig['entry'])}\n"
            f"🛑 SL:  {p(tgt['sl'])} (-{tgt['sl_pct']:.1f}%)\n"
            f"🎯 TP1: {p(tgt['tp1'])} (+{tgt['tp1_pct']:.1f}%)\n"
            f"🏆 TP2: {p(tgt['tp2'])} (+{tgt['tp2_pct']:.1f}%) — закрытие\n"
        )

    return (
        f"🎯 АГРЕГАТОР — {dir_label}\n"
        f'{exch} – <a href="{url}">{name}</a>\n'
        f"Уверенность: {conf}/10  {bar}\n"
        f"\n{reasons}\n\n"
        f"{ls_line}{fr_line}{liq_line}{cvd_line}{fp_line}{walls_line}{vol_line}"
        f"💵 OI: {_fmt_usd(sig['oi_usd'])}\n"
        f"📊 Сигнал #{sig['signal_num']} за сутки"
        f"{tp_sl_line}"
        f"⏰ {t}"
    )


async def _send(text: str) -> None:
    if not AGG_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{AGG_BOT_TOKEN}/sendMessage"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                url,
                json={"chat_id": AGG_CHAT_ID, "text": text, "parse_mode": "HTML"},
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    logger.error(f"Aggregator Telegram {r.status}: {body}")
    except Exception as e:
        logger.error(f"Aggregator send error: {e}")


async def send_startup() -> None:
    await _send(
        "🎯 <b>Aggregator Bot запущен</b>\n"
        "SHORT: памп → OI в боковике → L/S перекос → фандинг\n"
        "LONG: OI рост / отскок от ликвидационной зоны\n"
        f"LONG ≥ {AGG_LONG_MIN_SCORE} | SHORT ≥ {AGG_SHORT_MIN_SCORE}\n"
        "Жду сигналов..."
    )


async def check_and_send() -> None:
    """Вызывается каждые AGG_POLL_INTERVAL секунд из main.py"""
    from datetime import datetime, timezone as tz
    for exchange in ("binance", "bybit"):
        for symbol in list(oi_history[exchange].keys()):
            sig = await _score(exchange, symbol)
            if sig:
                # Рассчитываем TP/SL и добавляем в сигнал
                targets = trade_tracker.calculate_targets(
                    exchange, symbol, sig["direction"], sig["entry"]
                )
                sig["targets"] = targets

                # Шлём сигнал с TP/SL
                await _send(_format(sig))

                # ── Фичи для ML ──────────────────────────────────────────
                # Сохраняем ВСЕ индикаторы в момент сигнала.
                # После закрытия сделки (tp2/sl) это станет обучающим примером.
                ask_w = sig.get("ask_wall")
                bid_w = sig.get("bid_wall")
                features = {
                    # ─ ценовые изменения ─
                    "oi_15m":        sig.get("oi_change"),     # OI % за 15м
                    "price_15m":     sig.get("price_15m"),     # цена % за 15м
                    "price_20m":     sig.get("price_20m"),     # цена % за 20м
                    "price_1h":      sig.get("price_1h"),      # цена % за 1ч
                    # ─ рыночные условия ─
                    "funding_pct":   round(sig["funding"] * 100, 4)
                                     if sig.get("funding") is not None else None,
                    "ls_pct":        sig.get("ls_val_pct"),    # % лонгов (числовой)
                    "cvd":           sig.get("cvd"),           # CVD дельта 15м
                    "fp_bias":       sig.get("fp_bias"),       # footprint дельта $
                    # ─ ликвидации ─
                    "long_liq_usd":  sig.get("long_liq_usd"),
                    "short_liq_usd": sig.get("short_liq_usd"),
                    # ─ стакан ─
                    "ask_wall_pct":  round(ask_w["pct"], 2) if ask_w else None,
                    "ask_wall_usd":  round(ask_w["usd"])    if ask_w else None,
                    "bid_wall_pct":  round(bid_w["pct"], 2) if bid_w else None,
                    "bid_wall_usd":  round(bid_w["usd"])    if bid_w else None,
                    # ─ контекст ─
                    "oi_usd":        round(sig.get("oi_usd", 0)),
                    "score":         sig.get("score"),
                    "direction":     sig.get("direction"),
                    "hour_utc":      datetime.now(tz.utc).hour,
                    "exchange":      exchange,
                    # ─ TP/SL параметры ─
                    "tp1_pct":       targets.get("tp1_pct"),
                    "tp2_pct":       targets.get("tp2_pct"),
                    "sl_pct":        targets.get("sl_pct"),
                }

                # Записываем сделку в трекер для мониторинга
                trade_tracker.add_trade(
                    exchange, symbol, sig["direction"],
                    sig["entry"], sig["signal_num"],
                    features=features,
                )
