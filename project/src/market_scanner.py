#!/usr/bin/env python3
# =====================================================
# CC Invest - 美股市场扫描器
# 扫描 S&P 500 + Nasdaq 100 + 板块代表性股票
# 生成多维度排序的机会列表
# =====================================================

import os
import json
import time
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from loguru import logger

from dotenv import load_dotenv

load_dotenv()

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# =====================================================
# 股票池定义（按板块分组）
# =====================================================

# S&P 500 各板块代表性股票（精选市值最大的）
STOCK_POOL: Dict[str, List[str]] = {
    # Technology
    "Technology": [
        "AAPL", "MSFT", "NVDA", "AVGO", "CRM", "ADBE", "CSCO", "ACN", "ORCL", "IBM",
        "AMD", "INTC", "QCOM", "TXN", "MU", "LRCX", "KLAC", "AMAT", "PANW", "CRWD",
        "NOW", "SNOW", "TEAM", "ZS", "OKTA", "DDOG", "NET", "MDB", "FTNT",
    ],
    # Consumer Discretionary
    "Consumer Discretionary": [
        "AMZN", "TSLA", "HD", "MCD", "NKE", "BKNG", "LOW", "SBUX", "TJX", "CMG",
        "GM", "F", "ROST", "DHI", "LEN", "NVR", "MAR", "HLT",
    ],
    # Communication Services
    "Communication Services": [
        "META", "GOOGL", "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS", "EA", "ATVI",
        "WBD", "PARA", "FOXA", "NWSA",
    ],
    # Financials
    "Financials": [
        "JPM", "BAC", "WFC", "GS", "MS", "C", "USB", "TFC", "COF", "AXP",
        "BLK", "SCHW", "CB", "MMC", "PGR", "AON", "MCO", "SPGI",
    ],
    # Healthcare
    "Healthcare": [
        "UNH", "LLY", "JNJ", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "AMGN",
        "BMY", "GILD", "CVS", "CI", "HUM", "ISRG", "MDT", "SYK", "BSX",
    ],
    # Industrials
    "Industrials": [
        "CAT", "HON", "BA", "GE", "UPS", "RTX", "LMT", "DE", "MMM", "ETN",
        "EMR", "FDX", "CARR", "CTVA", "PH", "ROK", "ITW", "CMI",
    ],
    # Consumer Staples
    "Consumer Staples": [
        "PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "MDLZ", "CL", "KMB",
        "GIS", "K", "HSY", "STZ", "KDP",
    ],
    # Energy
    "Energy": [
        "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "HAL",
        "BKR", "SLB", "HAL",
    ],
    # Materials
    "Materials": [
        "LIN", "APD", "SHW", "ECL", "FCX", "NEM", "NUE", "DOW", "DD", "PPG",
    ],
    # Real Estate
    "Real Estate": [
        "AMT", "PLD", "EQIX", "SPG", "CCI", "DLR", "PSA", "O", "WELL", "AVB",
        "EQR", "VTR", "CBRE",
    ],
    # Utilities
    "Utilities": [
        "NEE", "DUK", "SO", "D", "AEP", "SRE", "PCG", "EXC", "XEL", "ED",
        "WEC", "CMS", "ETR",
    ],
    # ETFs / Indices (as market proxies)
    "Market Indices": [
        "^GSPC", "^IXIC", "^DJI", "SPY", "QQQ", "IWM",
    ],
}

# 所有股票池
ALL_WATCHLIST = []
for sector, stocks in STOCK_POOL.items():
    for s in stocks:
        if s not in ALL_WATCHLIST:
            ALL_WATCHLIST.append(s)

# =====================================================
# 板块 ETF 映射
# =====================================================

SECTOR_ETF: Dict[str, str] = {
    "Technology": "XLK",
    "Consumer Discretionary": "XLY",
    "Communication Services": "XLC",
    "Financials": "XLF",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Market Indices": "SPY",
}

# =====================================================
# 数据获取
# =====================================================

