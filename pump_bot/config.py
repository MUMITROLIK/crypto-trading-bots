import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
CHAT_ID: int = int(os.environ["CHAT_ID"])

BINANCE_REST = "https://fapi.binance.com"
BINANCE_WS   = "wss://fstream.binance.com"
BYBIT_REST   = "https://api.bybit.com"
BYBIT_WS     = "wss://stream.bybit.com/v5/public/linear"

PRICE_POLL_INTERVAL = 10    # секунды между REST циклами опроса цены

# LONG сигнал: короткий памп
LONG_PERIOD_MIN    = 2
LONG_THRESHOLD_PCT = 2.0

# SHORT сигнал: сильный памп → перегрев
SHORT_PERIOD_MIN    = 20
SHORT_THRESHOLD_PCT = 10.0

# DUMP сигнал: резкое падение
DUMP_PERIOD_MIN    = 30
DUMP_THRESHOLD_PCT = 7.0   # минимальный % падения (без минуса)

SIGNAL_COOLDOWN = 300   # 5 минут cooldown на символ/направление
BYBIT_BATCH     = 100
WS_RECONNECT    = 5
