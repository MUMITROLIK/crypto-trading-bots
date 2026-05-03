# Crypto Trading Bots

Bots for monitoring crypto futures on Binance and Bybit.

## What's inside

- **oi_bot** — Open Interest + CVD + Aggregator with TP/SL tracking
  - Order Book Analysis, Footprint, Volume Profile
  - Full docs: `oi_bot/INDEX.md`
- **pump_bot** — detects sharp price movements
- **liq_bot** — liquidation monitoring
- **aggregator_bot** — LONG/SHORT scoring system (old version)

## Quick start

### 1. Copy project folder

Copy the entire `crypto_boti` folder to your computer.

### 2. Install Python

Need Python 3.10 or newer.

**Windows:**
- Download from https://www.python.org/downloads/
- Check "Add Python to PATH" during install

**Linux/Mac:**
```bash
python3 --version  # check version
```

### 3. Install dependencies

Open terminal in project folder:

```bash
pip install -r requirements.txt
```

Libraries:
- aiohttp (HTTP + WebSocket)
- websockets (WebSocket client)
- python-dotenv (.env files)

### 4. Setup .env files

Each bot uses its own `.env` file in its folder.

**For oi_bot** (create `oi_bot/.env`):
```env
BOT_TOKEN=your_telegram_bot_token
CHAT_ID=your_chat_id

# Aggregator (optional, if you want separate bot for LONG/SHORT)
AGG_BOT_TOKEN=another_bot_token
AGG_CHAT_ID=another_chat_id
```

**For pump_bot** (create `pump_bot/.env`):
```env
BOT_TOKEN=your_telegram_bot_token
CHAT_ID=your_chat_id
```

**For liq_bot** (create `liq_bot/.env`):
```env
BOT_TOKEN=your_telegram_bot_token
CHAT_ID=your_chat_id
```

**For aggregator_bot** (create `aggregator_bot/.env`):
```env
BOT_TOKEN=your_telegram_bot_token
CHAT_ID=your_chat_id
```

#### Get BOT_TOKEN:
1. Message @BotFather in Telegram
2. Send `/newbot`
3. Follow instructions
4. Copy token

#### Get CHAT_ID:
1. Message @userinfobot in Telegram
2. It will send your ID

### 5. Run bots

Each bot runs separately:

```bash
# OI Bot (main, with aggregator and trade tracking)
cd oi_bot
python main.py

# Pump Bot (sharp price movements)
cd pump_bot
python main.py

# Liquidation Bot
cd liq_bot
python main.py

# Aggregator Bot (old version, optional)
cd aggregator_bot
python main.py
```

**Windows:** use `python` instead of `python3`

**Linux/Mac:** use `python3`

### 6. Stop bots

Press `Ctrl+C` in terminal where bot is running.

## Recommendations

### Which bots to run?

**Minimal:**
- `oi_bot` — most powerful, includes aggregator and trade tracking

**Full set:**
- `oi_bot` — OI signals + LONG/SHORT aggregator with TP/SL
- `pump_bot` — fast pumps/dumps
- `liq_bot` — large liquidations

**aggregator_bot** — old version, optional (functionality in oi_bot)

### Run in background (Linux/Mac)

```bash
# Run with logs
cd oi_bot
nohup python3 main.py > bot.log 2>&1 &

# View logs
tail -f bot.log

# Stop
pkill -f "python3 main.py"
```

### Run in background (Windows)

Use Task Scheduler or run in separate PowerShell window.

## Threshold settings

Each bot has its own `config.py`:

**oi_bot/config.py:**
- `OI_THRESHOLD_PCT = 5.0` — min OI growth for signal
- `OI_PERIOD_MIN = 15` — calculation window (minutes)
- `SIGNAL_COOLDOWN = 3600` — cooldown between signals (seconds)
- `AGG_LONG_MIN_SCORE = 5` — min score for LONG
- `AGG_SHORT_MIN_SCORE = 6` — min score for SHORT

**pump_bot/config.py:**
- `LONG_THRESHOLD_PCT = 2.0` — pump for LONG signal
- `SHORT_THRESHOLD_PCT = 10.0` — pump for SHORT signal
- `DUMP_THRESHOLD_PCT = 7.0` — drop for DUMP signal

**liq_bot/config.py:**
- `LIQ_MIN_USD = 20_000` — min liquidation in USD

## Data structure

Bots save data to JSON files:
- `oi_cache.json` — Open Interest history
- `price_cache.json` — price history
- `trades.json` — open trades (oi_bot)
- `daily_counts.json` — daily signal counters

On restart bots load data from cache (last 2 hours).

## System requirements

- Python 3.10+
- 100 MB RAM per bot
- Stable internet connection
- Open ports for WebSocket (usually works out of the box)

## Troubleshooting

**Error "BOT_TOKEN not found":**
- Check that `.env` file is created in bot folder
- Check that token is copied correctly (no spaces)

**Bot doesn't send messages:**
- Check CHAT_ID (must be a number)
- Message bot `/start` in Telegram
- Check that token is correct

**WebSocket errors:**
- Check internet connection
- Bot will auto-reconnect in 5 seconds

**No signals:**
- Wait 2-3 minutes (bots collecting data)
- Check thresholds in config.py (maybe too high)

## Contact

Questions and suggestions: create issue in repository or message in Telegram.
