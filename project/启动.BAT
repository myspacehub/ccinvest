@echo off
chcp 65001 >nul
echo ========================================
echo    CC Invest - 美股分析系统启动
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)

echo [2/3] 检查依赖...
pip show loguru >nul 2>&1
if errorlevel 1 (
    echo [警告] 缺少依赖，正在安装...
    pip install -r requirements.txt
)

echo [3/3] 启动 Webhook 服务...
echo.
echo 服务地址:
echo   - Dashboard: http://localhost:10000/reports/dashboard.html
echo   - API 文档:  http://localhost:10000/docs
echo   - 每日报告:  http://localhost:10000/webhooks/daily_report
echo   - 每周报告:  http://localhost:10000/webhooks/weekly_report
echo.
echo 按 Ctrl+C 停止服务
echo ========================================
echo.

python main.py webhook

pause
