@echo off
chcp 65001 >nul
echo ========================================
echo   Aggregator Bot - Запуск
echo ========================================
echo.

if not exist "aggregator_bot\.env" (
    echo [ОШИБКА] Файл aggregator_bot\.env не найден!
    echo.
    echo Создайте файл aggregator_bot\.env со следующим содержимым:
    echo BOT_TOKEN=ваш_telegram_bot_token
    echo CHAT_ID=ваш_chat_id
    echo.
    pause
    exit /b 1
)

cd aggregator_bot
echo Запуск Aggregator Bot...
echo Для остановки нажмите Ctrl+C
echo.
python main.py
pause
