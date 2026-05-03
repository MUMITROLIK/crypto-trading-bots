"""
Trade Bot — интерактивный Telegram бот для просмотра сделок и статистики.

Команды:
  /open    — открытые сделки с текущим P&L
  /stats   — статистика за 24ч (винрейт, avg P&L, лучшая/худшая)
  /closed  — закрытые сделки за сегодня
  /help    — помощь

Также шлёт push-уведомления (TP/SL) в TRADE_BOT_CHAT_ID.
Запускается как asyncio задача внутри oi_bot.
"""

import logging
import time

import aiohttp

import trade_tracker
from config import TRADE_BOT_TOKEN, TRADE_BOT_CHAT_ID
from data_store import price_history

logger = logging.getLogger(__name__)

_API = f"https://api.telegram.org/bot{TRADE_BOT_TOKEN}"


# ─────────────────────── Отправка ────────────────────────────────────

async def send_notification(text: str) -> None:
    """Отправляем push-уведомление о TP/SL в основной чат."""
    if not TRADE_BOT_TOKEN or not TRADE_BOT_CHAT_ID:
        return
    await _send(TRADE_BOT_CHAT_ID, text)


async def _send(chat_id: int, text: str, parse_mode: str = "HTML") -> None:
    if not TRADE_BOT_TOKEN:
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{_API}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    logger.warning(f"TradeBot send {r.status}: {body[:100]}")
    except Exception as e:
        logger.debug(f"TradeBot send error: {e}")


# ─────────────────────── Форматирование ответов ──────────────────────

def _fmt_open_trades() -> str:
    trades = [t for t in trade_tracker.open_trades.values() if not t["closed"]]
    if not trades:
        return "⏳ Нет открытых сделок"

    lines = [f"⏳ <b>ОТКРЫТЫЕ СДЕЛКИ</b> ({len(trades)})\n"]
    for t in sorted(trades, key=lambda x: x["created_at"], reverse=True)[:10]:
        is_long = t["direction"] == "long"
        symbol  = t["symbol"][:-4] if t["symbol"].endswith("USDT") else t["symbol"]
        exch    = "Bin" if t["exchange"] == "binance" else "Bybit"
        emoji   = "🟢" if is_long else "🔴"

        # Текущая цена
        hist  = price_history[t["exchange"]].get(t["symbol"])
        cur   = hist[-1][1] if hist else None
        pnl_s = ""
        if cur:
            pnl = (cur - t["entry"]) / t["entry"] * 100
            if not is_long:
                pnl = -pnl
            pnl_s = f"  <b>{pnl:+.2f}%</b>"

        # Статус тейков
        tp_status = ""
        if t.get("hit_tp1"):
            tp_status += "✅"
        if t.get("hit_tp2"):
            tp_status += "✅"

        p = trade_tracker._price_fmt
        lines.append(
            f"{emoji} <b>#{t['id']} {symbol}</b> ({exch}){pnl_s}\n"
            f"   Вход: {p(t['entry'])} {tp_status}\n"
            f"   🛑 {p(t['sl'])}  🎯 {p(t['tp1'])} / 🏆 {p(t['tp2'])}"
        )

    return "\n\n".join(lines)


def _fmt_stats() -> str:
    s   = trade_tracker.get_stats(24)
    exp = trade_tracker.get_stats(168)  # за неделю

    lines = ["📊 <b>СТАТИСТИКА СДЕЛОК</b>", ""]

    lines.append(f"<b>За 24 часа:</b>  {s['total']} сделок")
    if s["total"] > 0:
        lines.append(f"✅ TP: {s['tp_count']}  🛑 SL: {s['sl_count']}  ⏳ Открытых: {s['open_count']}")
        lines.append(f"🏆 Винрейт: {s['win_rate']}%  |  Avg P&L: {s['avg_pnl']:+.2f}%")
        if s["best"]:
            sym = s["best"]["symbol"][:-4] if s["best"]["symbol"].endswith("USDT") else s["best"]["symbol"]
            lines.append(f"🚀 Лучшая: {sym} {s['best']['pnl_pct']:+.1f}%")
        if s["worst"]:
            sym = s["worst"]["symbol"][:-4] if s["worst"]["symbol"].endswith("USDT") else s["worst"]["symbol"]
            lines.append(f"💩 Худшая: {sym} {s['worst']['pnl_pct']:+.1f}%")
    else:
        lines.append("Нет закрытых сделок за 24ч")

    lines.append("")
    lines.append(f"<b>За 7 дней:</b>  {exp['total']} сделок")
    if exp["total"] > 0:
        lines.append(f"✅ TP: {exp['tp_count']}  🛑 SL: {exp['sl_count']}")
        lines.append(f"🏆 Винрейт: {exp['win_rate']}%  |  Avg P&L: {exp['avg_pnl']:+.2f}%")

    lines.append(f"\n⏳ Сейчас открыто: {s['open_count']}")
    return "\n".join(lines)


