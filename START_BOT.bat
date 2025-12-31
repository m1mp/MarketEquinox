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
echo.

REM Проверяем наличие файла
if not exist "bot.py" (
    echo [ОШИБКА] Файл bot.py не найден!
    pause
    exit /b 1
)

echo [OK] Файл bot.py найден
echo.
echo ====================================
echo Запускаю бота...
echo ====================================
echo.
echo Для остановки нажмите Ctrl+C
echo.

%PYTHON_CMD% bot.py

pause

