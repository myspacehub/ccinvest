# =====================================================
# CC Invest - 技术分析技能 (Skill)
# OpenClaw 交易技能：技术指标分析、信号生成
# =====================================================

---
name: technical_analysis
description: 基于技术指标的加密货币分析与信号生成
version: 1.0.0
author: CC Invest Team
tags: [crypto, trading, technical-analysis, signals]
triggers: ["技术分析", "指标分析", "价格分析", "信号"]
metadata:
  openclaw:
    requires: ["database"]
    tools: ["code_execution", "http_request"]
    memory_types: ["market_data", "signals"]
  parameters:
    symbol:
      type: string
      required: true
      description: 交易对符号，如 BTCUSDT
    timeframe:
      type: string
      default: "1h"
      description: 时间周期 (1m, 5m, 15m, 1h, 4h, 1d)
    indicators:
      type: array
      items:
        type: string
      description: 要计算的技术指标列表
---

## 技能说明

本技能负责执行技术分析，包括：
1. 获取市场数据（价格、K线）
2. 计算技术指标（MA, RSI, MACD, Bollinger Bands）
3. 生成交易信号（买入/卖出/观望）
4. 评估信号强度和置信度

## 输入参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | string | ✅ | 交易对符号 |
| timeframe | string | ❌ | 时间周期，默认 1h |
| indicators | array | ❌ | 指标列表 |

## 输出格式

返回 JSON 格式的分析结果：
```json
{
  "symbol": "BTCUSDT",
  "timeframe": "1h",
  "current_price": 50000.00,
  "indicators": {
    "ma_short": 49500.00,
    "ma_long": 48000.00,
    "rsi": 65.5,
    "macd": {
      "value": 150.00,
      "signal": 120.00,
      "histogram": 30.00
    },
    "bollinger_bands": {
      "upper": 52000.00,
      "middle": 50000.00,
      "lower": 48000.00
    }
  },
  "signal": {
    "type": "BUY",
    "strength": 0.75,
    "confidence": 0.85,
    "reasoning": [
      "RSI 从超卖区域反弹",
      "价格突破布林带中轨",
      "MACD 金叉形成"
    ]
  },
  "analysis_time": "2024-01-15T10:30:00Z"
}
```

## 信号生成规则

### 买入信号 (BUY)
- RSI < 30（超卖）
- 价格触及布林带下轨后反弹
- MACD 线从下穿越信号线（金叉）
- 价格突破短期均线

### 卖出信号 (SELL)
- RSI > 70（超买）
- 价格触及布林带上轨后回落
- MACD 线从上穿越信号线（死叉）
- 价格跌破短期均线

### 观望信号 (HOLD)
- 信号不明确
- 多空力量均衡
- 市场震荡整理

## 信号强度评估

| 强度值 | 含义 |
|--------|------|
| 0.0 - 0.3 | 弱信号，建议观望 |
| 0.3 - 0.6 | 中等信号，轻仓试探 |
| 0.6 - 0.8 | 较强信号，正常仓位 |
| 0.8 - 1.0 | 强信号，可适当加仓 |

## 置信度计算

置信度基于以下因素：
- 多个指标一致性
- 指标历史表现
- 市场成交量配合
- 时间周期稳定性

---

## 执行逻辑

### Step 1: 获取数据
```
从数据库或 API 获取以下数据：
- 最近 100 根 K 线
- 实时价格
- 历史信号
```

### Step 2: 计算指标
```
使用 Python 计算：
- 移动平均线 (MA5, MA20, MA50)
- 相对强弱指数 (RSI)
- MACD (12, 26, 9)
- 布林带 (20, 2)
- ATR (14)
```

### Step 3: 信号生成
```
根据指标值判断：
- 检查超买/超卖区域
- 检查交叉信号
- 检查突破/跌破
- 综合评分
```

### Step 4: 输出结果
```
生成结构化 JSON：
- 指标数值
- 信号类型和强度
- 置信度
- 理由说明
```

---

## 示例输入

```json
{
  "symbol": "BTCUSDT",
  "timeframe": "1h",
  "indicators": ["MA", "RSI", "MACD"]
}
```

## 示例输出

```json
{
  "symbol": "BTCUSDT",
  "current_price": 50235.50,
  "change_24h": 2.35,
  "indicators": {
    "MA": {
      "MA5": 50100.00,
      "MA20": 49800.00,
      "MA50": 49500.00,
      "trend": "bullish"
    },
    "RSI": {
      "value": 68.5,
      "status": "neutral"
    },
    "MACD": {
      "value": 185.50,
      "signal": 145.20,
      "histogram": 40.30,
      "crossover": "bullish"
    },
    "Bollinger": {
      "upper": 51500.00,
      "middle": 50000.00,
      "lower": 48500.00,
      "bandwidth": 0.06
    }
  },
  "signal": {
    "type": "BUY",
    "strength": 0.72,
    "confidence": 0.80,
    "reasoning": [
      "MA20 上穿 MA50，形成多头排列",
      "RSI 处于上升趋势",
      "MACD 柱状图持续放大"
    ],
    "entry_price": 50235.50,
    "stop_loss": 48500.00,
    "take_profit": [52000.00, 54000.00]
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

---

## 注意事项

1. **风险管理优先**：即使信号很强，也要遵守风控规则
2. **多周期确认**：如可能，跨周期验证信号
3. **避免频繁交易**：考虑交易成本和滑点
4. **记录信号**：所有信号都应记录到数据库供回测使用

---

## 错误处理

| 错误码 | 说明 | 处理方式 |
|--------|------|----------|
| E001 | 数据不足 | 返回错误，请求更多历史数据 |
| E002 | API 超时 | 重试 3 次，仍失败返回缓存数据 |
| E003 | 指标计算错误 | 返回原始数据，标记错误指标 |

---

## 更新日志

### v1.0.0 (2024-01-15)
- 初始版本
- 支持 MA, RSI, MACD, Bollinger Bands
- 信号生成和置信度评估