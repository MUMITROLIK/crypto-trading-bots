"""
Trade Tracker — отслеживает открытые и закрытые сделки от агрегатора.

Для каждого сигнала:
  - Рассчитывает SL и 3 тейк-профита на основе волатильности последнего часа
  - Записывает в open_trades и сохраняет в JSON (trades.json)
  - check_trades() вызывается каждые 30с и возвращает список уведомлений
  - Ведёт историю closed_trades для статистики

При перезапуске бота: load_trades() подгружает все открытые сделки обратно.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

from data_store import price_history

logger = logging.getLogger(__name__)

_TRADES_FILE = os.path.join(os.path.dirname(__file__), "trades.json")

# Открытые сделки: key = "exchange:symbol:direction:id"
open_trades: dict[str, dict] = {}

# История закрытых сделок (полная, как в trades.json)
closed_trades: list[dict] = []

_trade_counter = 0

# После SL — не входим в ту же монету+направление 2 часа
_SL_PENALTY_SEC = 7_200
_sl_penalty: dict[str, float] = {}   # "symbol:direction" → timestamp SL


def in_sl_penalty(symbol: str, direction: str) -> bool:
    """True если по этой монете недавно был стоп-лосс (не входим повторно)."""
    return (time.time() - _sl_penalty.get(f"{symbol}:{direction}", 0)) < _SL_PENALTY_SEC


# ─────────────────────── Форматирование цены ────────────────────────

def _price_fmt(p: float) -> str:
    """Умное форматирование цены под любой диапазон (BTC → мемкоин)."""
    if p >= 10_000:
        return f"{p:,.1f}"
    elif p >= 100:
        return f"{p:,.2f}"
    elif p >= 1:
        return f"{p:.4f}"
    elif p >= 0.01:
        return f"{p:.5f}"
    elif p >= 0.0001:
        return f"{p:.7f}"
    else:
        s = f"{p:.10f}".rstrip("0")
        return s if "." in s else s + ".0"


# ─────────────────────── Расчёт TP/SL ────────────────────────────────

def calculate_targets(exchange: str, symbol: str, direction: str, entry: float) -> dict:
    """
    Считаем SL и TP1/TP2/TP3 на основе волатильности последнего часа.
    SL  = 80% волатильности  (мин 1.5%, макс 6%)
    TP1 = 70% волатильности  (мин 1.0%, макс 4%)
    TP2 = TP1 × 2  → закрытие сделки
    """
    hist = price_history[exchange].get(symbol)

    if hist and len(hist) >= 20:
        prices = [p for _, p in list(hist)[-360:]]
        high = max(prices)
        low  = min(prices)
        volatility = (high - low) / entry if entry > 0 else 0.03
    else:
        volatility = 0.03

    sl_pct  = max(0.015, min(0.06,  volatility * 0.80))
    tp1_pct = max(0.010, min(0.04,  volatility * 0.70))
    tp2_pct = tp1_pct * 2.0

    if direction == "long":
        return {
            "sl":      round(entry * (1 - sl_pct),      8),
            "tp1":     round(entry * (1 + tp1_pct),     8),
            "tp2":     round(entry * (1 + tp2_pct),     8),
            "sl_pct":  round(sl_pct  * 100, 2),
            "tp1_pct": round(tp1_pct * 100, 2),
            "tp2_pct": round(tp2_pct * 100, 2),
        }
    else:
        sl_s = sl_pct * 1.2
        return {
            "sl":      round(entry * (1 + sl_s),        8),
            "tp1":     round(entry * (1 - tp1_pct),     8),
            "tp2":     round(entry * (1 - tp2_pct),     8),
            "sl_pct":  round(sl_s    * 100, 2),
            "tp1_pct": round(tp1_pct * 100, 2),
            "tp2_pct": round(tp2_pct * 100, 2),
        }


# ─────────────────────── CRUD сделок ────────────────────────────────

def add_trade(
    exchange: str, symbol: str, direction: str,
    entry: float, signal_num: int,
    features: dict | None = None,
) -> dict:
    """Добавляем новую сделку в трекер.
    Если уже есть открытая сделка по этому символу+направлению (на любой бирже) —
    не дублируем, возвращаем существующую.
    """
    # Проверяем дубли по символу+направлению (биржа не важна)
    for existing in open_trades.values():
        if (
            existing["symbol"]    == symbol
            and existing["direction"] == direction
            and not existing["closed"]
        ):
            logger.debug(
                f"Trade дубль пропущен: уже открыт {direction.upper()} {symbol} "
                f"(#{existing['id']}, {existing['exchange']})"
            )
            return existing

    global _trade_counter
    _trade_counter += 1
    tid = _trade_counter

    targets = calculate_targets(exchange, symbol, direction, entry)

    trade = {
        "id":         tid,
        "exchange":   exchange,
        "symbol":     symbol,
        "direction":  direction,
        "entry":      entry,
        "created_at": time.time(),
        "signal_num": signal_num,
        "hit_tp1":    False,
        "hit_tp2":    False,
        "hit_sl":     False,
        "closed":     False,
        **targets,
        # Индикаторы в момент сигнала — для ML обучения после закрытия
        "features":   features if features else {},
    }

    key = f"{exchange}:{symbol}:{direction}:{tid}"
    open_trades[key] = trade
    save_trades()

    logger.info(
        f"[Trade #{tid}] {exchange.upper()} {symbol} {direction.upper()} "
        f"@ {_price_fmt(entry)} | "
        f"SL {_price_fmt(targets['sl'])} ({targets['sl_pct']:.1f}%) | "
        f"TP1 {_price_fmt(targets['tp1'])} ({targets['tp1_pct']:.1f}%) | "
        f"TP2 {_price_fmt(targets['tp2'])} ({targets['tp2_pct']:.1f}%)"
    )
    return trade


# ─────────────────────── История закрытых ────────────────────────────

def _record_closed(trade: dict, event: str, exit_price: float) -> None:
    """Записываем закрытую сделку в историю."""
    pnl = (exit_price - trade["entry"]) / trade["entry"] * 100
    if trade["direction"] == "short":
        pnl = -pnl

    raw_sym = trade["symbol"]

    # Запоминаем SL — 2 часа не входим в эту монету в том же направлении
    if event == "sl":
        _sl_penalty[f"{raw_sym}:{trade['direction']}"] = time.time()
        logger.info(f"SL penalty: {raw_sym} {trade['direction']} — пауза {_SL_PENALTY_SEC//3600}ч")

    closed_trades.append({
        "id":         trade["id"],
        "exchange":   trade["exchange"],
        "symbol":     raw_sym,
        "direction":  trade["direction"],
        "entry":      trade["entry"],
        "exit_price": exit_price,
        "result":     event,        # "tp2" / "sl" / "expired"
        "pnl_pct":    round(pnl, 2),
        "hit_tp1":    trade.get("hit_tp1", False),
        "hit_tp2":    trade.get("hit_tp2", False),
        "opened_at":  trade.get("created_at", 0),
        "closed_at":  time.time(),
        # Копируем фичи из открытой сделки → обучающий пример для ML
        "features":   trade.get("features", {}),
    })


# ─────────────────────── Статистика ──────────────────────────────────

def get_stats(since_hours: float = 24.0) -> dict:
    """
    Статистика по закрытым сделкам за последние since_hours часов.
    Возвращает dict с полями: total, tp_count, sl_count, win_rate,
    avg_pnl, best, worst, open_count.
    """
    cutoff = time.time() - since_hours * 3600
    recent = [t for t in closed_trades if t["closed_at"] >= cutoff]

    total    = len(recent)
    tp_count = sum(1 for t in recent if t["result"].startswith("tp"))
    sl_count = sum(1 for t in recent if t["result"] == "sl")
    win_rate = round(tp_count / total * 100, 1) if total > 0 else 0.0
    pnls     = [t["pnl_pct"] for t in recent]
    avg_pnl  = round(sum(pnls) / len(pnls), 2) if pnls else 0.0
    best     = max(recent, key=lambda t: t["pnl_pct"]) if recent else None
    worst    = min(recent, key=lambda t: t["pnl_pct"]) if recent else None

    return {
        "total":      total,
        "tp_count":   tp_count,
        "sl_count":   sl_count,
        "win_rate":   win_rate,
        "avg_pnl":    avg_pnl,
        "best":       best,
        "worst":      worst,
        "open_count": len(open_trades),
    }


# ─────────────────────── Проверка уровней ────────────────────────────

def check_trades() -> list[dict]:
    """
    Проверяем все открытые сделки против текущей цены.
    Возвращает список уведомлений:
      {"trade": ..., "event": "tp1"|"tp2"|"sl", "price": float}
    """
    notifications: list[dict] = []
    to_remove: list[str] = []

    for key, trade in list(open_trades.items()):
        if trade["closed"]:
            to_remove.append(key)
            continue

        # Автоматически закрываем через 24 часа
        if time.time() - trade["created_at"] > 86_400:
            hist = price_history[trade["exchange"]].get(trade["symbol"])
            exit_p = hist[-1][1] if hist else trade["entry"]
            _record_closed(trade, "expired", exit_p)
            trade["closed"] = True
            to_remove.append(key)
            continue

        hist = price_history[trade["exchange"]].get(trade["symbol"])
        if not hist:
            continue

        price   = hist[-1][1]
        is_long = trade["direction"] == "long"

        # ── SL ──
        if not trade["hit_sl"]:
            sl_hit = (is_long and price <= trade["sl"]) or \
                     (not is_long and price >= trade["sl"])
            if sl_hit:
                trade["hit_sl"] = True
                trade["closed"] = True
                to_remove.append(key)
                _record_closed(trade, "sl", price)
                notifications.append({"trade": dict(trade), "event": "sl", "price": price})
                continue

        # ── TP1 ──
        if not trade["hit_tp1"]:
            tp1_hit = (is_long and price >= trade["tp1"]) or \
                      (not is_long and price <= trade["tp1"])
            if tp1_hit:
                trade["hit_tp1"] = True
                # Переставляем SL на безубыток (цена входа)
                trade["sl"] = trade["entry"]
                notifications.append({"trade": dict(trade), "event": "tp1", "price": price})
                notifications.append({"trade": dict(trade), "event": "breakeven", "price": price})

        # ── TP2 (только после TP1) — закрываем сделку ──
        if trade["hit_tp1"] and not trade["hit_tp2"]:
            tp2_hit = (is_long and price >= trade["tp2"]) or \
                      (not is_long and price <= trade["tp2"])
            if tp2_hit:
                trade["hit_tp2"] = True
                trade["closed"]  = True
                to_remove.append(key)
                _record_closed(trade, "tp2", price)
                notifications.append({"trade": dict(trade), "event": "tp2", "price": price})

    if notifications or to_remove:
        save_trades()

    for key in to_remove:
        open_trades.pop(key, None)

    # Дедуплицируем уведомления: одна монета = одно сообщение за цикл
    seen_notif: set = set()
    deduped: list[dict] = []
    for n in notifications:
        notif_key = f"{n['trade']['symbol']}:{n['event']}"
        if notif_key not in seen_notif:
            seen_notif.add(notif_key)
            deduped.append(n)

    return deduped


# ─────────────────────── Форматирование уведомлений ─────────────────

def _coinglass_url(exchange: str, symbol: str) -> str:
    label = "Binance" if exchange == "binance" else "Bybit"
    return f"https://www.coinglass.com/tv/{label}_{symbol}"


def format_notification(n: dict) -> str:
    trade = n["trade"]
    event = n["event"]
    price = n["price"]

    is_long   = trade["direction"] == "long"
    raw_sym   = trade["symbol"]
    symbol    = raw_sym[:-4] if raw_sym.endswith("USDT") else raw_sym
    exch      = "Binance" if trade["exchange"] == "binance" else "ByBit"
    t         = datetime.now(timezone.utc).strftime("%H:%M UTC")
    dir_emoji = "🟢" if is_long else "🔴"
    url       = _coinglass_url(trade["exchange"], raw_sym)

    pnl_pct = (price - trade["entry"]) / trade["entry"] * 100
    if not is_long:
        pnl_pct = -pnl_pct

    p = _price_fmt

    # Блок цен — показываем всегда: вход / TP1 / TP2 / SL
    tp1_status = "✅" if trade.get("hit_tp1") else "○"
    price_block = (
        f"📍 Вход:  {p(trade['entry'])}\n"
        f"🎯 TP1:  {p(trade['tp1'])} (+{trade['tp1_pct']:.1f}%)  {tp1_status}\n"
        f"🏆 TP2:  {p(trade['tp2'])} (+{trade['tp2_pct']:.1f}%)\n"
        f"🛑 SL:   {p(trade['sl'])} (-{trade['sl_pct']:.1f}%)"
    )

    if event == "sl":
        is_be = abs(trade["entry"] - price) / trade["entry"] < 0.005
        if is_be:
            return (
                f"🔰 БЕЗУБЫТОК | {dir_emoji} {trade['direction'].upper()}\n"
                f'{exch} – <a href="{url}">{symbol}</a>  (сделка #{trade["id"]})\n\n'
                f"{price_block}\n\n"
                f"Закрыт по входу: {p(price)}\n"
                f"💼 P&L: {pnl_pct:+.2f}%  (сохранил депо)\n"
                f"⏰ {t}"
            )
        return (
            f"🛑 СТОП-ЛОСС | {dir_emoji} {trade['direction'].upper()}\n"
            f'{exch} – <a href="{url}">{symbol}</a>  (сделка #{trade["id"]})\n\n'
            f"{price_block}\n\n"
            f"Выбило на: {p(price)}\n"
            f"📉 P&L: {pnl_pct:+.2f}%\n"
            f"⏰ {t}"
        )

    if event == "breakeven":
        return (
            f"🔰 SL → БЕЗУБЫТОК | {dir_emoji} {trade['direction'].upper()}\n"
            f'{exch} – <a href="{url}">{symbol}</a>  (сделка #{trade["id"]})\n\n'
            f"TP1 взят ✅ — стоп перенесён на вход\n"
            f"📍 Новый SL: {p(trade['entry'])}\n"
            f"🏆 Цель: {p(trade['tp2'])} (+{trade['tp2_pct']:.1f}%)\n"
            f"⏰ {t}"
        )

    if event == "tp1":
        return (
            f"🎯 TP1 ВЗЯТ | {dir_emoji} {trade['direction'].upper()}\n"
            f'{exch} – <a href="{url}">{symbol}</a>  (сделка #{trade["id"]})\n\n'
            f"{price_block}\n\n"
            f"💰 P&L сейчас: {pnl_pct:+.2f}%\n"
            f"→ Жду TP2: {p(trade['tp2'])} (+{trade['tp2_pct']:.1f}%)\n"
            f"⏰ {t}"
        )

    if event == "tp2":
        return (
            f"🏆 TP2 — ЗАКРЫТО | {dir_emoji} {trade['direction'].upper()}\n"
            f'{exch} – <a href="{url}">{symbol}</a>  (сделка #{trade["id"]})\n\n'
            f"{price_block}\n\n"
            f"💰 P&L итог: {pnl_pct:+.2f}% ✅\n"
            f"⏰ {t}"
        )

    # Fallback для других событий
    return (
        f"📌 {event.upper()} | {dir_emoji} {trade['direction'].upper()}\n"
        f'{exch} – <a href="{url}">{symbol}</a>  (сделка #{trade["id"]})\n\n'
        f"{price_block}\n\n"
        f"💰 P&L: {pnl_pct:+.2f}%\n"
        f"⏰ {t}"
    )


# ─────────────────────── Персистентность ────────────────────────────

def save_trades() -> None:
    try:
        data = {
            "saved_at":     time.time(),
            "counter":      _trade_counter,
            "open_trades":  list(open_trades.values()),
            "closed_trades": list(closed_trades),
        }
        with open(_TRADES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Не удалось сохранить trades.json: {e}")


def load_trades() -> None:
    global _trade_counter
    if not os.path.exists(_TRADES_FILE):
        return
    try:
        with open(_TRADES_FILE, encoding="utf-8") as f:
            data = json.load(f)

        _trade_counter = data.get("counter", 0)
        cutoff = time.time() - 86_400

        # Поддержка старого формата ("trades") и нового ("open_trades")
        trades_list = data.get("open_trades") or data.get("trades", [])

        # Дедупликация: оставляем только 1 сделку на символ+направление (самую свежую)
        fresh = [
            t for t in trades_list
            if not t.get("closed") and t.get("created_at", 0) >= cutoff
        ]
        fresh.sort(key=lambda x: x.get("created_at", 0), reverse=True)

        seen_sd: set = set()
        loaded_open = 0
        skipped = 0
        for t in fresh:
            sd = f"{t['symbol']}:{t['direction']}"
            if sd in seen_sd:
                skipped += 1
                continue
            seen_sd.add(sd)

            # Если TP1 уже взят — SL должен быть на уровне входа (безубыток)
            if t.get("hit_tp1") and not t.get("closed"):
                t["sl"] = t["entry"]

            # Совместимость со старыми сделками: если hit_tp2 = True — закрываем
            # (в старой логике TP2 не закрывал сделку, теперь закрывает)
            if t.get("hit_tp2") and not t.get("closed"):
                t["closed"] = True
                continue  # не грузим в open_trades

            # Убираем устаревшие поля TP3 если есть
            t.pop("hit_tp3", None)
            t.pop("tp3",     None)
            t.pop("tp3_pct", None)

            key = f"{t['exchange']}:{t['symbol']}:{t['direction']}:{t['id']}"
            open_trades[key] = t
            loaded_open += 1

        if skipped:
            logger.info(f"Дублей сделок удалено при загрузке: {skipped}")

        # Загружаем всю историю закрытых
        for t in data.get("closed_trades", []):
            closed_trades.append(t)

        logger.info(
            f"Трейды загружены: {loaded_open} открытых, "
            f"{len(closed_trades)} закрытых в истории"
        )
    except Exception as e:
        logger.warning(f"Не удалось загрузить trades.json: {e}")
