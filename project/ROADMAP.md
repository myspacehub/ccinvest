# CC Invest 项目路线图
# 待完成步骤清单

## 📋 当前项目状态

| 模块 | 状态 | 说明 |
|------|------|------|
| 数据采集 (collector.py) | ✅ 完成 | 多源数据、验证、缓存 |
| 数据验证 (data_validator.py) | ✅ 完成 | 真实性检查、交叉验证 |
| 多源数据 (multi_source_data.py) | ✅ 完成 | 7个真实数据源 |
| 时间工具 (time_utils.py) | ✅ 完成 | 上海时区处理 |
| 风控模块 (risk.py) | ✅ 完成 | 断路器机制 |
| 模拟交易 (simulator.py) | ✅ 完成 | 订单执行、持仓管理 |
| 回测引擎 (backtest.py) | ✅ 完成 | 技术分析、回测框架 |
| 技术分析 (analyzer.py) | ✅ 完成 | MA/RSI/MACD/布林带 |
| Webhook API (webhook_server.py) | ✅ 完成 | REST API 接口 |
| 数据库 (migrations/) | ✅ 完成 | 完整表结构 |
| Skills | ✅ 完成 | 技术分析 + 交易执行 |
| 长期记忆 | ✅ 完成 | 规则 + 用户偏好 |
| **数据库初始化** | ⏳ 待完成 | 需要创建数据库 |
| **真实数据导入** | ⏳ 待完成 | 采集历史数据 |
| **OpenClaw 集成** | ⏳ 待完成 | 配置并启动 |
| **API 服务启动** | ⏳ 待完成 | 启动 Webhook |
| **前端界面** | 🔲 待开发 | 可选 Dashboard |
| **实盘对接** | 🔲 待规划 | 需要 API Key |

---

## 🔴 第一阶段：基础搭建（必须先完成）

### 1.1 数据库初始化
```bash
cd /Users/myworld/.openclaw/cc-invest/project
python main.py init
# 或
python migrations/init_db.py
```
**检查点**: 数据库文件 `data/ccinvest.db` 创建成功

### 1.2 配置环境变量
```bash
cp .env.example .env
# 编辑 .env，设置必要的配置项
nano .env
```
**必须配置**:
- `DATABASE_URL`: 数据库路径
- `INITIAL_CAPITAL`: 初始资金

**可选配置** (需要申请):
- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`
- `COINGECKO_API_KEY`

### 1.3 安装依赖
```bash
pip install -r requirements.txt
```
**检查点**: 所有模块可正常 import

---

## 🟡 第二阶段：数据准备（核心功能依赖）

### 2.1 历史数据导入
```bash
# 当前版本使用实时采集，历史数据通过以下方式导入
python main.py collect --symbols BTCUSDT,ETHUSDT
# 系统会自动获取历史数据（需要数据库已有基础数据）
```
**说明**: 导入最近 30 天历史数据用于回测

### 2.2 实时数据采集测试
```bash
python main.py collect --symbols BTCUSDT,ETHUSDT
```
**检查点**: 数据成功写入数据库

### 2.3 数据质量验证
```bash
python -c "from src.data_validator import DataValidator; dv = DataValidator(); print(dv.validate_database())"
```
**检查点**: 数据通过真实性验证

---

## 🟢 第三阶段：功能验证

### 3.1 技术分析测试
```bash
# 技术分析通过 Python 模块调用
python -c "from src.analyzer import TechnicalAnalyzer; ta = TechnicalAnalyzer(); print(ta.analyze('BTCUSDT', '1h'))"
```
**检查点**: 返回 MA/RSI/MACD 信号

### 3.2 回测测试
```bash
python main.py backtest --symbol BTCUSDT --strategy rsi --days 30
```
**检查点**: 生成回测报告

### 3.3 模拟交易测试
```bash
python main.py trade --mode paper --symbol BTCUSDT
```
**检查点**: 
- 模拟账户创建成功
- 订单成功执行
- 持仓正确更新

### 3.4 风控测试
```bash
python -c "from src.risk import RiskManager; rm = RiskManager(); print(rm.get_risk_report())"
```
**检查点**: 风控状态正常，断路器未触发

---

## 🔵 第四阶段：系统集成

### 4.1 启动 Webhook API
```bash
python main.py webhook
# 或
python src/webhook_server.py
```
**检查点**: API 服务在 http://localhost:10000 启动

### 4.2 API 接口测试
```bash
# 健康检查
curl http://localhost:10000/health

# 获取账户
curl http://localhost:10000/webhooks/account

# 获取价格
curl http://localhost:10000/webhooks/price/BTCUSDT
```

### 4.3 OpenClaw 集成
```bash
# 启动 OpenClaw
openclaw start

# 测试 Skills
openclaw agent "分析 BTCUSDT 的 RSI 指标"
```
**检查点**: OpenClaw 正确加载 Skills

---

## 🟣 第五阶段：优化与监控

### 5.1 配置定时任务
```bash
# 添加到 crontab
crontab -e

# 每 5 分钟采集数据
*/5 * * * * cd /path/to/project && python main.py collect --symbols BTCUSDT,ETHUSDT >> logs/collect.log 2>&1
```

### 5.2 配置日志监控
```bash
# 查看日志
tail -f logs/ccinvest.log

# 设置日志告警
# 编辑 logs/alert_rules.yaml
```

### 5.3 性能优化
```bash
# 添加索引
python -c "
from src.data_validator import DataValidator
dv = DataValidator()
dv.optimize_database()
"

# 清理旧数据
python main.py cleanup --days 90
```

---

## 🟠 第六阶段：可选增强

### 6.1 前端 Dashboard (可选)
- 开发 Web 界面
- 实时图表展示
- 持仓监控面板

### 6.2 实盘准备 (可选)
- 获取交易所 API Key
- 配置实盘模式
- 设置资金限制
- 小额实盘测试

### 6.3 策略增强 (可选)
- 添加更多技术指标
- 机器学习策略
- 多周期策略

---

## 📞 快速验证命令

```bash
# 一键检查项目状态
python main.py status

# 检查数据源
python -c "
import sys
sys.path.insert(0, 'src')
from multi_source_data import MultiSourceDataManager
m = MultiSourceDataManager()
data, meta = m.get_price('ETHUSDT')
print(f'价格: {data[\"price\"] if data else \"失败\"}')
print(f'来源: {meta[\"final_source\"]}')
"
```

---

## ⚠️ 注意事项

1. **数据真实性**: 所有数据必须来自真实 API，禁止模拟
2. **时区**: 所有显示使用上海时区 (CST, UTC+8)
3. **安全**: 不要将 API Key 提交到代码仓库
4. **测试**: 切换实盘前必须充分测试模拟交易

---

**最后更新**: 2024-05-14 02:04 CST