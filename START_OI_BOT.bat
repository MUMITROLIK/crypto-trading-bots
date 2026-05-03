@echo off
chcp 65001 >nul
echo ========================================
echo   OI Bot - Запуск
echo ========================================
echo.

if not exist "oi_bot\.env" (
    echo [ОШИБКА] Файл oi_bot\.env не найден!
    echo.
    echo Создайте файл oi_bot\.env со следующим содержимым:
    echo BOT_TOKEN=ваш_telegram_bot_token
    echo CHAT_ID=ваш_chat_id
    echo.
    echo Опционально для агрегатора:
    echo AGG_BOT_TOKEN=другой_bot_token
    echo AGG_CHAT_ID=другой_chat_id
    echo.
    pause
    exit /b 1
)

cd oi_bot
echo Запуск OI Bot...
echo Для остановки нажмите Ctrl+C
echo.
python main.py
pause
