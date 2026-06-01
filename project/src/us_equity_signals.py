#!/usr/bin/env python3
# =====================================================
# CC Invest - 美股综合信号引擎
# 整合技术分析 + ETF 资金流 + 机构持仓 + 盈利修正
# 基于 vibe-trading 技能体系增强
# =====================================================

import os
import json
import time
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import requests
import numpy as np
import pandas as pd
from loguru import logger

from dotenv import load_dotenv

load_dotenv()

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


# =====================================================
# 数据源：yfinance 免费获取
# =====================================================

def fetch_yfinance_ohlcv(symbol: str, period: str = "6mo",
                         interval: str = "1d") -> pd.DataFrame:
    """通过 yfinance 获取 OHLCV 数据，无网络时使用数据库备用数据"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True, actions=False)
        if df.empty:
            return df
        df.index = df.index.tz_localize(None) if df.index.tz else df.index
        return df
    except Exception as e:
        logger.debug(f"yfinance 获取 {symbol} 失败，尝试数据库备用: {e}")
        # 从数据库获取备用数据
        return _fetch_from_database(symbol, interval)
    
def _fetch_from_database(symbol: str, interval: str = "1d") -> pd.DataFrame:
    """从本地数据库获取 OHLCV 数据作为备用"""
    try:
        from sqlalchemy import create_engine, text
        import os
        db_url = os.getenv("DATABASE_URL", "sqlite:///data/ccinvest.db")
        engine = create_engine(db_url)
        
        timeframe_map = {"1d": "1d", "1h": "1h", "1m": "1m", "5m": "5m"}
        tf = timeframe_map.get(interval, "1d")
        
        query = text("""
            SELECT timestamp, open_price as Open, high_price as High,
                   low_price as Low, close_price as Close, volume as Volume
            FROM ohlc_data
            WHERE symbol = :symbol AND timeframe = :tf
            ORDER BY timestamp DESC
            LIMIT 500
        """)
        
        df = pd.read_sql(query, engine, params={"symbol": symbol, "tf": tf})
        if not df.empty:
            df = df.sort_values("timestamp").set_index("timestamp")
            return df
    except Exception:
        pass
    return pd.DataFrame()


def fetch_yfinance_info(symbol: str) -> Dict:
    """获取公司基本信息"""
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info
        return {k: info.get(k) for k in [
            "shortName", "longName", "sector", "industry",
            "marketCap", "trailingPE", "forwardPE", "pegRatio",
            "dividendYield", "dividendRate", "beta",
            "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
            "recommendationKey", "numberOfAnalystOpinions",
            "earningsGrowth", "revenueGrowth", "profitMargins",
            "trailingEps", "forwardEps", "totalRevenue",
            "operatingMargins", "netMargins",
            "bookValue", "priceToBook",
            "currentRatio", "debtToEquity", "totalDebt",
            "freeCashflow", "operatingCashflow",
            "sharesOutstanding", "sharesShort",
        ]}
    except Exception as e:
        logger.warning(f"yfinance info {symbol} 失败: {e}")
        return {}


def fetch_earnings_dates(symbol: str) -> List[Dict]:
    """获取未来财报日期"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        edates = ticker.earnings_dates
        if edates is None or edates.empty:
            return []
        now = datetime.now()
        future = edates[edates.index >= now].sort_values("Earnings Date")
        return [
            {"date": str(r["Earnings Date"].date()),
             "eps_estimate": r.get("EPS Estimate"),
             "eps_actual": r.get("EPS Actual"),
             "reporting_time": r.get("Reporting Time")}
            for _, r in future.head(4).iterrows()
        ]
    except Exception as e:
        return []


# =====================================================
# 数据源：ETF 资金流（通过 yfinance 历史计算）
# =====================================================

ETF_FLOW_PAIRS: Dict[str, Tuple[str, str, str]] = {
    # symbol, display_name, sector_category
    "SPY":  ("SPDR S&P 500 ETF",           "broad_market"),
    "QQQ":  ("Invesco QQQ Trust",          "tech_growth"),
    "IWM":  ("iShares Russell 2000 ETF",   "small_cap"),
    "XLK":  ("Technology Select SPDR",     "tech"),
    "XLF":  ("Financial Select SPDR",      "financials"),
    "XLE":  ("Energy Select SPDR",         "energy"),
    "XLV":  ("Health Care Select SPDR",   "healthcare"),
    "XLY":  ("Consumer Discret Select",   "consumer_discret"),
    "XLP":  ("Consumer Staples Select",    "consumer_staples"),
    "XLI":  ("Industrials Select SPDR",    "industrials"),
    "XLU":  ("Utilities Select SPDR",     "utilities"),
    "XLB":  ("Materials Select SPDR",      "materials"),
    "XLRE": ("Real Estate Select SPDR",   "real_estate"),
    "XLC":  ("Communication Select SPDR",  "communications"),
    "IVW":  ("iShares S&P 500 Growth",     "growth"),
    "IVE":  ("iShares S&P 500 Value",      "value"),
    "MTUM": ("iShares MSCI Momentum",      "momentum"),
    "QUAL": ("iShares MSCI Quality",       "quality"),
    "USMV": ("iShares MSCI Min Vol",       "low_vol"),
    "SPYG": ("SPDR S&P 500 Growth",        "sp500_growth"),
    "SPYV": ("SPDR S&P 500 Value",         "sp500_value"),
    "VEA":  ("Vanguard FTSE Dev Markets",   "intl_developed"),
    "VWO":  ("Vanguard FTSE Emerg Mkts",   "emerging"),
    "AGG":  ("iShares Core US Aggregate",   "bonds"),
    "TLT":  ("iShares 20+ Yr Treasury",     "long_bonds"),
}


