import logging
from datetime import datetime, timezone


import aiohttp

from config import BOT_TOKEN, CHAT_ID

logger = logging.getLogger(__name__)

_TG_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def _fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:.4f}".rstrip("0").rstrip(".")
    return f"{p:.6f}".rstrip("0").rstrip(".")


def _coinglass_url(exchange: str, symbol: str) -> str:
    label = "Binance" if exchange == "binance" else "Bybit"
    return f"https://www.coinglass.com/tv/{label}_{symbol}"


def _short_symbol(symbol: str) -> str:
    """BTCUSDT → BTC"""
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def format_signal(sig: dict) -> str:
    exchange_label = "Binance" if sig["exchange"] == "binance" else "ByBit"
    time_utc = datetime.now(timezone.utc).strftime("%H:%M UTC")
    url  = _coinglass_url(sig["exchange"], sig["symbol"])
    name = _short_symbol(sig["symbol"])
    p_from = _fmt_price(sig["old_price"])
    p_to   = _fmt_price(sig["cur_price"])

    direction = sig["direction"]

    if direction == "long":
        emoji = "🟢"
        label = f"Pump: {sig['change_pct']:+.2f}%"
    elif direction == "short":
        emoji = "🔴"
        label = f"Pump: {sig['change_pct']:+.2f}%"
    else:  # dump
        emoji = "🔴"
        label = f"Dump: {sig['change_pct']:.2f}%"

    return (
        f'{exchange_label} – {sig["period_min"]}м – <a href="{url}">{name}</a>\n'
        f"{emoji} {label} ({p_from}-{p_to})\n"
        f"📊 Сигнал за сутки: {sig['signal_num']}\n"
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
    await send("✅ Pump Screener запущен\nЖду сигналов...")
