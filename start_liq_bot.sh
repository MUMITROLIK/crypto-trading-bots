#!/bin/bash

echo "========================================"
echo "  Liquidation Bot - Запуск"
echo "========================================"
echo ""

if [ ! -f "liq_bot/.env" ]; then
    echo "[ОШИБКА] Файл liq_bot/.env не найден!"
    echo ""
    echo "Создайте файл liq_bot/.env со следующим содержимым:"
    echo "BOT_TOKEN=ваш_telegram_bot_token"
    echo "CHAT_ID=ваш_chat_id"
    echo ""
    exit 1
fi

cd liq_bot
echo "Запуск Liquidation Bot..."
echo "Для остановки нажмите Ctrl+C"
echo ""
python3 main.py
