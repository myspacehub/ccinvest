# =====================================================
# CC Invest - 交易执行技能 (Skill)
# OpenClaw 交易技能：订单执行、仓位管理
# =====================================================

---
name: trading_execution
description: 模拟交易订单执行与仓位管理
version: 1.0.0
author: CC Invest Team
tags: [crypto, trading, execution, orders]
triggers: ["下单", "交易执行", "买入", "卖出", "仓位管理"]
metadata:
  openclaw:
    requires: ["risk_manager", "database"]
    tools: ["code_execution", "http_request"]
    memory_types: ["orders", "positions", "account"]
  parameters:
    action:
      type: string
      required: true
      enum: ["BUY", "SELL"]
      description: 交易动作
    symbol:
      type: string
      required: true
      description: 交易对符号
    quantity:
      type: number
      required: true
      description: 交易数量
    order_type:
      type: string
      default: "market"
      enum: ["market", "limit", "stop_loss"]
      description: 订单类型
    price:
      type: number
      description: 限价单价格
    strategy:
      type: string
      description: 策略名称
---

## 技能说明

本技能负责执行模拟交易订单：
1. 接收交易信号
2. 风控检查（仓位、限额、断路器）
3. 模拟订单执行
4. 仓位记录与更新
5. 交易日志与审计

## 交易模式

| 模式 | 环境变量 | 说明 |
|------|----------|------|
| 模拟交易 | `TRADING_MODE=paper` | 仅记录，不实际下单 |
| 实盘交易 | `TRADING_MODE=live` | 调用真实交易所 API |

## 输入参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| action | string | ✅ | BUY / SELL |
| symbol | string | ✅ | 交易对 |
| quantity | number | ✅ | 数量 |
| order_type | string | ❌ | market / limit / stop_loss |
| price | number | ❌ | 限价 |
| strategy | string | ❌ | 策略名称 |

## 订单类型说明

### 市价单 (market)
- 以当前市场价格立即成交
- 适用于快速建仓
- 可能存在滑点

### 限价单 (limit)
- 指定价格成交
- 可能无法立即成交
- 适合挂单策略

### 止损单 (stop_loss)
- 价格触发后执行
- 用于止损保护
- 设置触发价和执行价

## 执行流程

### Step 1: 参数验证
```
检查必要参数：
- action in [BUY, SELL]
- quantity > 0
- symbol 格式正确
```

### Step 2: 风控检查
```
调用风控模块：
- check_order() → 仓位检查
- calculate_metrics() → 风险指标
- 检查断路器状态
```

### Step 3: 模拟成交
```
生成订单记录：
- 订单 ID 生成
- 模拟成交价格
- 手续费计算
- 更新账户余额
```

### Step 4: 仓位更新
```
开仓：
- 创建 position 记录
- 计算持仓成本

平仓：
- 更新 position
- 计算已实现盈亏
- 平仓记录
```

### Step 5: 日志审计
```
记录操作：
- audit_logs 表
- 交易详情
- 异常处理
```

---

## 输出格式

### 成功响应
```json
{
  "status": "success",
  "order": {
    "order_id": "SIM_20240115_100001",
    "symbol": "BTCUSDT",
    "side": "BUY",
    "quantity": 0.1,
    "price": 50000.00,
    "total": 5000.00,
    "commission": 5.00,
    "filled_at": "2024-01-15T10:00:00Z"
  },
  "position": {
    "id": 101,
    "symbol": "BTCUSDT",
    "side": "LONG",
    "quantity": 0.1,
    "entry_price": 50000.00,
    "current_price": 50000.00,
    "unrealized_pnl": 0.00
  },
  "account": {
    "balance": 5000.00,
    "total_exposure": 5000.00
  },
  "risk_metrics": {
    "risk_level": "SAFE",
    "position_count": 1,
    "total_exposure": 5000.00
  }
}
```

### 失败响应
```json
{
  "status": "rejected",
  "error": {
    "code": "RISK_LIMIT_EXCEEDED",
    "message": "单笔仓位超出限制 (5% > 2%)",
    "risk_level": "WARNING"
  },
  "suggestion": {
    "max_quantity": 0.04,
    "reason": "建议降低仓位以通过风控"
  }
}
```

---

## 风控规则

### 仓位限制
- 单笔交易 ≤ 账户余额的 2%
- 总持仓 ≤ 账户余额的 10%
- 禁止全仓操作

### 亏损限制
- 单日最大亏损 $1000
- 最大回撤 5%
- 触发后停止交易

### 订单频率
- 单日最大订单数 50
- 最小订单间隔 10 秒
- 同一标的最小间隔 60 秒

---

## 断路器机制

| 等级 | 触发条件 | 处理措施 |
|------|----------|----------|
| L1 | 日亏损达 50% 限额 | 警告，减少 50% 仓位 |
| L2 | 日亏损达 80% 限额 | 强制平仓所有头寸 |
| L3 | 日亏损达 100% 限额 | 停止所有交易 |

---

## 模拟成交算法

### 市价单成交价格
```python
# 模拟市价单成交
# 假设滑点 0.1%
slippage = 0.001
if action == "BUY":
    fill_price = current_price * (1 + slippage)
else:
    fill_price = current_price * (1 - slippage)
```

### 手续费计算
```python
# 模拟手续费 0.1%
commission_rate = 0.001
commission = order_value * commission_rate
```

---

## 示例输入

```json
{
  "action": "BUY",
  "symbol": "BTCUSDT",
  "quantity": 0.1,
  "order_type": "market",
  "strategy": "technical_analysis"
}
```

## 示例输出

```json
{
  "status": "success",
  "order_id": "SIM_20240115_100001",
  "message": "模拟买入 0.1 BTC @ 50000.00",
  "execution_price": 50050.00,
  "commission": 5.01,
  "timestamp": "2024-01-15T10:00:00Z"
}
```

---

## 错误代码

| 代码 | 说明 | 处理方式 |
|------|------|----------|
| E101 | 参数不完整 | 返回缺少参数列表 |
| E102 | 余额不足 | 建议降低数量 |
| E103 | 仓位超限 | 拒绝订单，建议分批 |
| E104 | 风控拒绝 | 返回风控详情 |
| E105 | 断路器触发 | 拒绝所有订单 |

---

## 更新日志

### v1.0.0 (2024-01-15)
- 初始版本
- 支持市价单、限价单
- 风控集成
- 仓位管理