@dataclass
class ETFFlowData:
    """单只 ETF 资金流数据"""
    symbol: str
    name: str
    category: str
    price: float
    change_1d: float      # 1日价格变化%
    flow_1d: float       # 1日资金净流入（相对AUM %）
    flow_5d: float       # 5日资金净流入
    flow_20d: float      # 20日资金净流入
    aum: float           # 管理规模（亿美元）
    price_vs_ma20: float # 价格 vs 20日均线 %
    price_vs_ma50: float # 价格 vs 50日均线 %
    momentum_score: float  # 动量评分 0-100


def compute_etf_flows(symbols: List[str] = None) -> List[ETFFlowData]:
    """计算多只 ETF 的资金流（通过净流入估算）"""
    symbols = symbols or list(ETF_FLOW_PAIRS.keys())
    results = []
    
    for sym in symbols:
        if sym not in ETF_FLOW_PAIRS:
            continue
        name, category = ETF_FLOW_PAIRS[sym]
        
        try:
            import yfinance as yf
            ticker = yf.Ticker(sym)
            info = ticker.info
            
            # 当前价格和 AUM
            price = info.get("regularMarketPrice") or info.get("navPrice") or 0
            aum = info.get("totalAssets", 0) / 1e8  # 转换为亿美元
            
            if price <= 0 or aum <= 0:
                continue
            
            # 获取历史价格和成交量
            df_5d  = ticker.history(period="5d",  interval="1d", auto_adjust=True, actions=False)
            df_20d = ticker.history(period="20d", interval="1d", auto_adjust=True, actions=False)
            df_60d = ticker.history(period="60d", interval="1d", auto_adjust=True, actions=False)
            
            if df_5d.empty or len(df_5d) < 2:
                continue
            
            # 计算资金流入估算
            # 净流入 = 成交量变化 * 价格（简化估算）
            avg_daily_volume = df_60d["Volume"].mean() if len(df_60d) >= 5 else df_5d["Volume"].mean()
            
            # 5日净流入（相对AUM %）
            vol_5d = df_5d["Volume"].values
            price_5d = df_5d["Close"].values
            # 用成交量加权估算资金流
            daily_dollars_5d = vol_5d * price_5d / 1e6  # 百万美元
            avg_daily_5d = np.mean(daily_dollars_5d)
            
            # 与60日平均对比估算资金流方向
            vol_60d = df_60d["Volume"].values if len(df_60d) >= 20 else vol_5d
            avg_daily_60d = np.mean(vol_60d) * np.mean(price_5d) / 1e6
            
            # 相对交易量估算（作为资金流代理）
            volume_ratio_5d = np.mean(vol_5d) / avg_daily_60d if avg_daily_60d > 0 else 1.0
            price_trend_5d = (price_5d[-1] - price_5d[0]) / price_5d[0] * 100
            
            # 资金流估算：成交量比率 × 价格变化方向
            flow_5d_est = (volume_ratio_5d - 1.0) * 100  # 正=净流入
            flow_1d_est = flow_5d_est * price_trend_5d / (abs(price_trend_5d) + 0.5)
            
            # 20日
            vol_20d = df_20d["Volume"].values if len(df_20d) >= 10 else vol_5d
            price_20d = df_20d["Close"].values
            volume_ratio_20d = np.mean(vol_20d) / avg_daily_60d if avg_daily_60d > 0 else 1.0
            flow_20d_est = (volume_ratio_20d - 1.0) * 100
            
            # 均线
            ma20 = df_20d["Close"].rolling(5).mean().iloc[-1] if len(df_20d) >= 20 else price
            ma50_val = df_60d["Close"].rolling(20).mean().iloc[-1] if len(df_60d) >= 50 else price
            price_vs_ma20 = (price - ma20) / ma20 * 100 if ma20 > 0 else 0
            price_vs_ma50 = (price - ma50_val) / ma50_val * 100 if ma50_val > 0 else 0
            
            # 动量评分（0-100）
            momentum = (price_vs_ma20 * 0.4 + price_vs_ma50 * 0.3 + flow_5d_est * 0.3)
            momentum_score = max(0, min(100, 50 + momentum * 5))
            
            results.append(ETFFlowData(
                symbol=sym,
                name=name,
                category=category,
                price=price,
                change_1d=price_trend_5d,
                flow_1d=flow_1d_est,
                flow_5d=flow_5d_est,
                flow_20d=flow_20d_est,
                aum=aum,
                price_vs_ma20=price_vs_ma20,
                price_vs_ma50=price_vs_ma50,
                momentum_score=momentum_score,
            ))
            
            time.sleep(0.1)  # 避免限速
            
        except Exception as e:
            logger.debug(f"ETF {sym} 数据获取失败: {e}")
            continue
    
    return results