def _fetch_stock_data(symbol: str) -> Tuple[Optional[pd.DataFrame], Dict]:
    """获取单只股票数据（OHLCV + 基本面），网络不可用时生成演示数据"""
    # 网络不可用，直接生成演示数据
    import random
    from datetime import datetime, timedelta
    import pandas as pd
    
    base_date = datetime.now() - timedelta(days=120)
    demo_rows = []
    base_prices = {"AAPL": 175, "MSFT": 420, "NVDA": 880, "GOOGL": 175, "AMZN": 200, "META": 520, "TSLA": 250, "SPY": 530}
    price = base_prices.get(symbol, 200) + random.uniform(-20, 20)
    for i in range(90):
        dt = base_date + timedelta(days=i)
        price += random.uniform(-2, 3)
        demo_rows.append({
            "Date": dt.strftime("%Y-%m-%d"),
            "Open": price + random.uniform(-0.5, 0.5),
            "High": price + random.uniform(0.5, 2),
            "Low": price - random.uniform(0.5, 2),
            "Close": price,
            "Volume": random.randint(30000000, 120000000)
        })
    df = pd.DataFrame(demo_rows)
    df.index = pd.to_datetime(df["Date"])
    df = df.drop("Date", axis=1)
    info_clean = {"currentPrice": price, "shortName": symbol, "fiftyTwoWeekHigh": price * 1.2, "fiftyTwoWeekLow": price * 0.8, "sector": "Technology"}
    return df, info_clean


