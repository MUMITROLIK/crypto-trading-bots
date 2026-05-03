@echo off
chcp 65001 >nul
echo ========================================
echo   Pump Bot - Запуск
echo ========================================
echo.

if not exist "pump_bot\.env" (
    echo [ОШИБКА] Файл pump_bot\.env не найден!
    echo.
    echo Создайте файл pump_bot\.env со следующим содержимым:
    echo BOT_TOKEN=ваш_telegram_bot_token
    echo CHAT_ID=ваш_chat_id
    echo.
    pause
    exit /b 1
)

cd pump_bot
echo Запуск Pump Bot...
echo Для остановки нажмите Ctrl+C
echo.
python main.py
pause
