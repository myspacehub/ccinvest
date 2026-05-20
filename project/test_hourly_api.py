import asyncio
import uvicorn
from src.webhook_server import app

# 测试请求
from fastapi.testclient import TestClient
client = TestClient(app)

# 测试1: 小时线
print("测试1: hour线 (1h)")
r = client.get("/webhooks/history/BTCUSDT?interval=1h&limit=2")
print(f"状态: {r.status_code}")
print(f"响应: {r.json()}")

# 测试2: 日线
print("\n测试2: 日线 (1d)")
r = client.get("/webhooks/history/BTCUSDT?interval=1d&limit=2")
print(f"状态: {r.status_code}")
print(f"响应: {r.json()}")