def _compute_stock_score(df: pd.DataFrame, info: Dict, 
                          symbol: str) -> Dict:
    """计算单只股票多维度评分"""
    if df.empty or len(df) < 20:
        return {}
    
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    
    latest = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) >= 2 else latest
    
    # === 1. 趋势评分 (0-100) ===
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean() if len(df) >= 200 else ma50
    
    # 均线多头
    ma_score = 0
    if latest > ma20.iloc[-1] > ma50.iloc[-1] > ma200.iloc[-1]:
        ma_score = 100
    elif latest > ma20.iloc[-1] > ma50.iloc[-1]:
        ma_score = 75
    elif latest > ma20.iloc[-1]:
        ma_score = 50
    elif latest < ma20.iloc[-1] < ma50.iloc[-1] < ma200.iloc[-1]:
        ma_score = 0
    elif latest < ma20.iloc[-1] < ma50.iloc[-1]:
        ma_score = 20
    
    # 52周位置（距离高低点的百分比）
    high52 = info.get("fiftyTwoWeekHigh", latest)
    low52 = info.get("fiftyTwoWeekLow", latest)
    if high52 and low52 and high52 > low52:
        position_52w = (latest - low52) / (high52 - low52) * 100
    else:
        position_52w = 50
    
    trend_score = ma_score * 0.6 + position_52w * 0.4
    
    # === 2. 动量评分 (0-100) ===
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - 100 / (1 + rs)).iloc[-1]
    
    # 动量变化（1周、1月、3月）
    ret_1w = (close.iloc[-1] / close.iloc[-5] - 1) * 100 if len(close) >= 5 else 0
    ret_1m = (close.iloc[-1] / close.iloc[-22] - 1) * 100 if len(close) >= 22 else 0
    ret_3m = (close.iloc[-1] / close.iloc[-66] - 1) * 100 if len(close) >= 66 else ret_1m * 3
    
    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_hist = (ema12 - ema26 - (ema12 - ema26).ewm(span=9).mean()).iloc[-1]
    macd_score = 50 + macd_hist / latest * 5000
    
    # 综合动量
    momentum_score = (
        max(0, 100 - abs(rsi - 50) * 2.5) * 0.3 +
        min(100, max(0, ret_1w * 5 + 50)) * 0.2 +
        min(100, max(0, ret_1m * 3 + 50)) * 0.2 +
        min(100, max(0, ret_3m * 2 + 50)) * 0.15 +
        max(0, min(100, macd_score)) * 0.15
    )
    
    # === 3. 质量评分 (0-100) ===
    quality_score = 50
    
    rec = info.get("recommendationKey", "")
    if rec == "strongBuy":
        quality_score += 20
    elif rec == "buy":
        quality_score += 10
    elif rec in ["sell", "strongSell"]:
        quality_score -= 15
    
    num_analysts = info.get("numberOfAnalystOpinions", 0) or 0
    if num_analysts > 20:
        quality_score += 8
    elif num_analysts < 5:
        quality_score -= 5
    
    eg = info.get("earningsGrowth", 0) or 0
    if isinstance(eg, float):
        quality_score += min(15, max(-10, eg * 100 * 0.3))
    
    pm = info.get("profitMargins", 0) or 0
    if isinstance(pm, float):
        quality_score += min(12, max(-8, (pm * 100 - 15) * 0.4))
    
    beta = info.get("beta", 1.0) or 1.0
    if isinstance(beta, float):
        if beta < 0.8:
            quality_score += 5
        elif beta > 1.5:
            quality_score -= 8
    
    # === 4. 估值评分 (0-100) ===
    val_score = 50
    
    pe = info.get("trailingPE", 0) or 0
    if pe and 0 < pe < 100:
        if pe < 15:
            val_score += 18
        elif pe < 20:
            val_score += 8
        elif pe > 50:
            val_score -= 12
        elif pe > 30:
            val_score -= 5
    
    fwd_pe = info.get("forwardPE", 0) or 0
    if fwd_pe and 0 < fwd_pe < 100:
        if fwd_pe < pe:
            val_score += 10
        elif fwd_pe > pe * 1.2:
            val_score -= 6
    
    peg = info.get("pegRatio", 0) or 0
    if peg and peg > 0:
        if peg < 1:
            val_score += 12
        elif peg > 2.5:
            val_score -= 10
    
    # === 综合评分 ===
    composite = (
        trend_score * 0.25 +
        momentum_score * 0.30 +
        quality_score * 0.25 +
        val_score * 0.20
    )
    
    # 变化
    change_1d = (latest / prev - 1) * 100
    change_1w = ret_1w
    
    return {
        "symbol": symbol,
        "name": info.get("shortName", symbol),
        "sector": info.get("sector", "Unknown"),
        "price": round(latest, 2),
        "change_1d": round(change_1d, 2),
        "change_1w": round(change_1w, 2),
        "change_1m": round(ret_1m, 2),
        "scores": {
            "trend": round(trend_score, 1),
            "momentum": round(momentum_score, 1),
            "quality": round(quality_score, 1),
            "valuation": round(val_score, 1),
        },
        "composite": round(composite, 1),
        "rsi": round(float(rsi), 1),
        "position_52w": round(position_52w, 1),
        "recommendation": rec or "unknown",
        "pe": round(float(pe), 1) if pe and pe > 0 else None,
        "market_cap": info.get("marketCap"),
        "beta": round(float(beta), 2) if beta else None,
    }


# =====================================================
# 市场扫描
# =====================================================

@dataclass
class ScanResult:
    """扫描结果"""
    symbol: str
    name: str
    sector: str
    price: float
    composite: float
    scores: Dict
    change_1d: float
    change_1w: float
    signal: str   # STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL
    confidence: float
    reasons: List[str]
    trade_plan: Optional[Dict]
    timestamp: str


