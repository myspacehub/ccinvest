@echo off
chcp 65001 >nul
echo ========================================
echo    CC Invest - 停止服务
echo ========================================
echo.

taskkill /f /im python.exe 2>nul
echo 已停止所有 Python 服务

echo.
pause
