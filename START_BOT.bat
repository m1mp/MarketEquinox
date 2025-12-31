@echo off
echo ====================================
echo Запуск Telegram бота MarketEquinox
echo ====================================
echo.
REM Проверяем наличие Python
py --version >nul 2>&1
if errorlevel 1 (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo [ОШИБКА] Python не найден! Установите Python.
        pause
        exit /b 1
    )
    set PYTHON_CMD=python
) else (
    set PYTHON_CMD=py
)
echo [OK] Python найден
echo Setting environment variables...
set TELEGRAM_BOT_TOKEN=8570781131:AAEsSFJf44OpGXV8ML0WlOlF_l0HOgfkAE0
set ADMIN_CHAT_ID=979000473
set WEBAPP_URL=https://market-equinox.vercel.app/
echo [OK] Env variables set
echo.
echo ====================================
echo ������ Telegram ����...
echo ====================================
echo.
echo ������� Ctrl+C ��� ���������
%PYTHON_CMD% 

pause