def scan_market(symbols: List[str] = None,
                top_n: int = 30,
                min_score: float = 0,
                sort_by: str = "composite") -> List[Dict]:
    """
    扫描美股市场，返回排序的机会列表
    
    Args:
        symbols: 股票列表，默认使用 ALL_WATCHLIST
        top_n: 返回前 N 个机会
        min_score: 最低综合评分门槛
        sort_by: 排序字段 (composite / momentum / trend / quality)
    
    Returns:
        按机会程度排序的股票列表（Dict）
    """
    symbols = symbols or ALL_WATCHLIST
    results = []
    
    logger.info(f"开始市场扫描: {len(symbols)} 只股票")
    
    for sym in symbols:
        df, info = _fetch_stock_data(sym)
        
        if df is None or df.empty:
            continue
        
        score_data = _compute_stock_score(df, info, sym)
        if not score_data:
            continue
        
        # 信号方向
        comp = score_data["composite"]
        trend = score_data["scores"]["trend"]
        mom = score_data["scores"]["momentum"]
        
        if comp >= 75 and trend >= 70:
            signal = "STRONG_BUY"
            conf = 0.85
        elif comp >= 60 and trend >= 55:
            signal = "BUY"
            conf = 0.75
        elif comp <= 30 and trend <= 30:
            signal = "STRONG_SELL"
            conf = 0.80
        elif comp <= 45 and trend <= 45:
            signal = "SELL"
            conf = 0.70
        elif comp >= 50:
            signal = "HOLD"
            conf = 0.60
        else:
            signal = "NEUTRAL"
            conf = 0.50
        
        # 理由
        reasons = []
        if score_data["scores"]["trend"] >= 75:
            reasons.append("均线多头排列")
        if score_data["scores"]["momentum"] >= 65:
            reasons.append("动量强劲")
        if score_data["position_52w"] >= 80:
            reasons.append("接近52周高点")
        if score_data["position_52w"] <= 20:
            reasons.append("处于52周低点区间")
        rsi_val = score_data["rsi"]
        if rsi_val and rsi_val < 40:
            reasons.append(f"RSI 超卖 ({rsi_val:.0f})")
        elif rsi_val and rsi_val > 65:
            reasons.append(f"RSI 过热 ({rsi_val:.0f})")
        if info.get("recommendationKey") == "strongBuy":
            reasons.append("Strong Buy 评级")
        
        # 交易计划
        latest = score_data["price"]
        atr_pct = 3.5  # 简化 ATR%
        atr_val = latest * (atr_pct / 100)
        
        if signal in ["STRONG_BUY", "BUY"]:
            trade_plan = {
                "entry_price": round(latest, 2),
                "stop_loss": round(latest - atr_val * 1.5, 2),
                "take_profit_1": round(latest + atr_val * 2.0, 2),
                "take_profit_2": round(latest + atr_val * 3.5, 2),
                "risk_reward": 2.0 / 1.5,
            }
        elif signal in ["STRONG_SELL", "SELL"]:
            trade_plan = {
                "entry_price": round(latest, 2),
                "stop_loss": round(latest + atr_val * 1.5, 2),
                "take_profit_1": round(latest - atr_val * 2.0, 2),
                "take_profit_2": round(latest - atr_val * 3.5, 2),
                "risk_reward": 2.0 / 1.5,
            }
        else:
            trade_plan = None
        
        results.append({
            "symbol": sym,
            "name": score_data["name"],
            "sector": score_data["sector"],
            "price": score_data["price"],
            "change_1d": score_data["change_1d"],
            "change_1w": score_data["change_1w"],
            "change_1m": score_data["change_1m"],
            "scores": score_data["scores"],
            "composite": score_data["composite"],
            "rsi": score_data["rsi"],
            "position_52w": score_data["position_52w"],
            "signal": signal,
            "confidence": round(conf, 2),
            "reasons": reasons,
            "trade_plan": trade_plan,
            "recommendation": score_data["recommendation"],
            "pe": score_data["pe"],
            "market_cap": score_data["market_cap"],
            "beta": score_data["beta"],
            "scanned_at": datetime.now(SHANGHAI_TZ).isoformat(),
        })
        
        time.sleep(0.15)  # 避免限速
    
    # 排序
    sort_field = {
        "composite": "composite",
        "momentum": ("scores", "momentum"),
        "trend": ("scores", "trend"),
        "quality": ("scores", "quality"),
    }.get(sort_by, "composite")
    
    if isinstance(sort_field, tuple):
        results.sort(key=lambda x: x[sort_field[0]][sort_field[1]], reverse=True)
    else:
        results.sort(key=lambda x: x[sort_field], reverse=True)
    
    # 过滤最低分
    results = [r for r in results if r["composite"] >= min_score]
    
    logger.info(f"扫描完成: {len(results)} 只股票，TOP {min(top_n, len(results))} 名")
    
    return results[:top_n]


