# Быстрая инструкция по переносу на другой компьютер

## Шаг 1: Скопируйте папку
Скопируйте всю папку `crypto_boti` на новый компьютер (через флешку, облако, или любым способом).

## Шаг 2: Установите Python
- **Windows**: https://www.python.org/downloads/ (поставьте галочку "Add Python to PATH")
- **Linux/Mac**: обычно уже установлен, проверьте `python3 --version`

## Шаг 3: Установите зависимости

### Windows:
Двойной клик на `SETUP.bat` или в командной строке:
```
SETUP.bat
```

### Linux/Mac:
```bash
chmod +x setup.sh
./setup.sh
```

## Шаг 4: Создайте .env файлы

Создайте файл `.env` в каждой папке бота, который хотите запустить:

**oi_bot/.env:**
```
BOT_TOKEN=ваш_telegram_bot_token
CHAT_ID=ваш_chat_id
AGG_BOT_TOKEN=другой_bot_token
AGG_CHAT_ID=другой_chat_id
```

**pump_bot/.env:**
```
BOT_TOKEN=ваш_telegram_bot_token
CHAT_ID=ваш_chat_id
```

**liq_bot/.env:**
```
BOT_TOKEN=ваш_telegram_bot_token
CHAT_ID=ваш_chat_id
```

**aggregator_bot/.env:**
```
BOT_TOKEN=ваш_telegram_bot_token
CHAT_ID=ваш_chat_id
```

### Как получить токены:
- **BOT_TOKEN**: напишите @BotFather в Telegram → `/newbot`
- **CHAT_ID**: напишите @userinfobot в Telegram

## Шаг 5: Запустите боты

### Windows:
Двойной клик на нужный файл:
- `START_OI_BOT.bat` — главный бот (OI + агрегатор + трекинг сделок)
- `START_PUMP_BOT.bat` — пампы/дампы
- `START_LIQ_BOT.bat` — ликвидации
- `START_AGGREGATOR_BOT.bat` — старый агрегатор (опционально)

### Linux/Mac:
```bash
chmod +x start_*.sh
./start_oi_bot.sh
```

## Готово!
Боты запустятся и начнут присылать сигналы в Telegram.

Для остановки нажмите `Ctrl+C` в окне бота.

---

## Рекомендуемая конфигурация

**Минимум (один бот):**
- `oi_bot` — самый мощный, включает всё

**Оптимально (два бота):**
- `oi_bot` — OI сигналы + агрегатор с TP/SL
- `liq_bot` — крупные ликвидации

**Максимум (три бота):**
- `oi_bot`
- `pump_bot`
- `liq_bot`

`aggregator_bot` можно не запускать — его функционал уже встроен в `oi_bot`.
