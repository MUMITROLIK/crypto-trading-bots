@echo off
chcp 65001 >nul
echo ========================================
echo   Liquidation Bot - Запуск
echo ========================================
echo.

if not exist "liq_bot\.env" (
    echo [ОШИБКА] Файл liq_bot\.env не найден!
    echo.
    echo Создайте файл liq_bot\.env со следующим содержимым:
    echo BOT_TOKEN=ваш_telegram_bot_token
    echo CHAT_ID=ваш_chat_id
    echo.
    pause
    exit /b 1
)

cd liq_bot
echo Запуск Liquidation Bot...
echo Для остановки нажмите Ctrl+C
echo.
python main.py
pause
