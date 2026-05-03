#!/bin/bash

echo "========================================"
echo "  Pump Bot - Запуск"
echo "========================================"
echo ""

if [ ! -f "pump_bot/.env" ]; then
    echo "[ОШИБКА] Файл pump_bot/.env не найден!"
    echo ""
    echo "Создайте файл pump_bot/.env со следующим содержимым:"
    echo "BOT_TOKEN=ваш_telegram_bot_token"
    echo "CHAT_ID=ваш_chat_id"
    echo ""
    exit 1
fi

cd pump_bot
echo "Запуск Pump Bot..."
echo "Для остановки нажмите Ctrl+C"
echo ""
python3 main.py