def _fmt_closed() -> str:
    cutoff = time.time() - 86_400
    recent = [t for t in trade_tracker.closed_trades if t["closed_at"] >= cutoff]
    recent.sort(key=lambda x: x["closed_at"], reverse=True)

    if not recent:
        return "📭 Нет закрытых сделок за последние 24ч"

    lines = [f"📋 <b>ЗАКРЫТЫЕ СДЕЛКИ</b> ({len(recent)})\n"]
    for t in recent[:15]:
        is_long = t["direction"] == "long"
        symbol  = t["symbol"][:-4] if t["symbol"].endswith("USDT") else t["symbol"]
        pnl     = t["pnl_pct"]
        result  = t["result"].upper()
        emoji   = "✅" if t["result"].startswith("tp") else ("🛑" if t["result"] == "sl" else "⌛")
        dir_e   = "🟢" if is_long else "🔴"
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(t["closed_at"], tz=timezone.utc).strftime("%H:%M")
        lines.append(
            f"{emoji} {dir_e} {symbol}  <b>{pnl:+.2f}%</b>  [{result}]  {dt}"
        )

    return "\n".join(lines)


def _fmt_help() -> str:
    return (
        "🤖 <b>Trade Bot — команды</b>\n\n"
        "/open — открытые сделки с текущим P&L\n"
        "/stats — статистика (24ч и 7 дней)\n"
        "/closed — закрытые сделки за 24ч\n"
        "/help — это сообщение\n\n"
        "Бот автоматически уведомит когда сработает TP или SL."
    )


# ─────────────────────── Polling ────────────────────────────────────

async def _get_updates(offset: int) -> tuple[list, int]:
    """Telegram getUpdates long-polling (таймаут 25с)."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{_API}/getUpdates",
                params={"offset": offset, "timeout": 25, "allowed_updates": ["message"]},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                data = await r.json()
        if data.get("ok") and data["result"]:
            updates = data["result"]
            return updates, updates[-1]["update_id"] + 1
        return [], offset
    except Exception as e:
        logger.debug(f"TradeBot getUpdates: {e}")
        return [], offset


async def _handle(chat_id: int, text: str) -> None:
    text = text.strip().lower().split()[0] if text.strip() else ""
    if text in ("/open", "/сделки", "/trades"):
        await _send(chat_id, _fmt_open_trades())
    elif text in ("/stats", "/стата", "/статистика"):
        await _send(chat_id, _fmt_stats())
    elif text in ("/closed", "/закрытые", "/history"):
        await _send(chat_id, _fmt_closed())
    elif text in ("/help", "/start", "/помощь"):
        await _send(chat_id, _fmt_help())
    else:
        await _send(chat_id, "Используй /open, /stats, /closed или /help")


async def run() -> None:
    """Основной цикл бота — long-polling Telegram."""
    if not TRADE_BOT_TOKEN:
        logger.warning("TradeBot: TRADE_BOT_TOKEN не задан, бот не запущен")
        return

    logger.info("TradeBot: запущен")
    offset = 0

    # Стартовое сообщение
    if TRADE_BOT_CHAT_ID:
        await _send(
            TRADE_BOT_CHAT_ID,
            "📈 <b>Trade Bot запущен</b>\n"
            "/open — открытые сделки\n"
            "/stats — статистика\n"
            "/closed — история\n"
            "Буду уведомлять о TP и SL 🔔"
        )

    while True:
        updates, offset = await _get_updates(offset)
        for upd in updates:
            msg = upd.get("message", {})
            chat_id = msg.get("chat", {}).get("id")
            text    = msg.get("text", "")
            if chat_id and text:
                await _handle(chat_id, text)
