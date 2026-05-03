#!/bin/bash

echo "========================================"
echo "  Aggregator Bot - Запуск"
echo "========================================"
echo ""

if [ ! -f "aggregator_bot/.env" ]; then
    echo "[ОШИБКА] Файл aggregator_bot/.env не найден!"
    echo ""
    echo "Создайте файл aggregator_bot/.env со следующим содержимым:"
    echo "BOT_TOKEN=ваш_telegram_bot_token"
    echo "CHAT_ID=ваш_chat_id"
    echo ""
    exit 1
fi

cd aggregator_bot
echo "Запуск Aggregator Bot..."
echo "Для остановки нажмите Ctrl+C"
echo ""
python3 main.py
