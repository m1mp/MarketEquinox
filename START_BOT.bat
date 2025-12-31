@echo off
echo ====================================
echo Р—Р°РїСѓСЃРє Telegram Р±РѕС‚Р° MarketEquinox
echo ====================================
echo.
REM РџСЂРѕРІРµСЂСЏРµРј РЅР°Р»РёС‡РёРµ Python
py --version >nul 2>&1
if errorlevel 1 (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo [РћРЁРР‘РљРђ] Python РЅРµ РЅР°Р№РґРµРЅ! РЈСЃС‚Р°РЅРѕРІРёС‚Рµ Python.
        pause
        exit /b 1
    )
    set PYTHON_CMD=python
) else (
    set PYTHON_CMD=py
)
echo [OK] Python РЅР°Р№РґРµРЅ
echo Setting environment variables...
set TELEGRAM_BOT_TOKEN=8570781131:AAEsSFJf44OpGXV8ML0WlOlF_l0HOgfkAE0
set ADMIN_CHAT_ID=979000473
set WEBAPP_URL=https://market-equinox.vercel.app/
echo [OK] Env variables set
echo.
echo ====================================
echo Запуск Telegram бота...
echo ====================================
echo.
echo Нажмите Ctrl+C для остановки
%PYTHON_CMD% bot.py

pause
