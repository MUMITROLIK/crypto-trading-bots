import logging
from datetime import datetime, timezone

import aiohttp

from config import BOT_TOKEN, CHAT_ID

logger = logging.getLogger(__name__)

_TG_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def _fmt_usd(val: float) -> str:
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


def format_signal(symbol: str, side: str, usd: float, exchange: str, ratio: float | None, signal_num: int = 1) -> str:
    exchange_label = "Binance" if exchange == "binance" else "ByBit"
    time_utc = datetime.now(timezone.utc).strftime("%H:%M UTC")
    url  = _coinglass_url(exchange, symbol)
    name = _short_symbol(symbol)
    emoji = "🔴" if side == "LONG" else "🟢"

    ratio_str = f"\n🛡️ объёма в {ratio} раз" if ratio is not None else ""

    return (
        f'{exchange_label} – <a href="{url}">{name}</a>\n'
        f"Ликвидация {emoji} {_fmt_usd(usd)}{ratio_str}\n"
        f"📊 Сигнал за сутки: {signal_num}\n"
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
    await send("✅ Liquidation Screener запущен\nЖду ликвидаций >= $20,000...")
