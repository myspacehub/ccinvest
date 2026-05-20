#!/bin/bash
# =====================================================
# CC Invest - 快速启动脚本
# =====================================================

set -e

echo "🚀 CC Invest 系统启动脚本"
echo "========================"

# 检查 Python 版本
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装"
    exit 1
fi

# 检查目录
cd "$(dirname "$0")"

# 创建虚拟环境（如果需要）
if [ ! -d "venv" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "📥 安装依赖..."
pip install -q -r requirements.txt

# 初始化数据库
echo "🗄️ 初始化数据库..."
python main.py init

# 显示帮助
echo ""
echo "✅ 安装完成！使用以下命令启动："
echo ""
echo "  python main.py status     # 查看系统状态"
echo "  python main.py collect   # 采集数据"
echo "  python main.py backtest # 运行回测"
echo "  python main.py trade     # 启动模拟交易"
echo "  python main.py webhook  # 启动 API 服务"
echo "  python main.py start    # 启动完整系统"
echo ""
echo "  python main.py --help   # 查看所有命令"
echo ""
echo "🌐 API 文档: http://localhost:10000/docs"
echo ""

# 启动 Webhook 服务作为示例
echo "🚀 启动 Webhook 服务..."
python main.py webhook