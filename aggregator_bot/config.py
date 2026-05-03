import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
CHAT_ID: int   = int(os.environ["CHAT_ID"])

BINANCE_REST = "https://fapi.binance.com"
BINANCE_WS   = "wss://fstream.binance.com"
BYBIT_REST   = "https://api.bybit.com"
BYBIT_WS     = "wss://stream.bybit.com/v5/public/linear"

# Как часто проверяем сигналы (секунды)
POLL_INTERVAL    = 30
OI_POLL_INTERVAL = 10

# Пороги уверенности для сигнала
LONG_MIN_SCORE  = 5   # из макс ~8
SHORT_MIN_SCORE = 6   # из макс ~12

# Минимальный OI в долларах — фильтруем мусорные монеты
MIN_OI_USD = 500_000  # $500K

# Cooldown между повторными сигналами на одну монету
SIGNAL_COOLDOWN = 1800  # 30 минут

BYBIT_BATCH  = 100
WS_RECONNECT = 5
