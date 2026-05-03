import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
CHAT_ID: int = int(os.environ["CHAT_ID"])

# Агрегатор — отдельный бот, шлёт LONG/SHORT сигналы
AGG_BOT_TOKEN: str = os.environ.get("AGG_BOT_TOKEN", "")
AGG_CHAT_ID: int   = int(os.environ.get("AGG_CHAT_ID", os.environ.get("CHAT_ID", "0")))

# Binance Futures
BINANCE_REST = "https://fapi.binance.com"
BINANCE_WS   = "wss://fstream.binance.com"

# Bybit Futures (Linear Perpetuals)
BYBIT_REST = "https://api.bybit.com"
BYBIT_WS   = "wss://stream.bybit.com/v5/public/linear"

# --- OI Screener настройки ---
OI_POLL_INTERVAL  = 10    # секунды между циклами опроса OI
OI_PERIOD_MIN     = 15    # окно расчёта изменения OI (минуты)
OI_THRESHOLD_PCT  = 5.0   # минимальный % роста OI для сигнала

# Фильтр "раннего входа":
# Цена за OI_PERIOD_MIN должна вырасти НЕ БОЛЬШЕ этого значения.
# Если цена уже улетела — сигнал опоздал, пропускаем.
# Логика: OI растёт быстрее цены = деньги заходят ДО пампа = хороший вход.
OI_MIN_PRICE_PCT  = 0.5   # % минимального роста цены за период (ниже = шум, не сигнал)
OI_MAX_PRICE_PCT  = 3.0   # % максимального роста цены за период OI (0 = отключить)

# Фильтр "не опоздал ли":
# Если за последний час цена уже выросла больше этого — памп уже прошёл, пропускаем.
OI_MAX_1H_PRICE_PCT = 8.0   # % максимального роста за 1 час (0 = отключить)

# Funding Rate фильтр:
# > 0 = лонги платят шортам (бычий рынок) — хорошо для лонг сигнала
# < 0 = шорты платят лонгам (медвежий рынок) — плохо
# FUNDING_MIN = 0.0 → требуем хотя бы нейтральный funding
# Если данных нет — пропускаем фильтр (не блокируем)
FUNDING_MIN = 0.0

# CVD отслеживание:
# Когда OI монеты вырастает на OI_WATCH_PCT% — подписываемся на торговый поток
# и начинаем считать CVD. Сигнал разрешается только если CVD > 0.
OI_WATCH_PCT  = 3.0    # % OI при котором стартует CVD подписка (меньше OI_THRESHOLD_PCT)
CVD_TIMEOUT   = 1800   # секунд — автоотписка если монета так и не дала сигнал

# Cooldown: минимум секунд между двумя сигналами на один и тот же символ
SIGNAL_COOLDOWN = 3600    # 1 час — одна монета не чаще раза в час

# --- Fast Spike детектор ---
# Ловит резкие OI спайки за короткое окно (5 минут).
# Более ранний сигнал чем основной OI, но без CVD подтверждения.
# Требует ручной проверки графика перед входом.
SPIKE_PERIOD_MIN    = 5    # окно расчёта (минуты)
SPIKE_THRESHOLD_PCT = 3.0  # минимальный % роста OI за 5м
SPIKE_MAX_PRICE_PCT = 2.0  # макс рост цены за 5м (выше = уже улетело)
SPIKE_COOLDOWN      = 1800 # кулдаун 30 минут между spike сигналами

# Trade Bot — интерактивный бот для просмотра сделок и статистики
TRADE_BOT_TOKEN: str = os.environ.get("TRADE_BOT_TOKEN", "")
TRADE_BOT_CHAT_ID: int = int(os.environ.get("TRADE_BOT_CHAT_ID", os.environ.get("CHAT_ID", "0")))

# --- Агрегатор настройки ---
AGG_POLL_INTERVAL  = 5     # секунды между проверками (быстро, без API запросов)
AGG_LONG_MIN_SCORE  = 7    # минимум баллов для LONG сигнала  (уверенность ≥ 5/10)
AGG_SHORT_MIN_SCORE = 10   # минимум баллов для SHORT сигнала: памп+OI или памп+L/S+2 фильтра
AGG_MIN_OI_USD     = 500_000  # минимальный OI в USD ($500K)
AGG_COOLDOWN       = 1800  # 30 мин между повторными сигналами на символ
AGG_LS_TTL         = 300   # обновлять L/S ratio не чаще раза в 5 мин

# Bybit: сколько символов на одно WS соединение
BYBIT_BATCH = 100

# Задержка при переподключении WS (секунды)
WS_RECONNECT = 5