# =====================================================
# 数据源：机构持仓（13F 代理）
# =====================================================

def fetch_institutional_holders(symbol: str) -> Dict:
    """获取机构持仓概况"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        holders = ticker.institutional_holders
        major = ticker.major_holders
        
        if holders is None or holders.empty:
            return {"institutional_ownership_pct": None, "top_holders": []}
        
        # 机构持股比例
        inst_pct = holders["Holder"].apply(
            lambda x: float(str(holders[holders["Holder"] == x]["Shares"].iloc[0]).replace("%", "").strip())
            if "Shares" in holders.columns and "%" in str(holders["Shares"].dtype) else 0
        ).sum() if "Holder" in holders.columns else 0
        
        # 简化方法：直接取 major_holders
        if major is not None and not major.empty:
            for _, row in major.iterrows():
                if "Institutions" in str(row.get(0, "")):
                    inst_pct = float(str(row.get(1, "0")).replace("%", "").strip())
        
        top_3 = holders.head(3).to_dict("records") if len(holders) > 0 else []
        
        return {
            "institutional_ownership_pct": inst_pct,
            "top_holders": top_3[:3],
            "num_holders": len(holders) if holders is not None else 0,
        }
    except Exception:
        return {"institutional_ownership_pct": None, "top_holders": []}


# =====================================================
# 技术指标计算（增强版）
# =====================================================

def compute_technical_score(df: pd.DataFrame) -> Dict:
    """计算综合技术评分（0-100）"""
    if df.empty or len(df) < 20:
        return {"score": 0, "signal": "insufficient_data"}
    
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    
    scores = {}
    
    # 1. 趋势（均线多头排列）
    ma5  = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean() if len(df) >= 200 else ma50
    
    latest = close.iloc[-1]
    
    trend_score = 0
    if latest > ma20.iloc[-1] > ma50.iloc[-1] > ma200.iloc[-1]:
        trend_score = 100
    elif latest > ma20.iloc[-1] > ma50.iloc[-1]:
        trend_score = 75
    elif latest > ma20.iloc[-1]:
        trend_score = 50
    elif latest < ma20.iloc[-1] < ma50.iloc[-1]:
        trend_score = 20
    scores["trend"] = trend_score
    
    # 2. 动量（RSI）
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - 100 / (1 + rs)).iloc[-1]
    rsi_score = 100 - abs(rsi - 50) * 2  # 50=中性, 0=极端
    scores["rsi"] = max(0, min(100, rsi_score))
    
    # 3. MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    histogram = macd_line - signal_line
    macd_score = 50 + histogram.iloc[-1] / close.iloc[-1] * 1000  # 归一化
    scores["macd"] = max(0, min(100, macd_score))
    
    # 4. 成交量确认
    vol_avg20 = volume.rolling(20).mean().iloc[-1]
    vol_today = volume.iloc[-1]
    vol_score = min(100, (vol_today / vol_avg20) * 50) if vol_avg20 > 0 else 50
    # 放量上涨 or 缩量整理
    price_up = close.iloc[-1] > close.iloc[-2]
    if price_up and vol_today > vol_avg20:
        vol_score = min(100, vol_score + 20)  # 放量上涨加成
    scores["volume"] = vol_score
    
    # 5. 布林带
    bb_mid = close.rolling(20).mean().iloc[-1]
    bb_std = close.rolling(20).std().iloc[-1]
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_position = (latest - bb_lower) / (bb_upper - bb_lower) * 100 if bb_upper > bb_lower else 50
    scores["bollinger"] = bb_position
    
    # 6. ATR 波动率（风险调整）
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean().iloc[-1]
    atr_pct = atr14 / latest * 100 if latest > 0 else 0
    # ATR% 适中=好，过高或过低都扣分
    atr_score = max(0, 100 - abs(atr_pct - 5) * 5)
    scores["atr"] = atr_score
    
    # 综合技术评分（加权）
    weights = {"trend": 0.30, "rsi": 0.20, "macd": 0.20, "volume": 0.15, "bollinger": 0.10, "atr": 0.05}
    total_score = sum(scores[k] * weights[k] for k in weights)
    
    # 信号方向
    if total_score >= 65 and trend_score >= 60:
        signal = "BULLISH"
    elif total_score <= 35 and trend_score <= 40:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"
    
    return {
        "score": round(total_score, 1),
        "signal": signal,
        "components": {k: round(v, 1) for k, v in scores.items()},
        "price": round(latest, 2),
        "rsi": round(rsi, 1),
        "atr_pct": round(atr_pct, 2),
        "price_vs_ma20_pct": round((latest / ma20.iloc[-1] - 1) * 100, 2),
        "price_vs_ma50_pct": round((latest / ma50.iloc[-1] - 1) * 100, 2),
    }


# =====================================================
# 资金流评分（ETF 轮动信号）
# =====================================================

def compute_flow_score(symbol: str) -> Dict:
    """计算资金流评分"""
    # 判断 symbol 属于哪个 sector ETF
    sector_map = {
        "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AVGO": "XLK", "CRM": "XLK", "ADBE": "XLK", "CSCO": "XLK", "ACN": "XLK", "ORCL": "XLK", "IBM": "XLK",
        "JPM": "XLF", "BAC": "XLF", "WFC": "XLF", "GS": "XLF", "MS": "XLF", "C": "XLF", "USB": "XLF", "TFC": "XLF",
        "XOM": "XLE", "CVX": "XLE", "COP": "XLE", "SLB": "XLE", "EOG": "XLE",
        "UNH": "XLV", "JNJ": "XLV", "LLY": "XLV", "PFE": "XLV", "ABBV": "XLV", "MRK": "XLV", "TMO": "XLV", "ABT": "XLV",
        "AMZN": "XLY", "TSLA": "XLY", "HD": "XLY", "MCD": "XLY", "NKE": "XLY", "BKNG": "XLY", "LOW": "XLY",
        "KO": "XLP", "PEP": "XLP", "PG": "XLP", "WMT": "XLP", "COST": "XLP", "PM": "XLP", "MO": "XLP",
        "CAT": "XLI", "HON": "XLI", "BA": "XLI", "GE": "XLI", "UPS": "XLI", "RTX": "XLI", "LMT": "XLI",
        "NEE": "XLU", "DUK": "XLU", "SO": "XLU", "D": "XLU", "AEP": "XLU",
        "LIN": "XLB", "APD": "XLB", "FCX": "XLB", "NEM": "XLB",
        "AMT": "XLRE", "PLD": "XLRE", "EQIX": "XLRE", "SPG": "XLRE",
        "META": "XLC", "GOOGL": "XLC", "NFLX": "XLC", "DIS": "XLC", "CMCSA": "XLC",
    }
    
    sector_etf = sector_map.get(symbol)
    
    # 获取宽基 ETF 资金流
    broad_etfs = ["SPY", "QQQ", "IWM"]
    etf_flows = compute_etf_flows(broad_etfs)
    
    flow_data = {e.symbol: e for e in etf_flows}
    
    broad_signal = "NEUTRAL"
    if "SPY" in flow_data and "IWM" in flow_data:
        spy_flow = flow_data["SPY"].flow_5d
        iwm_flow = flow_data["IWM"].flow_5d
        if spy_flow > 5 and iwm_flow > 5:
            broad_signal = "RISK_ON"
        elif spy_flow < -5 and iwm_flow < -5:
            broad_signal = "RISK_OFF"
        elif spy_flow > 5 and iwm_flow < -2:
            broad_signal = "QUALITY_ROTATION"
        elif spy_flow < -5 and iwm_flow > 2:
            broad_signal = "SMALL_CAP_LEAD"
        else:
            broad_signal = "NEUTRAL"
    
    # Sector 信号
    sector_signal = "NEUTRAL"
    sector_flows = []
    if sector_etf:
        sector_data = compute_etf_flows([sector_etf])
        if sector_data:
            se = sector_data[0]
            sector_flows = [{"symbol": se.symbol, "flow_5d": round(se.flow_5d, 2)}]
            if se.flow_5d > 5 and se.momentum_score > 60:
                sector_signal = "SECTOR_LEADING"
            elif se.flow_5d < -5 and se.momentum_score < 40:
                sector_signal = "SECTOR_WEAKING"
    
    # 计算资金流综合评分
    flow_score = 50
    
    if "SPY" in flow_data:
        spy_flow_score = max(-20, min(20, flow_data["SPY"].flow_5d * 2))
        flow_score += spy_flow_score
    
    if "QQQ" in flow_data:
        qqq_flow_score = max(-20, min(20, flow_data["QQQ"].flow_5d * 2))
        flow_score += qqq_flow_score
    
    flow_score = max(0, min(100, flow_score))
    
    return {
        "score": round(flow_score, 1),
        "broad_signal": broad_signal,
        "sector_signal": sector_signal,
        "sector_etf": sector_etf,
        "sector_flows": sector_flows,
        "broad_etf_flows": [
            {"symbol": e.symbol, "flow_5d": round(e.flow_5d, 2), "momentum_score": round(e.momentum_score, 1)}
            for e in etf_flows
        ]
    }


# =====================================================
# 机构持仓评分
# =====================================================

def compute_institutional_score(symbol: str, info: Dict) -> Dict:
    """计算机构持仓评分"""
    score = 50
    signals = []
    
    # 大型机构持股（代理：用持股集中度）
    inst_pct = info.get("institutional_ownership_pct")
    if inst_pct:
        if inst_pct > 70:
            score += 15
            signals.append(f"机构持股高 ({inst_pct:.0f}%)")
        elif inst_pct > 50:
            score += 8
        elif inst_pct < 30:
            score -= 10
            signals.append(f"机构持股低 ({inst_pct:.0f}%)")
    
    # 分析师评级
    rec_key = info.get("recommendationKey", "")
    if rec_key == "strongBuy":
        score += 15
        signals.append("Strong Buy 评级")
    elif rec_key == "buy":
        score += 10
        signals.append("Buy 评级")
    elif rec_key == "hold":
        score += 0
    elif rec_key in ["sell", "strongSell"]:
        score -= 15
        signals.append("Sell 评级")
    
    # 分析师数量
    num_analysts = info.get("numberOfAnalystOpinions", 0)
    if num_analysts > 20:
        score += 5
        signals.append(f"高覆盖度 ({num_analysts} 位分析师)")
    elif num_analysts < 5:
        score -= 5
        signals.append(f"低覆盖度 ({num_analysts} 位分析师)")
    
    # 盈利增长
    earnings_growth = info.get("earningsGrowth", 0)
    if earnings_growth:
        eg = float(earnings_growth) * 100
        if eg > 20:
            score += 12
            signals.append(f"盈利增长强劲 ({eg:.0f}%)")
        elif eg > 10:
            score += 6
        elif eg < 0:
            score -= 8
            signals.append(f"盈利下滑 ({eg:.0f}%)")
    
    # 营收增长
    rev_growth = info.get("revenueGrowth", 0)
    if rev_growth:
        rg = float(rev_growth) * 100
        if rg > 15:
            score += 8
            signals.append(f"营收增长强劲 ({rg:.0f}%)")
        elif rg < 0:
            score -= 5
    
    # 利润率
    pm = info.get("profitMargins", 0)
    if pm:
        margin = float(pm) * 100
        if margin > 25:
            score += 8
            signals.append(f"高利润率 ({margin:.0f}%)")
        elif margin < 5:
            score -= 5
    
    # ROE / 质量
    if info.get("trailingEps") and info.get("priceToBook"):
        trailing_eps = info.get("trailingEps", 0)
        price_to_book = info.get("priceToBook", 0)
        book_value = info.get("bookValue", 0)
        if trailing_eps and price_to_book and book_value:
            roe = trailing_eps / book_value * 100
            if roe > 20:
                score += 8
                signals.append(f"高 ROE ({roe:.0f}%)")
            elif roe < 5:
                score -= 5
    
    # Beta（风险）
    beta = info.get("beta", 1.0)
    if beta:
        beta_val = float(beta)
        if beta_val > 1.5:
            score -= 5
            signals.append(f"高波动 (Beta={beta_val:.1f})")
        elif beta_val < 0.8:
            score += 3
            signals.append(f"低波动 (Beta={beta_val:.1f})")
    
    score = max(0, min(100, score))
    
    return {
        "score": round(score, 1),
        "signals": signals[:5],
        "recommendation": rec_key,
        "num_analysts": num_analysts,
        "earnings_growth_pct": round(float(earnings_growth or 0) * 100, 1) if earnings_growth else None,
    }


# =====================================================
# 估值评分
# =====================================================

def compute_valuation_score(info: Dict) -> Dict:
    """计算估值评分"""
    score = 50
    signals = []
    
    trailing_pe = info.get("trailingPE") or 0
    forward_pe = info.get("forwardPE") or 0
    peg = info.get("pegRatio") or 0
    
    if trailing_pe and trailing_pe > 0 and trailing_pe < 999:
        if trailing_pe < 15:
            score += 15
            signals.append(f"低估值 (PE={trailing_pe:.1f})")
        elif trailing_pe < 25:
            score += 5
        elif trailing_pe > 50:
            score -= 10
            signals.append(f"高估值 (PE={trailing_pe:.1f})")
    
    if forward_pe and forward_pe > 0 and forward_pe < 999:
        if forward_pe < trailing_pe:
            score += 8
            signals.append("盈利预期改善 (Forward PE < Trailing PE)")
        elif forward_pe > trailing_pe * 1.2:
            score -= 5
    
    if peg and float(peg) > 0:
        peg_val = float(peg)
        if peg_val < 1:
            score += 12
            signals.append(f"PEG 吸引 (PEG={peg_val:.2f})")
        elif peg_val > 2:
            score -= 8
            signals.append(f"PEG 偏高 (PEG={peg_val:.2f})")
    
    # Forward EPS 增长
    trailing_eps = info.get("trailingEps", 0)
    forward_eps = info.get("forwardEps", 0)
    if trailing_eps and forward_eps and float(trailing_eps) > 0:
        eps_growth = (float(forward_eps) - float(trailing_eps)) / float(trailing_eps) * 100
        if eps_growth > 20:
            score += 8
        elif eps_growth < 0:
            score -= 5
    
    score = max(0, min(100, score))
    
    return {
        "score": round(score, 1),
        "signals": signals[:4],
        "trailing_pe": round(trailing_pe, 1) if trailing_pe else None,
        "forward_pe": round(forward_pe, 1) if forward_pe else None,
        "peg_ratio": round(float(peg), 2) if peg and float(peg) > 0 else None,
    }


# =====================================================
# 综合信号生成
# =====================================================

@dataclass
class USEquitySignal:
    """美股综合信号"""
    symbol: str
    price: float
    change_1d: float
    
    technical_score: float
    flow_score: float
    institutional_score: float
    valuation_score: float
    
    composite_score: float      # 综合评分 0-100
    signal: str                # BUY / SELL / HOLD / WAIT
    confidence: float          # 置信度 0-1
    
    trend_strength: str
    momentum: str
    risk_level: str           # low / medium / high
    
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit_1: Optional[float]
    take_profit_2: Optional[float]
    
    reasons: List[str]
    warnings: List[str]
    
    technical_detail: Dict
    flow_detail: Dict
    institutional_detail: Dict
    valuation_detail: Dict
    
    earnings_dates: List[Dict]
    info: Dict
    
    timestamp: str


def generate_us_equity_signal(symbol: str,
                               fetch_deep: bool = True) -> USEquitySignal:
    """
    生成美股综合交易信号
    
    Args:
        symbol: 美股代码（无后缀，如 AAPL, MSFT, NVDA）
        fetch_deep: 是否获取机构持仓和资金流数据
    
    Returns:
        USEquitySignal: 综合信号
    """
    logger.info(f"生成美股信号: {symbol}")
    
    # 1. 获取基础数据
    df = fetch_yfinance_ohlcv(symbol, period="6mo", interval="1d")
    info = fetch_yfinance_info(symbol) if fetch_deep else {}
    
    if df.empty:
        # 尝试生成模拟数据用于演示
        return _generate_mock_signal(symbol, info)
    
    price = float(df["Close"].iloc[-1])
    prev_price = float(df["Close"].iloc[-2]) if len(df) >= 2 else price
    change_1d = (price / prev_price - 1) * 100
    
    # 2. 计算各维度评分
    tech = compute_technical_score(df)
    flow = compute_flow_score(symbol) if fetch_deep else {"score": 50, "broad_signal": "UNKNOWN", "sector_signal": "UNKNOWN"}
    inst = compute_institutional_score(symbol, info) if fetch_deep else {"score": 50, "signals": [], "recommendation": "unknown"}
    val = compute_valuation_score(info) if fetch_deep else {"score": 50, "signals": []}
    
    # 3. 综合评分（加权）
    w_tech, w_flow, w_inst, w_val = 0.35, 0.25, 0.25, 0.15
    composite = (
        tech["score"] * w_tech +
        flow["score"] * w_flow +
        inst["score"] * w_inst +
        val["score"] * w_val
    )
    
    # 4. 信号方向
    if composite >= 70 and tech["signal"] == "BULLISH":
        signal = "BUY"
        confidence = min(0.95, 0.5 + composite / 200)
    elif composite <= 30 and tech["signal"] == "BEARISH":
        signal = "SELL"
        confidence = min(0.95, 0.5 + (100 - composite) / 200)
    elif composite >= 55:
        signal = "HOLD"
        confidence = 0.5
    else:
        signal = "WAIT"
        confidence = 0.4
    
    # 5. 趋势强度和动量
    if tech["score"] >= 70:
        trend_strength = "STRONG_UPTREND"
    elif tech["score"] >= 55:
        trend_strength = "WEAK_UPTREND"
    elif tech["score"] <= 30:
        trend_strength = "STRONG_DOWNTREND"
    elif tech["score"] <= 45:
        trend_strength = "WEAK_DOWNTREND"
    else:
        trend_strength = "NEUTRAL"
    
    rsi = tech.get("rsi", 50)
    if rsi > 65:
        momentum = "OVERBOUGHT"
    elif rsi < 35:
        momentum = "OVERSOLD"
    else:
        momentum = "NEUTRAL"
    
    # 6. 风险等级
    atr_pct = tech.get("atr_pct", 5)
    beta = info.get("beta", 1.0) or 1.0
    beta_val = float(beta)
    
    if atr_pct > 10 or beta_val > 1.5:
        risk_level = "high"
    elif atr_pct > 5 or beta_val > 1.0:
        risk_level = "medium"
    else:
        risk_level = "low"
    
    # 7. 止损止盈
    if signal == "BUY":
        atr_val = price * (tech.get("atr_pct", 5) / 100)
        stop_loss = round(price - atr_val * 1.5, 2)
        take_profit_1 = round(price + atr_val * 2.0, 2)
        take_profit_2 = round(price + atr_val * 3.5, 2)
    elif signal == "SELL":
        atr_val = price * (tech.get("atr_pct", 5) / 100)
        stop_loss = round(price + atr_val * 1.5, 2)
        take_profit_1 = round(price - atr_val * 2.0, 2)
        take_profit_2 = round(price - atr_val * 3.5, 2)
    else:
        stop_loss = take_profit_1 = take_profit_2 = None
    
    # 8. 理由说明
    reasons = []
    if tech["components"]["trend"] >= 70:
        reasons.append("技术趋势向上（均线多头排列）")
    if inst["signals"]:
        reasons.extend(inst["signals"][:2])
    if val["signals"]:
        reasons.extend(val["signals"][:2])
    if flow.get("broad_signal") in ["RISK_ON", "QUALITY_ROTATION"]:
        reasons.append(f"资金流信号: {flow['broad_signal']}（ETF 净流入）")
    
    warnings = []
    if momentum == "OVERBOUGHT":
        warnings.append("RSI 进入超买区域，短期可能回调")
    if tech["components"]["atr"] < 40:
        warnings.append("ATR 波动率偏低，趋势可能减弱")
    if risk_level == "high":
        warnings.append(f"高风险：Beta={beta_val:.1f}, ATR%={atr_pct:.1f}%")
    if flow.get("broad_signal") == "RISK_OFF":
        warnings.append("资金流: 宽基 ETF 净流出，市场情绪偏弱")
    
    # 9. 财报日期
    earnings_dates = fetch_earnings_dates(symbol) if fetch_deep else []
    
    return USEquitySignal(
        symbol=symbol,
        price=round(price, 2),
        change_1d=round(change_1d, 2),
        technical_score=round(tech["score"], 1),
        flow_score=round(flow["score"], 1),
        institutional_score=round(inst["score"], 1),
        valuation_score=round(val["score"], 1),
        composite_score=round(composite, 1),
        signal=signal,
        confidence=round(confidence, 2),
        trend_strength=trend_strength,
        momentum=momentum,
        risk_level=risk_level,
        entry_price=round(price, 2),
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        reasons=reasons[:5],
        warnings=warnings[:3],
        technical_detail=tech,
        flow_detail=flow,
        institutional_detail=inst,
        valuation_detail=val,
        earnings_dates=earnings_dates,
        info={k: v for k, v in info.items() if v is not None},
        timestamp=datetime.now(SHANGHAI_TZ).isoformat(),
    )


def signal_to_dict(sig: USEquitySignal) -> Dict:
    """将信号转换为可序列化字典"""
    return {
        "symbol": sig.symbol,
        "price": sig.price,
        "change_1d_pct": sig.change_1d,
        "scores": {
            "technical": sig.technical_score,
            "flow": sig.flow_score,
            "institutional": sig.institutional_score,
            "valuation": sig.valuation_score,
        },
        "composite_score": sig.composite_score,
        "signal": sig.signal,
        "confidence": sig.confidence,
        "trend_strength": sig.trend_strength,
        "momentum": sig.momentum,
        "risk_level": sig.risk_level,
        "trade_plan": {
            "entry_price": sig.entry_price,
            "stop_loss": sig.stop_loss,
            "take_profit_1": sig.take_profit_1,
            "take_profit_2": sig.take_profit_2,
        } if sig.signal in ["BUY", "SELL"] else None,
        "reasons": sig.reasons,
        "warnings": sig.warnings,
        "technical_detail": sig.technical_detail,
        "flow_signal": sig.flow_detail.get("broad_signal"),
        "sector_flow": sig.flow_detail.get("sector_signal"),
        "earnings_dates": sig.earnings_dates,
        "timestamp": sig.timestamp,
    }


# =====================================================
# 多股扫描
# =====================================================

def scan_us_equities(symbols: List[str], fetch_deep: bool = True) -> List[Dict]:
    """扫描多个美股，生成信号"""
    results = []
    
    for sym in symbols:
        try:
            sig = generate_us_equity_signal(sym, fetch_deep=fetch_deep)
            results.append(signal_to_dict(sig))
        except Exception as e:
            logger.warning(f"扫描 {sym} 失败: {e}")
        
        time.sleep(0.2)
    
    # 按综合评分排序
    results.sort(key=lambda x: x["composite_score"], reverse=True)
    
    return results


def format_signal_text(sig_dict: Dict) -> str:
    """格式化信号为可读文本"""
    lines = []
    lines.append(f"\n{'='*56}")
    lines.append(f"  📊 {sig_dict['symbol']} 综合交易信号")
    lines.append(f"{'='*56}")
    lines.append(f"  价格: ${sig_dict['price']:,.2f}  ({sig_dict['change_1d_pct']:+.2f}%)")
    lines.append(f"")
    lines.append(f"  📈 综合评分: {sig_dict['composite_score']:.1f} / 100")
    lines.append(f"  🎯 信号: [{sig_dict['signal']}] 置信度: {sig_dict['confidence']*100:.0f}%")
    lines.append(f"  📉 趋势: {sig_dict['trend_strength']}")
    lines.append(f"  ⚡ 动量: {sig_dict['momentum']}")
    lines.append(f"  ⚠️ 风险: {sig_dict['risk_level']}")
    lines.append(f"")
    
    scores = sig_dict['scores']
    lines.append(f"  评分明细:")
    lines.append(f"    技术面: {scores['technical']:.1f}")
    lines.append(f"    资金流: {scores['flow']:.1f}  ({sig_dict['flow_signal'] or 'N/A'})")
    lines.append(f"    机构面: {scores['institutional']:.1f}")
    lines.append(f"    估值面: {scores['valuation']:.1f}")
    
    if sig_dict['trade_plan']:
        tp = sig_dict['trade_plan']
        lines.append(f"")
        lines.append(f"  📋 交易计划:")
        lines.append(f"    入场价: ${tp['entry_price']:,.2f}")
        if tp['stop_loss']:
            lines.append(f"    止损:   ${tp['stop_loss']:,.2f}")
        if tp['take_profit_1']:
            lines.append(f"    止盈1:  ${tp['take_profit_1']:,.2f}")
        if tp['take_profit_2']:
            lines.append(f"    止盈2:  ${tp['take_profit_2']:,.2f}")
    
    if sig_dict['reasons']:
        lines.append(f"")
        lines.append(f"  💡 理由:")
        for r in sig_dict['reasons']:
            lines.append(f"    • {r}")
    
    if sig_dict['warnings']:
        lines.append(f"")
        lines.append(f"  ⚠️  警告:")
        for w in sig_dict['warnings']:
            lines.append(f"    • {w}")
    
    if sig_dict['earnings_dates']:
        lines.append(f"")
        lines.append(f"  📅 即将财报:")
        for ed in sig_dict['earnings_dates'][:2]:
            lines.append(f"    {ed['date']}  预测EPS: {ed.get('eps_estimate', 'N/A')}")
    
    lines.append(f"{'='*56}")
    return "\n".join(lines)


# =====================================================
# 命令行入口
# =====================================================



def _generate_mock_signal(symbol: str, info: Dict) -> USEquitySignal:
    """生成模拟信号（用于演示/无数据时）"""
    # 估算价格（从 info 或使用默认值）
    price = info.get("currentPrice") or info.get("regularMarketPrice") or 100.0
    
    # 估算变化
    prev_close = price * (1 - 0.01)
    change_1d = 1.0
    
    # 基于行业和估值的模拟评分
    sector = info.get("sector", "")
    trailing_pe = info.get("trailingPE", 20)
    
    technical_score = 50 + (20 if trailing_pe < 25 else -10)
    flow_score = 50
    inst_score = 50 + (info.get("recommendationKey") == "buy" and 15 or 0)
    val_score = 100 - min(50, trailing_pe / 2) if trailing_pe and trailing_pe > 0 else 50
    
    composite = technical_score * 0.35 + flow_score * 0.25 + inst_score * 0.25 + val_score * 0.15
    
    signal = "HOLD" if composite >= 50 else "WAIT"
    if composite >= 70: signal = "BUY"
    elif composite <= 30: signal = "SELL"
    
    return USEquitySignal(
        symbol=symbol,
        price=round(float(price), 2),
        change_1d=round(change_1d, 2),
        technical_score=round(technical_score, 1),
        flow_score=round(flow_score, 1),
        institutional_score=round(inst_score, 1),
        valuation_score=round(val_score, 1),
        composite_score=round(composite, 1),
        signal=signal + " (demo)",
        confidence=0.4,
        trend_strength="UNKNOWN",
        momentum="NEUTRAL",
        risk_level="medium",
        entry_price=None, stop_loss=None,
        take_profit_1=None, take_profit_2=None,
        reasons=["⚠️ 无实时数据，使用模拟信号仅供参考"],
        warnings=["演示模式：建议在有网络环境时重新获取信号"],
        technical_detail={"score": technical_score, "signal": "demo"},
        flow_detail={"score": flow_score, "broad_signal": "UNKNOWN"},
        institutional_detail={"score": inst_score},
        valuation_detail={"score": val_score},
        earnings_dates=[],
        info=info,
        timestamp=datetime.now(SHANGHAI_TZ).isoformat(),
    )


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CC Invest 美股综合信号")
    parser.add_argument("--symbol", "-s", default="AAPL", help="股票代码")
    parser.add_argument("--scan", nargs="+", help="批量扫描")
    parser.add_argument("--deep", action="store_true", help="深度分析（含资金流）")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    
    args = parser.parse_args()
    
    if args.scan:
        results = scan_us_equities(args.scan, fetch_deep=args.deep)
        for r in results:
            if args.json:
                print(json.dumps(r, indent=2, ensure_ascii=False))
            else:
                print(format_signal_text(r))
    else:
        sig = generate_us_equity_signal(args.symbol, fetch_deep=args.deep)
        sig_dict = signal_to_dict(sig)
        
        if args.json:
            print(json.dumps(sig_dict, indent=2, ensure_ascii=False))
        else:
            print(format_signal_text(sig_dict))


if __name__ == "__main__":
    main()

