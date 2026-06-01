#!/bin/bash
# ========================================
#    CC Invest - 停止服务
# ========================================

echo "停止 CC Invest 服务..."

# 停止 webhook 服务
pkill -f "python3 main.py webhook" 2>/dev/null

echo "✓ 服务已停止"