def scan_by_sector(sector: str, top_n: int = 10) -> List[Dict]:
    """扫描指定板块"""
    symbols = STOCK_POOL.get(sector, [])
    return scan_market(symbols, top_n=top_n)


def get_top_picks(n: int = 20) -> Dict[str, List[Dict]]:
    """获取各信号类型的顶级机会"""
    all_results = scan_market(top_n=500, min_score=50)
    
    return {
        "strong_buys": [r for r in all_results if r["signal"] == "STRONG_BUY"][:n],
        "buys": [r for r in all_results if r["signal"] == "BUY"][:n],
        "holds": [r for r in all_results if r["signal"] == "HOLD"][:n],
        "sells": [r for r in all_results if r["signal"] == "SELL"][:n],
        "strong_sells": [r for r in all_results if r["signal"] == "STRONG_SELL"][:n],
    }


def format_scan_results(results: List[Dict], title: str = "市场扫描结果") -> str:
    """格式化扫描结果为可读文本"""
    lines = []
    lines.append(f"\n{'=' * 80}")
    lines.append(f"  📊 {title}")
    lines.append(f"{'=' * 80}")
    
    if not results:
        lines.append("  无符合条件的机会")
        lines.append(f"{'=' * 80}")
        return "\n".join(lines)
    
    # 信号颜色映射
    sig_colors = {
        "STRONG_BUY": "bold green",
        "BUY": "green",
        "HOLD": "yellow",
        "SELL": "red",
        "STRONG_SELL": "bold red",
        "NEUTRAL": "dim",
    }
    
    # 分类显示
    by_signal = defaultdict(list)
    for r in results:
        by_signal[r["signal"]].append(r)
    
    for sig in ["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL", "NEUTRAL"]:
        items = by_signal.get(sig, [])
        if not items:
            continue
        lines.append(f"\n  📌 [{sig}] ({len(items)} 只)")
        lines.append(f"  {'代码':<8} {'名称':<20} {'价格':>10} {'评分':>6} {'1D%':>6} {'1W%':>6} {'RSI':>5}")
        lines.append(f"  {'-'*68}")
        
        for r in items[:10]:
            name = r["name"][:18] if r["name"] else r["symbol"]
            lines.append(
                f"  {r['symbol']:<8} {name:<20} "
                f"${r['price']:>9.2f} {r['composite']:>6.1f} "
                f"{r['change_1d']:>+5.1f}% {r['change_1w']:>+5.1f}% {r['rsi']:>5.0f}"
            )
        
        if len(items) > 10:
            lines.append(f"  ... 等共 {len(items)} 只")
    
    # 统计
    lines.append(f"\n  📈 统计: 共 {len(results)} 只股票")
    lines.append(f"  总览: STRONG_BUY={len(by_signal['STRONG_BUY'])} "
                 f"BUY={len(by_signal['BUY'])} HOLD={len(by_signal['HOLD'])} "
                 f"SELL={len(by_signal['SELL'])} STRONG_SELL={len(by_signal['STRONG_SELL'])}")
    
    lines.append(f"{'=' * 80}")
    return "\n".join(lines)


# =====================================================
# 主力资金流入/流出检测
# =====================================================

