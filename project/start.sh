#!/bin/bash
# ========================================
#    CC Invest - 美股分析系统启动
# ========================================

cd "$(dirname "$0")"

echo "========================================"
echo "   CC Invest - 美股分析系统启动"
echo "========================================"
echo ""

# 检查 Python
echo "[1/3] 检查 Python 环境..."
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python3，请先安装"
    exit 1
fi
echo "✓ Python $(python3 --version | cut -d' ' -f2)"

# 检查依赖
echo "[2/3] 检查依赖..."
python3 -c "import loguru" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "  安装依赖中..."
    pip3 install -q -r requirements.txt
fi
echo "✓ 依赖就绪"

# 启动服务
echo "[3/3] 启动 Webhook 服务..."
echo ""
echo "服务地址:"
echo "  • Dashboard:  http://localhost:10000/reports/dashboard.html"
echo "  • API 文档:   http://localhost:10000/docs"
echo "  • 每日报告:   http://localhost:10000/webhooks/daily_report"
echo "  • 每周报告:   http://localhost:10000/webhooks/weekly_report"
echo ""
echo "按 Ctrl+C 停止服务"
echo "========================================"
echo ""

python3 main.py webhook
