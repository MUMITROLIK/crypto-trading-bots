#!/bin/bash

echo "========================================"
echo "  OI Bot - Запуск"
echo "========================================"
echo ""

if [ ! -f "oi_bot/.env" ]; then
    echo "[ОШИБКА] Файл oi_bot/.env не найден!"
    echo ""
    echo "Создайте файл oi_bot/.env со следующим содержимым:"
    echo "BOT_TOKEN=ваш_telegram_bot_token"
    echo "CHAT_ID=ваш_chat_id"
    echo ""
    echo "Опционально для агрегатора:"
    echo "AGG_BOT_TOKEN=другой_bot_token"
    echo "AGG_CHAT_ID=другой_chat_id"
    echo ""
    exit 1
fi

cd oi_bot
echo "Запуск OI Bot..."
echo "Для остановки нажмите Ctrl+C"
echo ""
python3 main.py
