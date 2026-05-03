import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
CHAT_ID: int = int(os.environ["CHAT_ID"])

BINANCE_WS = "wss://fstream.binance.com"
BYBIT_REST = "https://api.bybit.com"
BYBIT_WS   = "wss://stream.bybit.com/v5/public/linear"

LIQ_MIN_USD  = 20_000   # минимальный объём ликвидации в USD
LIQ_COOLDOWN = 30       # секунды между сигналами на один символ

BYBIT_BATCH  = 100
WS_RECONNECT = 5
