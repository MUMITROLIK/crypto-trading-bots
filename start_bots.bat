@echo off
title Crypto Bots — Запуск
color 0A
echo.
echo  ==========================================
echo    Crypto Trading Bots — Запуск всех
echo  ==========================================
echo.

set ROOT=%~dp0

echo  [1/3] OI Screener + Aggregator + Trade Bot...
start "OI Screener + Aggregator" cmd /k "title OI+AGG+TRADE && cd /d "%ROOT%oi_bot" && py main.py"
timeout /t 3 /nobreak >nul

echo  [2/3] Pump Bot...
start "Pump Bot" cmd /k "title PUMP BOT && cd /d "%ROOT%pump_bot" && py main.py"
timeout /t 3 /nobreak >nul

echo  [3/3] Liq Bot...
start "Liq Bot" cmd /k "title LIQ BOT && cd /d "%ROOT%liq_bot" && py main.py"

echo.
echo  Все 3 бота запущены в отдельных окнах!
echo  Это окно можно закрыть.
echo.
pause
