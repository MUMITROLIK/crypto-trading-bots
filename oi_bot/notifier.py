"""
Отправка сигналов в Telegram через Bot API (без сторонних библиотек).
"""

import logging
from datetime import datetime, timezone

import aiohttp

from config import BOT_TOKEN, CHAT_ID

logger = logging.getLogger(__name__)

_TG_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def _fmt_qty(val: float) -> str:
    """Форматирует количество монет: 6277000 → 6.28M"""
    val = abs(val)
    if val >= 1_000_000:
        return f"{val / 1_000_000:.2f}M"
    if val >= 1_000:
        return f"{val / 1_000:.1f}K"
    return f"{val:.0f}"


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
    exchange_label = "Binance" if sig["exchange"] == "binance" else "ByBit"
    time_utc = datetime.now(timezone.utc).strftime("%H:%M UTC")
    url  = _coinglass_url(sig["exchange"], sig["symbol"])
    name = _short_symbol(sig["symbol"])
    price_sign = "+" if sig["price_change_pct"] >= 0 else ""

    # Строка с изменением за 1ч — помогает понять не опоздал ли сигнал
    h1 = sig.get("price_change_1h")
    if h1 is not None:
        h1_sign = "+" if h1 >= 0 else ""
        h1_line = f"За 1ч: {h1_sign}{h1}%"
        # Предупреждение если цена уже улетела
        if h1 >= 10:
            h1_line += " ⚠️ поздно"
        h1_line = f"📈 {h1_line}\n"
    else:
        h1_line = ""

    # Строка с CVD (15м и 5м)
    cvd    = sig.get("cvd_15m")
    cvd_5m = sig.get("cvd_5m")
    if cvd is not None:
        cvd_sign  = "+" if cvd >= 0 else ""
        cvd_emoji = "🟢" if cvd >= 0 else "🔴"
        cvd_5m_str = ""
        if cvd_5m is not None:
            s5 = "+" if cvd_5m >= 0 else ""
            cvd_5m_str = f" / 5м: {s5}{_fmt_qty(cvd_5m)}"
        cvd_line = f"{cvd_emoji} CVD(15м): {cvd_sign}{_fmt_qty(cvd)}{cvd_5m_str}\n"
    else:
        cvd_line = ""

    # Строка с funding rate
    fr = sig.get("funding_rate")
    if fr is not None:
        fr_pct = fr * 100  # переводим 0.0001 → 0.01%
        fr_sign = "+" if fr_pct >= 0 else ""
        fr_emoji = "🟢" if fr_pct >= 0 else "🔴"
        fr_line = f"{fr_emoji} Funding: {fr_sign}{fr_pct:.4f}%\n"
    else:
        fr_line = ""

    return (
        f'{exchange_label} – {sig["period_min"]}м – <a href="{url}">{name}</a>\n'
        f"🟢 ОИ вырос на {sig['oi_change_pct']}% ({_fmt_usd(sig['oi_usd'])})\n"
        f"Изменение цены: {price_sign}{sig['price_change_pct']}%\n"
        f"{h1_line}"
        f"{cvd_line}"
        f"{fr_line}"
        f"📊 Сигнал за сутки: {sig['signal_num']}\n"
        f"⏰ {time_utc}"
    )


def format_spike(sig: dict) -> str:
    exchange_label = "Binance" if sig["exchange"] == "binance" else "ByBit"
    time_utc = datetime.now(timezone.utc).strftime("%H:%M UTC")
    url  = _coinglass_url(sig["exchange"], sig["symbol"])
    name = _short_symbol(sig["symbol"])

    h1 = sig.get("price_change_1h")
    if h1 is not None:
        h1_sign = "+" if h1 >= 0 else ""
        h1_line = f"📈 За 1ч: {h1_sign}{h1}%\n"
    else:
        h1_line = ""

    fr = sig.get("funding_rate")
    if fr is not None:
        fr_pct   = fr * 100
        fr_sign  = "+" if fr_pct >= 0 else ""
        fr_emoji = "🟢" if fr_pct >= 0 else "🔴"
        fr_line  = f"{fr_emoji} Funding: {fr_sign}{fr_pct:.4f}%\n"
    else:
        fr_line = ""

    return (
        f'⚡ SPIKE – {exchange_label} – 5м – <a href="{url}">{name}</a>\n'
        f"🟢 ОИ вырос на {sig['oi_change_pct']}% за 5м ({_fmt_usd(sig['oi_usd'])})\n"
        f"Цена: +{sig['price_change_pct']}%\n"
        f"{h1_line}"
        f"{fr_line}"
        f"⚠️ CVD нет — проверь график перед входом\n"
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
    await send("✅ OI Screener запущен\nЖду сигналов...")
