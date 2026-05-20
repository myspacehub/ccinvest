# =====================================================
# CC Invest - 加密货币投资系统
# 基于 OpenClaw 的智能量化交易平台
# =====================================================

![CC Invest](https://img.shields.io/badge/CC%20Invest-v1.0.0-blue)
![Python](https://img.shields.io/badge/Python-3.9+-green)
![License](https://img.shields.io/badge/License-MIT-orange)

> 🤖 CC Invest 是一个基于 OpenClaw 的模块化加密货币投资系统，支持技术分析、策略回测、模拟交易和风险管理。

## 🌟 功能特性

### 📊 市场分析
- 多交易所行情数据采集（Binance、Coinbase 等）
- 链上数据监控（Etherscan、Covalent）
- 社交情绪分析（Twitter、News）
- 实时技术指标计算（MA、RSI、MACD、布林带）

### 🧠 策略系统
- **技术分析技能** - 基于指标的信号生成
- **交易执行技能** - 模拟/实盘订单执行
- **行为克隆** - 模仿资深交易员策略
- **强化学习** - 自动策略优化
- **元学习** - 快速适应市场变化

### 📈 回测引擎
- 多框架支持（Backtrader、VectorBT）
- 蒙特卡洛压力测试
- 绩效指标分析（夏普率、最大回撤、胜率）
- 历史数据回测

### 🛡️ 风险管理
- 仓位限制与断路器机制
- 自动止损/止盈
- 实时风险监控
- 合规审计日志

### 🔗 OpenClaw 集成
- 自定义 Skills 开发
- Webhook API 接口
- 长期记忆管理
- 多模型集成（GPT、Claude、Local LLM）

## 📁 项目结构

```
project/
├── main.py                    # 主程序入口
├── requirements.txt           # Python 依赖
├── .env.example              # 环境变量示例
├── start.sh                  # 快速启动脚本
│
├── skills/                   # OpenClaw 技能
│   ├── technical-analysis-skill.md
│   └── trading-execution-skill.md
│
├── src/                      # 源代码
│   ├── collector.py           # 数据采集模块
│   ├── analyzer.py            # 技术分析模块
│   ├── backtest.py            # 回测引擎
│   ├── simulator.py           # 模拟交易引擎
│   ├── risk.py                # 风控模块
│   └── webhook_server.py      # Webhook API
│
├── migrations/               # 数据库迁移
│   └── 001_initial_schema.sql
│
├── data/                     # 数据存储
├── logs/                     # 日志文件
├── reports/                  # 回测报告
│
└── .openclaw/                # OpenClaw 配置
    ├── skills.yaml           # 技能配置
    ├── memory.yaml            # 记忆配置
    └── integrations.yaml     # 集成配置
```

## 🚀 快速开始

### 1. 安装依赖

```bash
# 克隆项目
git clone https://github.com/your-repo/cc-invest.git
cd cc-invest/project

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 环境配置

```bash
# 复制环境变量文件
cp .env.example .env

# 编辑配置文件
nano .env
```

关键配置项：
```env
DATABASE_URL=sqlite:///data/ccinvest.db
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
TRADING_MODE=paper
INITIAL_CAPITAL=10000
```

### 3. 初始化数据库

```bash
python main.py init
```

### 4. 启动服务

#### 方式一：单项命令

```bash
# 采集数据
python main.py collect --symbols BTCUSDT,ETHUSDT

# 运行回测
python main.py backtest --symbol BTCUSDT --strategy mean_reversion

# 启动模拟交易
python main.py trade --mode paper

# 启动 API 服务
python main.py webhook
```

#### 方式二：一键启动完整系统

```bash
bash start.sh
# 或
python main.py start
```

### 5. 访问 API 文档

打开浏览器访问：http://localhost:10000/docs

## 📖 使用指南

### 策略回测

```bash
# 简单回测
python main.py backtest --symbol BTCUSDT --strategy mean_reversion

# 自定义参数
python main.py backtest \
  --symbol ETHUSDT \
  --strategy rsi \
  --start 2023-01-01 \
  --end 2024-01-01 \
  --capital 20000 \
  --monte-carlo 100
```

### 技术分析

```python
from src.analyzer import TechnicalAnalyzer

analyzer = TechnicalAnalyzer()
result = analyzer.analyze("BTCUSDT", "1h")

print(f"信号: {result['signal']['type']}")
print(f"置信度: {result['confidence']:.2f}")
print(f"理由: {result['reasoning']}")
```

### 模拟交易

```python
from src.simulator import SimulatorEngine

simulator = SimulatorEngine(trading_mode="paper")

# 下单
result = simulator.place_order(
    symbol="BTCUSDT",
    side="BUY",
    quantity=0.1,
    strategy="technical_analysis"
)

print(result)
```

### Webhook 调用

```bash
# 下单
curl -X POST http://localhost:10000/webhooks/place_order \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "side": "BUY",
    "quantity": 0.1,
    "strategy": "webhook_signal"
  }'

# 查询账户
curl http://localhost:10000/webhooks/account
```

### OpenClaw 技能调用

```
# 在 OpenClaw 中触发技能
> 分析 BTCUSDT 的技术指标
> 基于 RSI 策略模拟买入 0.5 ETH
> 运行趋势跟踪策略回测
```

## 📊 回测示例

```
═══════════════════════════════════════════════════════
                    回 测 报 告
═══════════════════════════════════════════════════════

📊 收益指标
─────────────────────────────────────────────────────
  初始资金:     $10,000.00
  最终资金:     $12,500.00
  总收益率:     +25.00%
  夏普比率:     1.2543

⚠️ 风险指标
─────────────────────────────────────────────────────
  最大回撤:     8.50%
  盈利因子:     2.15

📈 交易统计
─────────────────────────────────────────────────────
  总交易次数:   45
  盈利次数:     32
  亏损次数:     13
  胜率:         71.11%
  平均盈利:     $150.00
  平均亏损:     $75.00

🎲 蒙特卡洛压力测试 (n=100)
─────────────────────────────────────────────────────
  最终资金 (均值): $12,200.00
  存活率: 95.0%

═══════════════════════════════════════════════════════
```

## 🛡️ 风控规则

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 单笔最大仓位 | 2% | 单笔交易不超过账户余额的 2% |
| 总持仓上限 | 10% | 所有持仓不超过账户余额的 10% |
| 单日最大亏损 | $1000 | 日亏损超过后停止交易 |
| 最大回撤 | 5% | 回撤超过后停止所有交易 |

### 断路器等级

| 等级 | 触发条件 | 处理措施 |
|------|----------|----------|
| L1 | 日亏损达 50% | 警告，减少 50% 仓位 |
| L2 | 日亏损达 80% | 强制平仓所有头寸 |
| L3 | 日亏损达 100% | 停止所有交易 |

## 🔧 配置说明

### 数据库配置

```env
# SQLite（开发环境）
DATABASE_URL=sqlite:///data/ccinvest.db

# PostgreSQL（生产环境）
DATABASE_URL=postgresql://user:password@localhost:5432/ccinvest
```

### 交易所 API

```env
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
```

### 风控参数

```env
MAX_POSITION_SIZE=0.02      # 2%
MAX_TOTAL_POSITION=0.10     # 10%
MAX_DAILY_LOSS=1000.0       # $1000
MAX_DRAWDOWN=0.05           # 5%
```

## 📝 数据库表结构

| 表名 | 说明 |
|------|------|
| `market_data` | 市场行情数据 |
| `ohlc_data` | K 线数据 |
| `chain_data` | 链上数据 |
| `sentiment` | 情绪数据 |
| `accounts` | 账户信息 |
| `positions` | 持仓记录 |
| `orders` | 订单记录 |
| `trades` | 交易记录 |
| `signals` | 策略信号 |
| `backtest_results` | 回测结果 |
| `risk_logs` | 风控日志 |
| `audit_logs` | 审计日志 |

## 🔌 API 接口

### Webhook 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/webhooks/place_order` | POST | 下单 |
| `/webhooks/signal` | POST | 记录信号 |
| `/webhooks/risk_check` | POST | 风控检查 |
| `/webhooks/account` | GET | 查询账户 |
| `/webhooks/positions` | GET | 查询持仓 |
| `/webhooks/orders` | GET | 查询订单 |

### OpenClaw 集成

| 接口 | 方法 | 说明 |
|------|------|------|
| `/agent/analysis` | POST | 技术分析 |
| `/agent/backtest` | POST | 回测请求 |

### 系统接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/metrics` | GET | 指标数据 |

## 🐛 故障排查

### 数据获取失败

```bash
# 检查 API 配置
cat .env | grep BINANCE

# 测试 API 连接
python -c "import requests; print(requests.get('https://api.binance.com/api/v3/ping').json())"
```

### 数据库错误

```bash
# 重新初始化数据库
rm data/ccinvest.db
python main.py init
```

### 端口占用

```bash
# 查找占用进程
lsof -i :10000

# 杀死进程
kill -9 <PID>
```

## 🤝 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 🙏 致谢

- [OpenClaw](https://github.com/openclaw) - AI Agent 框架
- [Backtrader](https://www.backtrader.com/) - 回测框架
- [VectorBT](https://vectorbt.dev/) - 向量化回测
- [CCXT](https://github.com/ccxt/ccxt) - 交易所接口

## 📬 联系方式

- **作者**: Your Name
- **邮箱**: your.email@example.com
- **Telegram**: @your_username

---

<div align="center">

**如果这个项目对您有帮助，请给个 ⭐ Star！**

Made with ❤️ for crypto traders

</div>