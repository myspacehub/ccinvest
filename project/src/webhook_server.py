# =====================================================
# CC Invest - OpenClaw Webhook 配置
# 支持外部系统通过 Webhook 调用交易功能
# =====================================================

import os
import json
import hmac
import hashlib
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from functools import wraps
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Depends, Header, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

class HTMLResponse(JSONResponse):

    def __init__(self, content: str, status_code: int = 200):

        super().__init__(content=content, status_code=status_code, media_type="text/html")



from pydantic import BaseModel, Field
from dotenv import load_dotenv
from loguru import logger

# 加载配置
load_dotenv()

# 导入优化的价格获取模块
try:
    from src.price_fetcher import get_price_with_fallback, get_market_data_with_fallback
    HAS_PRICE_FETCHER = True
except ImportError:
    HAS_PRICE_FETCHER = False
    logger.warning("price_fetcher 模块不可用，使用旧版数据获取")

# =====================================================
# Pydantic 模型
# =====================================================

class OrderRequest(BaseModel):
    """订单请求模型"""
    symbol: str = Field(..., description="交易对符号", example="BTCUSDT")
    side: str = Field(..., description="交易方向: BUY or SELL")
    quantity: float = Field(..., gt=0, description="交易数量")
    order_type: str = Field(default="market", description="订单类型: market, limit, stop_loss")
    price: Optional[float] = Field(None, description="限价单价格")
    stop_price: Optional[float] = Field(None, description="止损价格")
    strategy: str = Field(default="webhook", description="策略名称")
    webhook_id: Optional[str] = Field(None, description="Webhook ID 用于追踪")

class SignalRequest(BaseModel):
    """信号请求模型"""
    symbol: str = Field(..., description="交易对符号")
    strategy: str = Field(..., description="策略名称")
    signal_type: str = Field(..., description="信号类型: BUY, SELL, HOLD")
    strength: float = Field(default=0.5, ge=0, le=1, description="信号强度 0-1")
    confidence: float = Field(default=0.5, ge=0, le=1, description="置信度 0-1")
    indicators: Optional[Dict] = Field(None, description="指标数据")
    reasoning: Optional[List[str]] = Field(None, description="理由说明")

class RiskCheckRequest(BaseModel):
    """风控检查请求"""
    symbol: str
    side: str
    quantity: float
    price: Optional[float] = None

class AccountRequest(BaseModel):
    """账户查询请求"""
    account_id: int = Field(default=1, description="账户 ID")

# =====================================================
# Webhook 安全验证
# =====================================================

WEBHOOK_SECRET = os.getenv("OPENCLAW_WEBHOOK_TOKEN", "default_secret_change_me")

# 速率限制配置
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))  # 每分钟请求数
RATE_LIMIT_BURST = int(os.getenv("RATE_LIMIT_BURST", "10"))  # 突发限制

# 简单的内存速率限制器
class SimpleRateLimiter:
    """简单的速率限制器"""
    def __init__(self):
        self.requests = {}
        self.last_reset = time.time()
    
    def is_allowed(self, client_id: str) -> bool:
        now = time.time()
        # 每分钟重置
        if now - self.last_reset > 60:
            self.requests.clear()
            self.last_reset = now
        
        # 检查请求数
        if client_id in self.requests:
            if self.requests[client_id] >= RATE_LIMIT_REQUESTS:
                return False
            self.requests[client_id] += 1
        else:
            self.requests[client_id] = 1
        
        return True

rate_limiter = SimpleRateLimiter()


async def verify_webhook_signature(request: Request, x_webhook_signature: str = Header(None)):
    """验证 Webhook 签名"""
    # ⚠️ 生产环境：环境变量设置为 production 时强制启用签名验证
    env_mode = os.getenv("ENVIRONMENT", "development")
    
    if env_mode != "production" and (not WEBHOOK_SECRET or WEBHOOK_SECRET == "default_secret_change_me"):
        logger.warning("开发环境：跳过签名验证")
        return True  # 开发环境跳过验证
    
    if not x_webhook_signature:
        if env_mode == "production":
            raise HTTPException(status_code=401, detail="缺少签名")
        return True
    
    # 计算签名
    body = await request.body()
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(x_webhook_signature, expected_signature):
        raise HTTPException(status_code=401, detail="签名验证失败")
    
    return True

