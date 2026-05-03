@echo off
chcp 65001 >nul
echo ========================================
echo   Crypto Bots - Установка зависимостей
echo ========================================
echo.

echo Проверка Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден!
    echo Скачайте Python 3.10+ с https://www.python.org/downloads/
    echo При установке поставьте галочку "Add Python to PATH"
    pause
    exit /b 1
)

python --version
echo.

echo Установка зависимостей...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Не удалось установить зависимости
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Установка завершена успешно!
echo ========================================
echo.
echo Следующие шаги:
echo 1. Создайте .env файлы в папках ботов
echo 2. Добавьте BOT_TOKEN и CHAT_ID
echo 3. Запустите нужные боты через START_*.bat
echo.
pause
