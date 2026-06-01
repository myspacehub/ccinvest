# CC Invest - Cloudflare Worker 部署指南

## 📋 概述

这是一个简化的 Cloudflare Worker Webhook，专为 Cloudflare Workers 部署优化。

**注意**: 完整的 FastAPI 后端 (`src/webhook_server.py`) 功能更丰富，但需要完整的 Python 环境。Cloudflare Workers 只支持简化版本。

## 🚀 快速部署

### 前置要求

- Node.js 18+
- npm
- Cloudflare 账号 (免费即可)
- Wrangler CLI (已安装)

### 1. 配置环境变量

在 `wrangler.jsonc` 中修改 `WEBHOOK_TOKEN`:

```json
"vars": {
  "WEBHOOK_TOKEN": "your_secure_token_here"
}
```

或在 Cloudflare Dashboard 中设置。

### 2. 本地测试

```bash
cd /Users/myworld/.openclaw/cc-invest/cloudflare-worker
npm run dev
```

访问 http://localhost:8787

### 3. 部署

```bash
npm run deploy
```

## 📡 API 端点

### GET /health
健康检查

### GET /webhooks/price/:symbol
获取代币价格

```bash
curl "https://cc-invest-webhook.your-subdomain.workers.dev/webhooks/price/BTCUSDT"
```

### POST /webhooks/place_order
下单 (模拟)

```bash
curl -X POST "https://cc-invest-webhook.your-subdomain.workers.dev/webhooks/place_order" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_token" \
  -d '{"symbol":"BTCUSDT","side":"BUY","quantity":0.1}'
```

### POST /webhooks/signal
记录交易信号

```bash
curl -X POST "https://cc-invest-webhook.your-subdomain.workers.dev/webhooks/signal" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_token" \
  -d '{"symbol":"ETHUSDT","strategy":"rsi","signal_type":"BUY","strength":0.8}'
```

### GET /webhooks/orders
获取订单历史

## 🔧 完整版 vs 简化版

| 功能 | 完整版 (FastAPI) | 简化版 (Worker) |
|------|-----------------|----------------|
| 价格查询 | ✅ 多源交叉验证 | ✅ CoinGecko + DexScreener |
| 下单 | ✅ 模拟/实盘 | ✅ 仅模拟 |
| 风控检查 | ✅ | ❌ |
| 历史K线 | ✅ | ❌ |
| 回测引擎 | ✅ | ❌ |
| 策略信号 | ✅ | ❌ |
| 部署平台 | Render/Railway | Cloudflare Workers |

## 🌐 部署完整版 (推荐)

如果需要完整功能，建议部署到 Render:

```bash
# 1. Push 到 GitHub
cd /Users/myworld/.openclaw/cc-invest
git add .
git commit -m "Add full cc-invest project"
git push

# 2. 在 Render.com 连接 GitHub 仓库
# 3. 使用 render.yaml 自动部署
```

## 📝 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| WEBHOOK_TOKEN | Webhook 认证 Token | default_secret_change_me |

## ❓ 常见问题

### Q: Worker 超出 CPU 时间限制?
A: Cloudflare Workers 有 30ms CPU 时间限制。复杂计算建议使用完整版。

### Q: 如何添加更多代币支持?
A: 编辑 `COINGECKO_IDS` 对象添加新的代币映射。

### Q: 如何持久化存储?
A: 使用 Cloudflare KV 或 Durable Objects。
