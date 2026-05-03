# Crypto Trading Bots

Набор ботов для мониторинга криптовалютных фьючерсов на Binance и Bybit.

## Что внутри

- **oi_bot** — мониторинг Open Interest + CVD + Aggregator с TP/SL трекингом
  - ✨ **НОВОЕ (2026-04-30):** Order Book Analysis, Footprint, Volume Profile
  - 📚 Полная документация: `oi_bot/INDEX.md`
- **pump_bot** — детектор резких движений цены (пампы/дампы)
- **liq_bot** — мониторинг ликвидаций в реальном времени
- **aggregator_bot** — скоринговая система LONG/SHORT сигналов (старая версия)

## Быстрый старт на новом компьютере

### 1. Скопируйте папку проекта

Просто скопируйте всю папку `crypto_boti` на новый компьютер.

### 2. Установите Python

Нужен Python 3.10 или новее.

**Windows:**
- Скачайте с https://www.python.org/downloads/
- При установке поставьте галочку "Add Python to PATH"

**Linux/Mac:**
```bash
python3 --version  # проверьте версию
```

### 3. Установите зависимости

Откройте терминал/командную строку в папке проекта и выполните:

```bash
pip install -r requirements.txt
```

Это установит все нужные библиотеки:
- aiohttp (HTTP клиент + WebSocket)
- websockets (WebSocket клиент)
- python-dotenv (загрузка .env файлов)

### 4. Настройте .env файлы

Каждый бот использует свой `.env` файл в своей папке.

**Для oi_bot** (создайте `oi_bot/.env`):
```env
BOT_TOKEN=ваш_telegram_bot_token
CHAT_ID=ваш_chat_id

# Агрегатор (опционально, если хотите отдельный бот для LONG/SHORT)
AGG_BOT_TOKEN=другой_bot_token
AGG_CHAT_ID=другой_chat_id
```

**Для pump_bot** (создайте `pump_bot/.env`):
```env
BOT_TOKEN=ваш_telegram_bot_token
CHAT_ID=ваш_chat_id
```

**Для liq_bot** (создайте `liq_bot/.env`):
```env
BOT_TOKEN=ваш_telegram_bot_token
CHAT_ID=ваш_chat_id
```

**Для aggregator_bot** (создайте `aggregator_bot/.env`):
```env
BOT_TOKEN=ваш_telegram_bot_token
CHAT_ID=ваш_chat_id
```

#### Как получить BOT_TOKEN:
1. Напишите @BotFather в Telegram
2. Отправьте `/newbot`
3. Следуйте инструкциям
4. Скопируйте токен

#### Как получить CHAT_ID:
1. Напишите @userinfobot в Telegram
2. Он пришлёт ваш ID

### 5. Запустите боты

Каждый бот запускается отдельно:

```bash
# OI Bot (главный, с агрегатором и трекингом сделок)
cd oi_bot
python main.py

# Pump Bot (резкие движения цены)
cd pump_bot
python main.py

# Liquidation Bot (ликвидации)
cd liq_bot
python main.py

# Aggregator Bot (старая версия, опционально)
cd aggregator_bot
python main.py
```

**Windows:** используйте `python` вместо `python3`

**Linux/Mac:** используйте `python3`

### 6. Остановка ботов

Нажмите `Ctrl+C` в терминале где запущен бот.

## Рекомендации

### Какие боты запускать?

**Минимальный набор:**
- `oi_bot` — самый мощный, включает агрегатор и трекинг сделок

**Полный набор:**
- `oi_bot` — OI сигналы + агрегатор LONG/SHORT с TP/SL
- `pump_bot` — быстрые пампы/дампы
- `liq_bot` — крупные ликвидации

**aggregator_bot** — старая версия, можно не запускать (функционал есть в oi_bot)

### Запуск в фоне (Linux/Mac)

```bash
# Запуск с логами
cd oi_bot
nohup python3 main.py > bot.log 2>&1 &

# Просмотр логов
tail -f bot.log

# Остановка
pkill -f "python3 main.py"
```

### Запуск в фоне (Windows)

Используйте Task Scheduler или запустите в отдельном окне PowerShell.

## Настройка порогов

Каждый бот имеет свой `config.py` с настройками:

**oi_bot/config.py:**
- `OI_THRESHOLD_PCT = 5.0` — минимальный рост OI для сигнала
- `OI_PERIOD_MIN = 15` — окно расчёта (минуты)
- `SIGNAL_COOLDOWN = 3600` — кулдаун между сигналами (секунды)
- `AGG_LONG_MIN_SCORE = 5` — минимум баллов для LONG
- `AGG_SHORT_MIN_SCORE = 6` — минимум баллов для SHORT

**pump_bot/config.py:**
- `LONG_THRESHOLD_PCT = 2.0` — памп для LONG сигнала
- `SHORT_THRESHOLD_PCT = 10.0` — памп для SHORT сигнала
- `DUMP_THRESHOLD_PCT = 7.0` — падение для DUMP сигнала

**liq_bot/config.py:**
- `LIQ_MIN_USD = 20_000` — минимальная ликвидация в USD

## Структура данных

Боты сохраняют данные в JSON файлы:
- `oi_cache.json` — история Open Interest
- `price_cache.json` — история цен
- `trades.json` — открытые сделки (oi_bot)
- `daily_counts.json` — счётчики сигналов за день

При перезапуске боты загружают данные из кэша (последние 2 часа).

## Требования к системе

- Python 3.10+
- 100 MB RAM на бот
- Стабильное интернет-соединение
- Открытые порты для WebSocket (обычно работает из коробки)

## Troubleshooting

**Ошибка "BOT_TOKEN not found":**
- Проверьте что `.env` файл создан в папке бота
- Проверьте что токен скопирован правильно (без пробелов)

**Бот не отправляет сообщения:**
- Проверьте CHAT_ID (должен быть числом)
- Напишите боту `/start` в Telegram
- Проверьте что токен правильный

**WebSocket ошибки:**
- Проверьте интернет-соединение
- Бот автоматически переподключится через 5 секунд

**Нет сигналов:**
- Подождите 2-3 минуты (боты собирают данные)
- Проверьте пороги в config.py (возможно слишком высокие)

## Контакты

Вопросы и предложения: создайте issue в репозитории или напишите в Telegram.
