#!/bin/bash

echo "========================================"
echo "  Crypto Bots - Установка зависимостей"
echo "========================================"
echo ""

echo "Проверка Python..."
if ! command -v python3 &> /dev/null; then
    echo "[ОШИБКА] Python3 не найден!"
    echo "Установите Python 3.10+ через менеджер пакетов вашей системы"
    exit 1
fi

python3 --version
echo ""

echo "Установка зависимостей..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo ""
    echo "[ОШИБКА] Не удалось установить зависимости"
    exit 1
fi

echo ""
echo "========================================"
echo "  Установка завершена успешно!"
echo "========================================"
echo ""
echo "Следующие шаги:"
echo "1. Создайте .env файлы в папках ботов"
echo "2. Добавьте BOT_TOKEN и CHAT_ID"
echo "3. Запустите нужные боты через ./start_*.sh"
echo ""
