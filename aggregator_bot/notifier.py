"""
Отправка агрегированных LONG/SHORT сигналов в Telegram.
"""

import logging
from datetime import datetime, timezone

import aiohttp

from config import BOT_TOKEN, CHAT_ID

logger = logging.getLogger(__name__)

_TG_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


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


def format_signal(sig: dict) -> str:
    direction      = sig["direction"]
    is_long        = direction == "long"
    dir_emoji      = "🟢 LONG" if is_long else "🔴 SHORT"
    exchange_label = "Binance" if sig["exchange"] == "binance" else "ByBit"
    time_utc       = datetime.now(timezone.utc).strftime("%H:%M UTC")
    url            = _coinglass_url(sig["exchange"], sig["symbol"])
    name           = _short_symbol(sig["symbol"])

    # Уверенность: score / max_score → шкала 1-10
    max_score = 8 if is_long else 12
    conf = min(10, round(sig["score"] / max_score * 10))
    conf_bar = "█" * conf + "░" * (10 - conf)

    # Причины
    reasons_text = "\n".join(f"  ✅ {r}" for r in sig["reasons"])

    # L/S ratio
    ls_line = f"👥 Лонгов на рынке: {sig['ls_ratio']}\n" if sig.get("ls_ratio") else ""

    # Funding
    fr = sig.get("funding")
    fr_line = ""
    if fr is not None:
        fr_pct   = fr * 100
        fr_sign  = "+" if fr_pct >= 0 else ""
        fr_emoji = "🟢" if fr_pct >= 0 else "🔴"
        fr_line  = f"{fr_emoji} Funding: {fr_sign}{fr_pct:.4f}%\n"

    return (
        f"🎯 АГРЕГАТОР — {dir_emoji}\n"
        f'{exchange_label} – <a href="{url}">{name}</a>\n'
        f"Уверенность: {conf}/10  {conf_bar}\n"
        f"\n{reasons_text}\n\n"
        f"{ls_line}"
        f"{fr_line}"
        f"💵 OI: {_fmt_usd(sig['oi_usd'])}\n"
        f"📊 Сигнал #{sig['signal_num']} за сутки\n"
        f"⏰ {time_utc}"
    )


async def send(text: str) -> None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                _TG_URL,
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            ) as r:
                if r.status != 200:
                    body = await r.text()
                    logger.error(f"Telegram {r.status}: {body}")
    except Exception as e:
        logger.error(f"Telegram send error: {e}")


async def send_startup() -> None:
    await send(
        "🎯 <b>Aggregator Bot запущен</b>\n"
        "Комбинирую: OI + Цена + Funding + L/S Ratio\n"
        "Порог: LONG ≥ 5/8 | SHORT ≥ 6/12\n"
        "Жду сигналов..."
    )