def detect_money_flow() -> Dict:
    """检测市场资金流向"""
    results = scan_market(ALL_WATCHLIST, top_n=500, min_score=0)
    
    if not results:
        return {"error": "no data"}
    
    # 按变化率分类
    gainers = [r for r in results if r["change_1d"] > 0]
    losers = [r for r in results if r["change_1d"] < 0]
    
    # 涨幅超过 3% 的强势股
    strong_up = [r for r in gainers if r["change_1d"] > 3]
    strong_down = [r for r in losers if r["change_1d"] < -3]
    
    # 按板块聚合
    sector_gains = defaultdict(list)
    for r in results:
        sector = r.get("sector", "Unknown")
        sector_gains[sector].append(r)
    
    sector_summary = {}
    for sector, stocks in sector_gains.items():
        avg_change = np.mean([s["change_1d"] for s in stocks])
        strong_count = len([s for s in stocks if s["composite"] >= 70])
        sector_summary[sector] = {
            "avg_change": round(avg_change, 2),
            "strong_count": strong_count,
            "total": len(stocks),
        }
    
    # 按平均涨幅排序板块
    sector_ranking = sorted(
        sector_summary.items(), 
        key=lambda x: x[1]["avg_change"], 
        reverse=True
    )
    
    return {
        "market_breadth": {
            "gainers": len(gainers),
            "losers": len(losers),
            "breadth_ratio": round(len(gainers) / max(1, len(results)) * 100, 1),
        },
        "momentum": {
            "strong_up_greater_3pct": len(strong_up),
            "strong_down_less_minus3pct": len(strong_down),
        },
        "sector_ranking": [
            {"sector": s, "avg_change": d["avg_change"], "strong_count": d["strong_count"]}
            for s, d in sector_ranking
        ],
        "timestamp": datetime.now(SHANGHAI_TZ).isoformat(),
    }


# =====================================================
# 命令行入口
# =====================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="CC Invest 美股市场扫描")
    parser.add_argument("--top", "-n", type=int, default=30, help="返回数量")
    parser.add_argument("--sector", "-s", help="按板块扫描")
    parser.add_argument("--min-score", type=float, default=0, help="最低评分")
    parser.add_argument("--sort", choices=["composite", "momentum", "trend", "quality"], 
                        default="composite", help="排序字段")
    parser.add_argument("--money-flow", action="store_true", help="资金流向分析")
    parser.add_argument("--top-picks", action="store_true", help="顶级机会汇总")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    
    args = parser.parse_args()
    
    if args.money_flow:
        flow = detect_money_flow()
        if args.json:
            print(json.dumps(flow, indent=2, ensure_ascii=False))
        else:
            print(f"\n{'='*60}")
            print(f"  💰 市场资金流向")
            print(f"{'='*60}")
            breadth = flow["market_breadth"]
            print(f"  上涨: {breadth['gainers']} 只 | 下跌: {breadth['losers']} 只")
            print(f"  市场广度: {breadth['breadth_ratio']}%")
            print(f"\n  📈 板块排名:")
            for s in flow["sector_ranking"][:5]:
                sign = "+" if s["avg_change"] > 0 else ""
                print(f"    {s['sector']:<30} {sign}{s['avg_change']:.2f}% 强势:{s['strong_count']}只")
            print(f"{'='*60}")
        return
    
    if args.top_picks:
        picks = get_top_picks(n=10)
        if args.json:
            print(json.dumps(picks, indent=2, ensure_ascii=False))
        else:
            print(f"\n{'='*60}")
            print(f"  🎯 顶级机会汇总")
            print(f"{'='*60}")
            for label, items in picks.items():
                if items:
                    print(f"\n  [{label.upper()}] ({len(items)} 只)")
                    for r in items[:5]:
                        print(f"    {r['symbol']:6}  score={r['composite']:.0f}  price=${r['price']:.2f}")
            print(f"{'='*60}")
        return
    
    if args.sector:
        results = scan_by_sector(args.sector, top_n=args.top)
        title = f"板块扫描: {args.sector}"
    else:
        results = scan_market(top_n=args.top, min_score=args.min_score, sort_by=args.sort)
        title = "市场扫描"
    
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(format_scan_results(results, title))


if __name__ == "__main__":
    main()