def generate_webhook_signature(payload: str) -> str:
    """生成 Webhook 签名"""
    return hmac.new(
        WEBHOOK_SECRET.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

# =====================================================
# FastAPI 应用
# =====================================================

app = FastAPI(
    title="CC Invest Webhook API",
    description="加密货币交易系统 Webhook 接口",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件服务 (Dashboard)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 挂载静态文件目录
reports_dir = Path(__file__).parent.parent / "reports"
if reports_dir.exists():
    app.mount("/static", StaticFiles(directory=str(reports_dir)), name="static")

# Dashboard 入口路由
@app.get("/", tags=["前端"])
async def dashboard_index():
    """Dashboard 主页"""
    dashboard_path = reports_dir / "dashboard.html"
    if dashboard_path.exists():
        return FileResponse(str(dashboard_path))
    return HTMLResponse(content="""
        <html><body>
        <h1>CC Invest Dashboard</h1>
        <p>Dashboard 文件未找到。</p>
        <p>请访问 <a href="/docs">API 文档</a></p>
        </body></html>
    """)

@app.get("/reports/dashboard", tags=["前端"])
@app.get("/reports/dashboard.html", tags=["前端"])
async def reports_dashboard():
    """Reports Dashboard 页面"""
    dashboard_path = reports_dir / "dashboard.html"
    if dashboard_path.exists():
        return FileResponse(str(dashboard_path))
    raise HTTPException(status_code=404, detail="Dashboard not found")

@app.get("/dashboard", tags=["前端"])
async def dashboard():
    """Dashboard 页面"""
    dashboard_path = reports_dir / "dashboard.html"
    if dashboard_path.exists():
        return FileResponse(str(dashboard_path))
    raise HTTPException(status_code=404, detail="Dashboard not found")

# HTML 响应类
# =====================================================
# 辅助函数
# =====================================================
# 辅助函数
# =====================================================

def get_simulator():
    """获取模拟器实例"""
    from src.simulator import SimulatorEngine
    from dotenv import load_dotenv
    load_dotenv()
    import os
    db_url = os.getenv("DATABASE_URL", "sqlite:///data/ccinvest.db")
    return SimulatorEngine(database_url=db_url, trading_mode="paper", initial_balance=10000.0)

def get_risk_manager():
    """获取风控管理器"""
    from src.risk import RiskManager
    return RiskManager()

# =====================================================
# Webhook 路由
# =====================================================

@app.post("/webhooks/place_order", tags=["交易"])
async def webhook_place_order(
    raw_request: Request,
    payload: OrderRequest,
    x_webhook_signature: str = Header(None)
):
    """
    Webhook: 下单接口
    
    通过 Webhook 接收外部交易信号并执行模拟订单
    
    **请求示例:**
    ```json
    {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": 0.1,
        "order_type": "market",
        "strategy": "moving_average_crossover",
        "webhook_id": "signal_123"
    }
    ```
    """
    try:
        # 速率限制检查
        if RATE_LIMIT_ENABLED:
            client_id = raw_request.client.host if raw_request.client else "unknown"
            if not rate_limiter.is_allowed(client_id):
                raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")
        
        # 验证签名
        await verify_webhook_signature(raw_request, x_webhook_signature)
        
        simulator = get_simulator()
        
        result = simulator.place_order(
            symbol=payload.symbol,
            side=payload.side,
            quantity=payload.quantity,
            order_type=payload.order_type,
            price=payload.price,
            stop_price=payload.stop_price,
            strategy=payload.strategy
        )
        
        # 记录 Webhook 调用
        logger.info(f"Webhook 下单 | {payload.webhook_id} | {result}")
        
        return {
            "status": "success",
            "webhook_id": payload.webhook_id,
            "result": result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook 下单失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhooks/signal", tags=["信号"])
async def webhook_signal(
    raw_request: Request,
    payload: SignalRequest,
    x_webhook_signature: str = Header(None)
):
    """
    Webhook: 信号记录接口
    
    记录外部生成的交易信号
    
    **请求示例:**
    ```json
    {
        "symbol": "BTCUSDT",
        "strategy": "rsi_divergence",
        "signal_type": "BUY",
        "strength": 0.8,
        "confidence": 0.75,
        "reasoning": ["RSI 超卖", "底背离形成"]
    }
    ```
    """
    try:
        # 速率限制检查
        if RATE_LIMIT_ENABLED:
            client_id = raw_request.client.host if raw_request.client else "unknown"
            if not rate_limiter.is_allowed(client_id):
                raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")
        
        # 验证签名
        await verify_webhook_signature(raw_request, x_webhook_signature)
        
        # 保存信号到数据库
        from sqlalchemy import create_engine, text
        db_url = os.getenv("DATABASE_URL", "sqlite:///data/ccinvest.db")
        engine = create_engine(db_url)
        
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO signals (symbol, strategy, signal_type, strength, confidence, indicators, reasoning, generated_at)
                VALUES (:symbol, :strategy, :signal_type, :strength, :confidence, :indicators, :reasoning, :generated_at)
            """), {
                "symbol": payload.symbol,
                "strategy": payload.strategy,
                "signal_type": payload.signal_type,
                "strength": payload.strength,
                "confidence": payload.confidence,
                "indicators": json.dumps(payload.indicators) if payload.indicators else None,
                "reasoning": json.dumps(payload.reasoning) if payload.reasoning else None,
                "generated_at": datetime.utcnow()
            })
            conn.commit()
        
        logger.info(f"信号已记录 | {payload.symbol} | {payload.signal_type}")
        
        return {
            "status": "recorded",
            "signal_id": f"SIG_{int(time.time())}",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"信号记录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhooks/risk_check", tags=["风控"])
async def webhook_risk_check(
    request: RiskCheckRequest,
    x_webhook_signature: str = Header(None)
):
    """
    Webhook: 风控检查接口
    
    在下单前检查订单是否通过风控
    
    **请求示例:**
    ```json
    {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": 0.5,
        "price": 50000
    }
    ```
    """
    try:
        risk_manager = get_risk_manager()
        
        from src.risk import OrderRequest as RiskOrderRequest
        order_req = RiskOrderRequest(
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            price=request.price
        )
        
        result = risk_manager.check_order(order_req)
        
        return {
            "status": "checked",
            "approved": result.approved,
            "risk_level": result.risk_level.value,
            "message": result.message,
            "warnings": result.warnings,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"风控检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/webhooks/account", tags=["账户"])
async def webhook_account(
    account_id: int = 1,
    x_webhook_signature: str = Header(None)
):
    """
    Webhook: 账户查询接口
    
    查询账户余额、持仓、风险指标
    """
    try:
        simulator = get_simulator()
        
        return {
            "account": simulator.account.to_dict(),
            "positions": simulator.get_positions(),
            "risk_report": simulator.risk_manager.get_risk_report(account_id),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"账户查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/webhooks/positions", tags=["持仓"])
async def webhook_positions(
    account_id: int = 1,
    x_webhook_signature: str = Header(None)
):
    """Webhook: 持仓查询接口"""
    try:
        simulator = get_simulator()
        positions = simulator.get_positions()
        
        return {
            "count": len(positions),
            "positions": positions,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"持仓查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/webhooks/orders", tags=["订单"])
async def webhook_orders(
    limit: int = 20,
    account_id: int = 1,
    x_webhook_signature: str = Header(None)
):
    """Webhook: 订单历史查询接口"""
    try:
        simulator = get_simulator()
        orders = simulator.get_order_history(limit)
        
        return {
            "count": len(orders),
            "orders": orders,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"订单查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================
# 健康检查
@app.get("/webhooks/price/{symbol}", tags=["市场"])
async def webhook_price(symbol: str, asset_class: str = "auto"):
    """Webhook: 获取代币价格 (多源交叉验证)"""
    raw_symbol = symbol.strip()
    symbol = raw_symbol.upper()
    base_symbol = symbol.replace("USDT", "").replace("USD", "")
    resolved_asset_class = infer_asset_class(symbol, asset_class)
    import requests as req
    
    # 检测合约地址
    is_contract = raw_symbol.lower().startswith("0x") or (len(raw_symbol) > 40 and not symbol.endswith("USDT"))
    prices = {}  # 多源价格收集
    sources_info = []
    
    # === 1. 合约地址模式 ===
    if is_contract:
        r = req.get(f"https://api.dexscreener.com/latest/dex/tokens/{raw_symbol}", timeout=12)
        if not r.ok:
            raise HTTPException(status_code=404, detail="DexScreener 请求失败")
        data = r.json()
        pairs = data.get("pairs", [])
        if not pairs:
            raise HTTPException(status_code=404, detail="未找到交易对")
        p = max(pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0))
        return {
            "symbol": p.get("baseToken", {}).get("symbol", symbol),
            "name": p.get("baseToken", {}).get("name", ""),
            "price": float(p.get("priceUsd", 0)),
            "change_24h": float(p.get("priceChange", {}).get("m24", 0)),
            "source": f"dexscreener_{p.get('chainId', 'unknown')}",
            "is_contract": True,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    # === 2. 普通代币 - 多源交叉验证 ===
    
    # 源1: CoinGecko (最可靠)
    cg_map = {
        # 主流币
        "BTC": "bitcoin", "BTCUSDT": "bitcoin",
        "ETH": "ethereum", "ETHUSDT": "ethereum",
        "BNB": "binancecoin", "BNBUSDT": "binancecoin",
        "SOL": "solana", "SOLUSDT": "solana",
        "XRP": "ripple", "XRPUSDT": "ripple",
        "ADA": "cardano", "ADAUSDT": "cardano",
        "AVAX": "avalanche-2", "AVAXUSDT": "avalanche-2",
        # 主流代币
        "DOGE": "dogecoin", "DOGEUSDT": "dogecoin",
        "DOT": "polkadot", "DOTUSDT": "polkadot",
        "LINK": "chainlink", "LINKUSDT": "chainlink",
        "MATIC": "matic-network", "MATICUSDT": "matic-network",
        "UNI": "uniswap", "UNIUSDT": "uniswap",
        "ARB": "arbitrum", "ARBUSDT": "arbitrum",
        "OP": "optimism", "OPUSDT": "optimism",
        # Meme 币
        "PEPE": "pepe", "PEPEUSDT": "pepe",
        "SHIB": "shiba-inu", "SHIBUSDT": "shiba-inu",
        "BONK": "bonk", "BONKUSDT": "bonk",
        # 其他热门
        "FIL": "filecoin", "FILUSDT": "filecoin",
        "ATOM": "cosmos", "ATOMUSDT": "cosmos",
        "LTC": "litecoin", "LTCUSDT": "litecoin",
        "APT": "aptos", "APTUSDT": "aptos",
        "INJ": "injective-protocol", "INJUSDT": "injective-protocol",
        "TIA": "celestia", "TIAUSDT": "celestia",
        "SUI": "sui", "SUIUSDT": "sui",
        "NEAR": "near", "NEARUSDT": "near"
    }
    # 辅助函数: 获取市场详细数据 (带备用方案)
    # 简单的内存缓存（避免重复请求导致 rate limit）
    _cache = getattr(webhook_price, '_cache', {})
    _cache_ttl = 60  # 缓存60秒
    _now = time.time()
    _price_cache_key = f"price_{symbol}"
    if _price_cache_key in _cache and _now - _cache[_price_cache_key].get("_timestamp", 0) < _cache_ttl:
        cached_result = _cache[_price_cache_key].copy()
        cached_result.pop("_timestamp", None)
        return cached_result
    
    def get_market_data(cg_id: str) -> dict:
        """从 CoinGecko 获取市场详细数据，支持多端点重试"""
        if not cg_id:
            return {}
        
        # 先尝试获取 change_24h（最可靠的方法）
        change_24h = 0
        try:
            simple_url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd&include_24hr_change=true"
            r_simple = req.get(simple_url, timeout=10)
            if r_simple.ok:
                d_simple = r_simple.json()
                if cg_id in d_simple:
                    change_24h = d_simple[cg_id].get("usd_24h_change", 0)
        except:
            pass
        
        # 方案1: 使用 /coins/{id} 端点
        try:
            url = f"https://api.coingecko.com/api/v3/coins/{cg_id}"
            params = {
                "localization": False,
                "tickers": False,
                "market_data": True,
                "community_data": False,
                "developer_data": False,
                "sparkline": False
            }
            r = req.get(url, params=params, timeout=15)
            if r.ok:
                data = r.json()
                m = data.get("market_data", {})
                market_cap = m.get("market_cap", {}).get("usd", 0)
                if market_cap and market_cap > 0:
                    return {
                        "market_cap": market_cap,
                        "market_cap_rank": data.get("market_cap_rank") or 0,
                        "total_volume": m.get("total_volume", {}).get("usd", 0),
                        "high_24h": m.get("high_24h", {}).get("usd", 0),
                        "low_24h": m.get("low_24h", {}).get("usd", 0),
                        "change_24h": data.get("price_change_percentage_24h") or m.get("price_change_percentage_24h") or change_24h,
                        "name": data.get("name", symbol),
                        "symbol": data.get("symbol", symbol).upper(),
                        "image": data.get("image", {}).get("large", "")
                    }
        except Exception as e:
            logger.debug(f"market方案1失败: {e}")
        
        # 方案2: 使用 /coins/markets 端点
        try:
            url2 = f"https://api.coingecko.com/api/v3/coins/markets"
            params2 = {
                "vs_currency": "usd",
                "ids": cg_id,
                "order": "market_cap_desc",
                "per_page": 1,
                "page": 1,
                "sparkline": False
            }
            r2 = req.get(url2, params=params2, timeout=15)
            if r2.ok:
                data2 = r2.json()
                if data2 and len(data2) > 0:
                    coin = data2[0]
                    market_cap = coin.get("market_cap") or 0
                    if market_cap > 0:
                        return {
                            "market_cap": market_cap,
                            "market_cap_rank": coin.get("market_cap_rank") or 0,
                            "total_volume": coin.get("total_volume") or 0,
                            "high_24h": coin.get("high_24h") or 0,
                            "low_24h": coin.get("low_24h") or 0,
                            "name": coin.get("name", symbol),
                            "symbol": coin.get("symbol", symbol).upper(),
                            "image": coin.get("image", "")
                        }
        except Exception as e:
            logger.debug(f"market方案2失败: {e}")
        
        # 如果所有方案都失败，返回 change_24h（至少保证有这个数据）
        if change_24h != 0:
            return {"change_24h": change_24h}
        return {}
    
    # 使用优化的价格获取模块
    if HAS_PRICE_FETCHER and resolved_asset_class != "us_equity":
        price_data = get_price_with_fallback(base_symbol)
        market_data = get_market_data_with_fallback(base_symbol)
        
        if price_data and price_data.get('price', 0) > 0:
            # 优先使用 market_data，否则使用 price_data 中的数据
            market_cap = market_data.get('market_cap', 0) or price_data.get('market_cap', 0)
            return {
                "symbol": base_symbol,
                "price": price_data.get("price", 0),
                "change_24h": price_data.get("change_24h", 0),
                "price_usd": price_data.get("price", 0),
                "source": price_data.get("source", "unknown"),
                "is_contract": False,
                "market_cap": market_cap,
                "market_cap_rank": market_data.get('market_cap_rank', 0) or price_data.get('rank', 0),
                "total_volume": market_data.get("total_volume", 0),
                "high_24h": market_data.get("high_24h", 0),
                "low_24h": market_data.get("low_24h", 0),
                "name": market_data.get("name", symbol),
                "image": market_data.get("image", ""),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    cg_id = cg_map.get(symbol.upper())
    
    # 简单的内存缓存（避免 rate limit）
    _cg_cache = getattr(webhook_price, '_cg_cache', {})
    _cg_ttl = 30  # 缓存30秒
    
    # 获取市场详细数据 (市值、成交量等)
    market_data = {}
    if cg_id:
        cache_key = f"{cg_id}_data"
        if cache_key in _cg_cache and time.time() - _cg_cache[cache_key][1] < _cg_ttl:
            market_data = _cg_cache[cache_key][0]
        else:
            market_data = get_market_data(cg_id) if cg_id else {}
            if market_data:
                _cg_cache[cache_key] = (market_data, time.time())
        
        # 尝试获取价格和24h变化
        price_cache_key = f"{cg_id}_price"
        if price_cache_key in _cg_cache and time.time() - _cg_cache[price_cache_key][1] < _cg_ttl:
            cached_price = _cg_cache[price_cache_key][0]
            if cached_price:
                prices["coingecko"] = cached_price["price"]
                sources_info.append({"source": "coingecko", "price": cached_price["price"], "change_24h": cached_price["change"]})
        else:
            try:
                r = req.get(f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd&include_24hr_change=true", timeout=10)
                if r.ok:
                    d = r.json()
                    if cg_id in d:
                        p = d[cg_id]["usd"]
                        c = d[cg_id].get("usd_24h_change", 0)
                        prices["coingecko"] = p
                        sources_info.append({"source": "coingecko", "price": p, "change_24h": c})
                        _cg_cache[price_cache_key] = ({"price": p, "change": c}, time.time())
                        # 更新 market_data 的 change_24h
                        if not market_data.get("change_24h"):
                            market_data["change_24h"] = c
            except Exception as e:
                logger.debug(f"CoinGecko simple price 失败: {e}")
        
        # 更新缓存
        webhook_price._cg_cache = _cg_cache
    
    # 源2: Yahoo Finance
    yf_map = {
        "BTC": "BTC-USD", "BTCUSDT": "BTC-USD",
        "ETH": "ETH-USD", "ETHUSDT": "ETH-USD",
        "SOL": "SOL-USD", "SOLUSDT": "SOL-USD",
        "DOGE": "DOGE-USD", "DOGEUSDT": "DOGE-USD",
        "ADA": "ADA-USD", "ADAUSDT": "ADA-USD",
        "XRP": "XRP-USD", "XRPUSDT": "XRP-USD",
        "DOT": "DOT-USD", "DOTUSDT": "DOT-USD",
        "AVAX": "AVAX-USD", "AVAXUSDT": "AVAX-USD",
        "LINK": "LINK-USD", "LINKUSDT": "LINK-USD",
        "MATIC": "MATIC-USD", "MATICUSDT": "MATIC-USD",
        "UNI": "UNI-USD", "UNIUSDT": "UNI-USD",
        "LTC": "LTC-USD", "LTCUSDT": "LTC-USD",
        "ATOM": "ATOM-USD", "ATOMUSDT": "ATOM-USD",
        "FIL": "FIL-USD", "FILUSDT": "FIL-USD",
        "APT": "APT-USD", "APTUSDT": "APT-USD"
    }
    if symbol.upper() in yf_map:
        try:
            ticker = yf_map[symbol.upper()]
            r = req.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d", timeout=10)
            if r.ok:
                d = r.json()
                result = d.get("chart", {}).get("result", [])
                if result:
                    p = result[0]["meta"]["regularMarketPrice"]
                    c = result[0]["meta"].get("regularMarketChangePercent", 0)
                    prices["yahoo"] = p
                    sources_info.append({"source": "yahoo", "price": p, "change_24h": c})
        except Exception as e:
            logger.debug(f"Yahoo 失败: {e}")
    elif resolved_asset_class == "us_equity":
        try:
            r = req.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d", timeout=10)
            if r.ok:
                d = r.json()
                result = d.get("chart", {}).get("result", [])
                if result:
                    meta = result[0].get("meta", {})
                    quote = result[0].get("indicators", {}).get("quote", [{}])[0]
                    closes = [v for v in quote.get("close", []) if v is not None]
                    highs = [v for v in quote.get("high", []) if v is not None]
                    lows = [v for v in quote.get("low", []) if v is not None]
                    volumes = [v for v in quote.get("volume", []) if v is not None]
                    p = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
                    if p:
                        previous_close = meta.get("previousClose") or meta.get("chartPreviousClose")
                        if not previous_close and len(closes) >= 2:
                            previous_close = closes[-2]
                        previous_close = previous_close or p
                        c = ((p - previous_close) / previous_close * 100) if previous_close else 0
                        prices["yahoo"] = float(p)
                        market_data.update({
                            "name": meta.get("longName") or meta.get("shortName") or symbol,
                            "symbol": symbol,
                            "total_volume": meta.get("regularMarketVolume", 0) or (volumes[-1] if volumes else 0),
                            "high_24h": meta.get("regularMarketDayHigh", 0) or (highs[-1] if highs else 0),
                            "low_24h": meta.get("regularMarketDayLow", 0) or (lows[-1] if lows else 0),
                            "change_24h": c,
                        })
                        sources_info.append({"source": "yahoo_equity", "price": float(p), "change_24h": c})
        except Exception as e:
            logger.debug(f"Yahoo equity 失败: {e}")
        
        if not prices:
            rows = fetch_yahoo_history(symbol, "1d", 30)
            if rows:
                last = rows[-1]
                previous = rows[-2] if len(rows) >= 2 else last
                p = float(last["close"])
                previous_close = float(previous["close"]) or p
                c = ((p - previous_close) / previous_close * 100) if previous_close else 0
                prices["yahoo"] = p
                market_data.update({
                    "name": symbol,
                    "symbol": symbol,
                    "total_volume": last.get("volume", 0) or 0,
                    "high_24h": last.get("high", 0) or 0,
                    "low_24h": last.get("low", 0) or 0,
                    "change_24h": c,
                })
                sources_info.append({"source": "yahoo_equity_history", "price": p, "change_24h": c})
        
        if not prices:
            raise HTTPException(status_code=404, detail="Yahoo Finance 美股数据不可用")
        
        result = {
            "symbol": symbol,
            "price": round(prices["yahoo"], 6),
            "change_24h": round(market_data.get("change_24h", 0), 2),
            "price_usd": round(prices["yahoo"], 6),
            "price_diff_pct": 0,
            "is_consistent": True,
            "sources": sources_info,
            "source": "yahoo_finance",
            "is_contract": False,
            "market_cap": market_data.get("market_cap", 0),
            "market_cap_rank": market_data.get("market_cap_rank", 0),
            "total_volume": market_data.get("total_volume", 0),
            "high_24h": market_data.get("high_24h", 0),
            "low_24h": market_data.get("low_24h", 0),
            "name": market_data.get("name", symbol),
            "image": "",
            "timestamp": datetime.utcnow().isoformat()
        }
        _cache[_price_cache_key] = result.copy()
        _cache[_price_cache_key]["_timestamp"] = _now
        webhook_price._cache = _cache
        return result
    
    # 源3: DexScreener 搜索 (带价格合理性过滤)
    try:
        r = req.get(f"https://api.dexscreener.com/latest/dex/search?q={symbol.replace('USDT','')}", timeout=10)
        if r.ok:
            d = r.json()
            pairs = d.get("pairs", [])
            if pairs:
                # 过滤掉流动性太低或价格异常的交易对
                # 优先选择与代币名称匹配的链
                chain_priority = {
                    'ethereum': 1, 'bsc': 2, 'solana': 3, 'base': 4, 'polygon': 5
                }
                valid_pairs = [p for p in pairs if float(p.get("liquidity", {}).get("usd") or 0) > 10000]
                if valid_pairs:
                    # 按链优先级和流动性排序
                    def pair_priority(p):
                        chain = p.get('chainId', '').lower()
                        return (chain_priority.get(chain, 99), -float(p.get("liquidity", {}).get("usd", 0) or 0))
                    
                    valid_pairs.sort(key=pair_priority)
                    p = valid_pairs[0]
                    price = float(p.get("priceUsd", 0))
                    # 价格合理性检查 - 使用已有价格的中位数作为参考
                    if prices:
                        avg = sum(prices.values()) / len(prices)
                        if 0.5 < price / avg < 2:  # 价格偏差不超过50%
                            prices["dexscreener"] = price
                            sources_info.append({
                                "source": f"dexscreener_{p.get('chainId', 'unknown')}",
                                "price": price,
                                "change_24h": float(p.get("priceChange", {}).get("m24", 0))
                            })
    except Exception as e:
        logger.debug(f"DexScreener 失败: {e}")
    
    # 源4: Coinbase
    cb_map = {
        "BTC": "BTC", "BTCUSDT": "BTC",
        "ETH": "ETH", "ETHUSDT": "ETH",
        "SOL": "SOL", "SOLUSDT": "SOL",
        "DOGE": "DOGE", "DOGEUSDT": "DOGE",
        "ADA": "ADA", "ADAUSDT": "ADA",
        "XRP": "XRP", "XRPUSDT": "XRP",
        "DOT": "DOT", "DOTUSDT": "DOT",
        "AVAX": "AVAX", "AVAXUSDT": "AVAX",
        "LINK": "LINK", "LINKUSDT": "LINK",
        "MATIC": "MATIC", "MATICUSDT": "MATIC",
        "UNI": "UNI", "UNIUSDT": "UNI",
        "LTC": "LTC", "LTCUSDT": "LTC",
        "ATOM": "ATOM", "ATOMUSDT": "ATOM",
        "FIL": "FIL", "FILUSDT": "FIL",
        "APT": "APT", "APTUSDT": "APT"
    }
    if symbol.upper() in cb_map:
        try:
            ticker = cb_map[symbol.upper()]
            r = req.get(f"https://api.coinbase.com/v2/prices/{ticker}-USD/spot", timeout=10)
            if r.ok:
                p = float(r.json()["data"]["amount"])
                prices["coinbase"] = p
                sources_info.append({"source": "coinbase", "price": p})
        except Exception as e:
            logger.debug(f"Coinbase 失败: {e}")
    
    # 源5: DexScreener 通用搜索 (所有代币的最后后备)
    if not prices:
        try:
            search_url = f"https://api.dexscreener.com/latest/dex/search?q={symbol.replace('USDT','').replace('USD','')}"
            r = req.get(search_url, timeout=10)
            if r.ok:
                d = r.json()
                pairs = d.get("pairs", [])
                if pairs:
                    valid_pairs = [p for p in pairs if float(p.get("liquidity", {}).get("usd", 0) or 0) > 10000]
                    if valid_pairs:
                        valid_pairs.sort(key=lambda p: (-float(p.get("liquidity", {}).get("usd", 0) or 0), p.get('chainId', '')))
                        p = valid_pairs[0]
                        price = float(p.get("priceUsd", 0))
                        if price > 0:
                            prices["dexscreener"] = price
                            sources_info.append({
                                "source": f"dexscreener_{p.get('chainId', 'unknown')}",
                                "price": price,
                                "change_24h": float(p.get("priceChange", {}).get("m24", 0))
                            })
        except Exception as e:
            logger.debug(f"DexScreener 搜索失败: {e}")
    
    # 计算加权平均价格
    if not prices:
        raise HTTPException(status_code=404, detail=f"所有数据源均不可用")
    
    # 权重: CoinGecko > Yahoo > Coinbase > DexScreener
    weights = {"coingecko": 0.4, "yahoo": 0.3, "coinbase": 0.2, "dexscreener": 0.1}
    total_weight = 0
    weighted_price = 0
    for src, price in prices.items():
        w = weights.get(src, 0.1)
        weighted_price += price * w
        total_weight += w
    
    final_price = weighted_price / total_weight if total_weight > 0 else list(prices.values())[0]
    avg_price = sum(prices.values()) / len(prices)
    
    # 验证数据一致性
    max_diff = max(prices.values()) - min(prices.values())
    diff_pct = max_diff / avg_price * 100 if avg_price > 0 else 0
    is_consistent = diff_pct < 1.0  # 误差 < 1%
    
    # 使用 CoinGecko 或 Yahoo 作为主价格
    main_price = prices.get("coingecko") or prices.get("yahoo") or prices.get("coinbase") or final_price
    main_change = 0
    
    # 从 sources_info 获取 change_24h（优先使用 CoinGecko/Yahoo，然后是 DexScreener）
    for s in sources_info:
        change_val = s.get("change_24h", 0)
        if change_val is not None:
            main_change = change_val
            break
    
    # 如果没有 change_24h，从 market_data 获取
    if main_change is None and market_data:
        main_change = market_data.get("change_24h", 0)
    
    # 如果仍然没有 change_24h，设置为 0（表示数据不可用）
    if main_change is None:
        main_change = 0
    
    # 备用1: 从 Yahoo Finance 获取 change_24h
    if main_change == 0 and symbol.upper() in yf_map:
        try:
            ticker = yf_map[symbol.upper()]
            r = req.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d", timeout=10)
            if r.ok:
                d = r.json()
                result = d.get("chart", {}).get("result", [])
                if result:
                    main_change = result[0]["meta"].get("regularMarketChangePercent", 0)
        except:
            pass
    
    # 备用2: 从 DexScreener 获取 change_24h
    if main_change == 0:
        try:
            search_url = f"https://api.dexscreener.com/latest/dex/search?q={symbol.replace('USDT','').replace('USD','')}"
            r = req.get(search_url, timeout=10)
            if r.ok:
                d = r.json()
                pairs = d.get("pairs", [])
                if pairs:
                    # 找到流动性最高的交易对
                    valid_pairs = [p for p in pairs if float(p.get("liquidity", {}).get("usd", 0) or 0) > 10000]
                    if valid_pairs:
                        best = max(valid_pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0))
                        change = float(best.get("priceChange", {}).get("m24", 0) or 0)
                        if change != 0:
                            main_change = change
        except:
            pass
    
    # 辅助函数: 获取市场详细数据 (带备用方案)

    
    # 构建返回数据
    result = {
        "symbol": symbol.replace("USDT", ""),
        "price": round(main_price, 6) if main_price else round(final_price, 6),
        "change_24h": round(main_change, 2),
        "price_usd": round(final_price, 6),
        "price_diff_pct": round(diff_pct, 3),
        "is_consistent": is_consistent,
        "sources": sources_info,
        "source": "multi_source_cross_validation",
        "is_contract": False,
        "market_cap": market_data.get("market_cap", 0),
        "market_cap_rank": market_data.get("market_cap_rank", 0),
        "total_volume": market_data.get("total_volume", 0),
        "high_24h": market_data.get("high_24h", 0),
        "low_24h": market_data.get("low_24h", 0),
        "name": market_data.get("name", symbol),
        "image": market_data.get("image", ""),
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # 缓存结果
    _cache[_price_cache_key] = result.copy()
    _cache[_price_cache_key]["_timestamp"] = _now
    webhook_price._cache = _cache
    
    return result


@app.get("/webhooks/history/{symbol}", tags=["市场"])
async def webhook_history(symbol: str, interval: str = "1d", limit: int = 365):
    """Webhook: 获取交易对历史 K 线数据。"""
    allowed_intervals = {"1h", "1d", "1w", "1M"}
    if interval not in allowed_intervals:
        raise HTTPException(status_code=400, detail="interval 仅支持 1h、1d、1w、1M")
    
    limit = max(1, min(limit, 1000))
    normalized_symbol = symbol.upper()
    
    try:
        from src.collector import DataCollector
        
        collector = DataCollector()
        data = []
        validation = None
        
        # 尝试从 Binance 获取数据
        try:
            data, validation = collector.fetch_ohlc(
                symbol=normalized_symbol,
                interval=interval,
                limit=limit
            )
            if data:
                collector.save_ohlc_data(data)
        except Exception as e:
            logger.warning(f"Binance 获取 K 线失败: {e}")
        
        # 如果 Binance 没有数据，使用 Yahoo Finance
        if not data:
            yahoo_data = fetch_yahoo_history(normalized_symbol, interval, limit)
            if yahoo_data:
                return {
                    "symbol": normalized_symbol,
                    "interval": interval,
                    "count": len(yahoo_data),
                    "validation": {
                        "is_valid": True,
                        "quality": "good",
                        "score": 80,
                        "issues": [],
                        "warnings": ["Binance 不可用，已切换到 Yahoo Finance"]
                    },
                    "data": yahoo_data,
                    "source": "yahoo_finance",
                    "timestamp": datetime.utcnow().isoformat()
                }
            else:
                raise HTTPException(status_code=404, detail="所有数据源均不可用")
        
        return {
            "symbol": normalized_symbol,
            "interval": interval,
            "count": len(data),
            "validation": validation.to_dict() if validation else None,
            "data": [
                {
                    "time": item["open_time"].isoformat(),
                    "open": item["open_price"],
                    "high": item["high_price"],
                    "low": item["low_price"],
                    "close": item["close_price"],
                    "volume": item["volume"],
                }
                for item in data
            ],
            "source": "binance",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"历史K线查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def fetch_yahoo_history(symbol: str, interval: str, limit: int) -> List[Dict[str, float]]:
    """从 Yahoo Finance 获取历史 OHLC 作为 Binance 不可用时的备用源。"""
    import requests
    
    symbol_map = {
        "BTCUSDT": "BTC-USD",
        "ETHUSDT": "ETH-USD",
        "BNBUSDT": "BNB-USD",
        "SOLUSDT": "SOL-USD",
        "XRPUSDT": "XRP-USD",
        "ADAUSDT": "ADA-USD",
        "DOGEUSDT": "DOGE-USD",
        "DOTUSDT": "DOT-USD",
    }
    yahoo_symbol = symbol_map.get(symbol, symbol.replace("USDT", "-USD"))
    interval_map = {
        "1h": ("1h", "5d"),
        "1d": ("1d", "1y"),
        "1w": ("1wk", "5y"),
        "1M": ("1mo", "10y"),
    }
    yahoo_interval, range_value = interval_map[interval]
    
    try:
        response = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}",
            params={"interval": yahoo_interval, "range": range_value},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("chart", {}).get("result", [])
        if not result:
            return []
        
        chart = result[0]
        timestamps = chart.get("timestamp", [])
        quote = chart.get("indicators", {}).get("quote", [{}])[0]
        rows = []
        
        for index, timestamp in enumerate(timestamps):
            try:
                open_price = quote.get("open", [])[index]
                high_price = quote.get("high", [])[index]
                low_price = quote.get("low", [])[index]
                close_price = quote.get("close", [])[index]
                volume = quote.get("volume", [])[index]
                if None in (open_price, high_price, low_price, close_price):
                    continue
                if interval == "1h" and not volume:
                    continue
                
                rows.append({
                    "time": datetime.utcfromtimestamp(timestamp).isoformat(),
                    "open": float(open_price),
                    "high": float(high_price),
                    "low": float(low_price),
                    "close": float(close_price),
                    "volume": float(volume or 0),
                })
            except (IndexError, TypeError, ValueError):
                continue
        
        return rows[-limit:]
    except Exception as e:
        logger.warning(f"Yahoo Finance 历史数据失败: {e}")
        return []


async def load_history_rows(symbol: str, interval: str, limit: int) -> Dict:
    """Load OHLC rows from Binance first, Yahoo Finance as fallback."""
    from src.collector import DataCollector
    
    normalized_symbol = symbol.upper()
    collector = DataCollector()
    data = []
    validation = None
    
    try:
        data, validation = collector.fetch_ohlc(
            symbol=normalized_symbol,
            interval=interval,
            limit=limit
        )
        if data:
            collector.save_ohlc_data(data)
            return {
                "symbol": normalized_symbol,
                "interval": interval,
                "count": len(data),
                "validation": validation.to_dict() if validation else None,
                "data": [
                    {
                        "time": item["open_time"].isoformat(),
                        "open": item["open_price"],
                        "high": item["high_price"],
                        "low": item["low_price"],
                        "close": item["close_price"],
                        "volume": item["volume"],
                    }
                    for item in data
                ],
                "source": "binance",
                "timestamp": datetime.utcnow().isoformat()
            }
    except Exception as e:
        logger.warning(f"Binance 获取 K 线失败: {e}")
    
    yahoo_data = fetch_yahoo_history(normalized_symbol, interval, limit)
    if not yahoo_data:
        raise HTTPException(status_code=404, detail="所有数据源均不可用")
    
    return {
        "symbol": normalized_symbol,
        "interval": interval,
        "count": len(yahoo_data),
        "validation": {
            "is_valid": True,
            "quality": "good",
            "score": 80,
            "issues": [],
            "warnings": ["Binance 不可用，已切换到 Yahoo Finance"]
        },
        "data": yahoo_data,
        "source": "yahoo_finance",
        "timestamp": datetime.utcnow().isoformat()
    }


def infer_asset_class(symbol: str, asset_class: str) -> str:
    """Infer asset class when caller passes auto."""
    requested = (asset_class or "auto").lower()
    if requested in {"crypto", "us_equity"}:
        return requested
    crypto_symbols = {
        "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "DOT",
        "AVAX", "LINK", "MATIC", "UNI", "LTC", "ATOM", "FIL",
        "APT", "ARB", "OP", "PEPE", "SHIB", "BONK", "NEAR"
    }
    normalized = symbol.upper().replace("USDT", "").replace("USD", "")
    return "crypto" if symbol.upper().endswith("USDT") or normalized in crypto_symbols else "us_equity"


@app.get("/webhooks/strategy_signal/{symbol}", tags=["策略"])
async def webhook_strategy_signal(
    symbol: str,
    asset_class: str = "auto",
    interval: str = "1d",
    limit: int = 260
):
    """Webhook: 多资产高端策略信号，支持加密货币和美股。"""
    allowed_intervals = {"1h", "1d", "1w", "1M"}
    if interval not in allowed_intervals:
        raise HTTPException(status_code=400, detail="interval 仅支持 1h、1d、1w、1M")
    
    resolved_asset_class = infer_asset_class(symbol, asset_class)
    normalized_symbol = symbol.upper()
    if resolved_asset_class == "crypto" and not normalized_symbol.endswith("USDT"):
        normalized_symbol = f"{normalized_symbol.replace('USD', '')}USDT"
    
    history = await load_history_rows(normalized_symbol, interval, max(120, min(limit, 1000)))
    
    from src.strategy_engine import MultiAssetStrategyEngine
    
    engine = MultiAssetStrategyEngine()
    signal = engine.generate_signal(
        history["data"],
        symbol=normalized_symbol,
        asset_class=resolved_asset_class,
        interval=interval
    )
    signal["data_source"] = history["source"]
    signal["bars"] = history["count"]
    signal["timestamp"] = datetime.utcnow().isoformat()
    return signal


# =====================================================

@app.get("/health", tags=["系统"])
async def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "service": "cc-invest-webhook",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/metrics", tags=["系统"])
async def metrics():
    """指标接口"""
    simulator = get_simulator()
    risk_manager = get_risk_manager()
    
    return {
        "account": {
            "balance": simulator.account.balance,
            "total_trades": simulator.account.total_trades,
            "win_rate": simulator.account.winning_trades / simulator.account.total_trades if simulator.account.total_trades > 0 else 0
        },
        "risk": risk_manager.get_risk_report(),
        "timestamp": datetime.utcnow().isoformat()
    }

# =====================================================
# OpenClaw 集成路由
# =====================================================

@app.post("/agent/analysis", tags=["OpenClaw"])
async def agent_analysis(
    symbol: str,
    timeframe: str = "1h",
    x_webhook_signature: str = Header(None)
):
    """
    OpenClaw 集成: 技术分析
    
    触发 OpenClaw 执行技术分析技能
    """
    try:
        from src.collector import DataCollector
        collector = DataCollector()
        
        indicators = collector.compute_indicators(symbol, timeframe)
        
        return {
            "status": "completed",
            "symbol": symbol,
            "timeframe": timeframe,
            "indicators": indicators.to_dict() if not indicators.empty else {},
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"分析失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/agent/backtest", tags=["OpenClaw"])
async def agent_backtest(
    symbol: str = "BTCUSDT",
    strategy: str = "mean_reversion",
    start_date: str = "2023-01-01",
    end_date: str = "2024-01-01",
    x_webhook_signature: str = Header(None)
):
    """
    OpenClaw 集成: 回测请求
    
    触发 OpenClaw 执行回测
    """
    try:
        from src.backtest import BacktestEngine
        engine = BacktestEngine()
        
        result = engine.run_backtrader_backtest(
            symbol=symbol,
            strategy_name=strategy,
            start_date=start_date,
            end_date=end_date
        )
        
        report = engine.generate_report(result)
        
        return {
            "status": "completed",
            "report": report,
            "metrics": {
                "total_return": result.total_return,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"回测失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================
# 错误处理
# =====================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局错误处理"""
    logger.error(f"未处理异常: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": str(exc),
            "path": str(request.url)
        }
    )

# =====================================================
# 主程序
# =====================================================

if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.getenv("WEBHOOK_PORT", "10000"))
    
    logger.info(f"启动 Webhook 服务 | {host}:{port}")
    
    uvicorn.run(
        "webhook_server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )
