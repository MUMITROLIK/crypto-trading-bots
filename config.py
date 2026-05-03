import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]

_raw_ids = os.getenv("CHAT_IDS", "")
CHAT_IDS: list[int] = [int(x.strip()) for x in _raw_ids.split(",") if x.strip()]

# Binance Futures
BINANCE_WS_BASE = "wss://fstream.binance.com"
BINANCE_REST_BASE = "https://fapi.binance.com"

# Bybit Futures
BYBIT_WS_LINEAR = "wss://stream.bybit.com/v5/public/linear"
BYBIT_REST_BASE = "https://api.bybit.com"

# OI polling interval (seconds)
OI_POLL_INTERVAL = 30

# Bybit: сколько символов на одно WS соединение
BYBIT_SYMBOLS_PER_CONNECTION = 100

# WebSocket reconnect delay (seconds)
WS_RECONNECT_DELAY = 5

# Default screener settings
DEFAULTS = {
    "oi_period_min": 15,
    "oi_threshold_pct": 5.0,
    "oi_enabled": True,
    "pump_period_min": 2,
    "pump_threshold_pct": 2.0,
    "pump_enabled": True,
    "short_period_min": 20,
    "short_threshold_pct": 10.0,
    "short_enabled": True,
    "liq_min_usd": 20000.0,
    "liq_enabled": True,
}

# Cooldown между сигналами одного типа на один символ (секунды)
SIGNAL_COOLDOWN = 300   # 5 минут

# Cooldown для ликвидаций
LIQ_COOLDOWN = 30       # 30 секунд
