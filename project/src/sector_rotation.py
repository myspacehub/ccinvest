#!/usr/bin/env python3
# =====================================================
# CC Invest - 板块轮动分析
# 基于 ETF 资金流追踪 + 技术指标识别板块趋势
# 结合 vibe-trading 的 sector-rotation 技能
# =====================================================

import os
import json
import time
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from loguru import logger

from dotenv import load_dotenv

load_dotenv()

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# =====================================================
# 板块 ETF 配置
# =====================================================

SECTOR_ETFS = {
    "XLK": {"name": "Technology", "sensitivity": "growth", "cycle": "expansion"},
    "XLF": {"name": "Financials", "sensitivity": "rates", "cycle": "early_recovery"},
    "XLE": {"name": "Energy", "sensitivity": "commodity", "cycle": "late_cycle"},
    "XLV": {"name": "Healthcare", "sensitivity": "defensive", "cycle": "recession"},
    "XLY": {"name": "Consumer Discretionary", "sensitivity": "cyclical", "cycle": "recovery"},
    "XLP": {"name": "Consumer Staples", "sensitivity": "defensive", "cycle": "recession"},
    "XLI": {"name": "Industrials", "sensitivity": "cyclical", "cycle": "early_expansion"},
    "XLU": {"name": "Utilities", "sensitivity": "rate_sensitive", "cycle": "late_cycle"},
    "XLB": {"name": "Materials", "sensitivity": "commodity", "cycle": "early_cycle"},
    "XLRE": {"name": "Real Estate", "sensitivity": "rate_sensitive", "cycle": "rate_cut"},
    "XLC": {"name": "Communication Services", "sensitivity": "growth", "cycle": "expansion"},
}

BROAD_ETFS = {
    "SPY": {"name": "S&P 500", "role": "benchmark"},
    "QQQ": {"name": "Nasdaq 100", "role": "tech_growth"},
    "IWM": {"name": "Russell 2000", "role": "small_cap"},
    "DIA": {"name": "Dow Jones", "role": "blue_chip"},
}


@dataclass
class SectorData:
    """板块数据"""
    symbol: str
    name: str
    price: float
    change_1d: float
    change_1w: float
    change_1m: float
    change_3m: float
    flow_5d_pct: float    # 资金流 5日 %
    flow_20d_pct: float   # 资金流 20日 %
    momentum_score: float  # 动量评分 0-100
    relative_strength: float  # 相对 SPY 的强度
    signal: str  # LEADING / STRONG / NEUTRAL / WEAK / LAGGING
    trend: str   # UP / DOWN / SIDEWAYS
    rank: int


def _fetch_etf_data(symbol: str) -> Tuple[Optional[pd.DataFrame], Dict]:
    """获取 ETF 数据"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        
        df = ticker.history(period="3mo", interval="1d", auto_adjust=True, actions=False)
        if df.empty:
            return None, {}
        df.index = df.index.tz_localize(None) if df.index.tz else df.index
        
        return df, {
            "navPrice": info.get("navPrice") or info.get("regularMarketPrice"),
            "totalAssets": info.get("totalAssets", 0),
        }
        
    except Exception as e:
        logger.debug(f"获取 {symbol} 数据失败: {e}")
        return None, {}


def compute_sector_data(symbol: str, etf_config: Dict) -> Optional[SectorData]:
    """计算板块数据"""
    df, info = _fetch_etf_data(symbol)
    if df is None or df.empty:
        return None
    
    close = df["Close"]
    volume = df["Volume"]
    
    price = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) >= 2 else price
    
    # 价格变化
    change_1d = (price / prev - 1) * 100
    change_1w = (price / close.iloc[-5] - 1) * 100 if len(close) >= 5 else 0
    change_1m = (price / close.iloc[-22] - 1) * 100 if len(close) >= 22 else 0
    change_3m = (price / close.iloc[-66] - 1) * 100 if len(close) >= 66 else 0
    
    # 均线位置（判断趋势）
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    
    trend = "SIDEWAYS"
    if price > ma20.iloc[-1] > ma50.iloc[-1]:
        trend = "UP"
    elif price < ma20.iloc[-1] < ma50.iloc[-1]:
        trend = "DOWN"
    
    # 资金流估算（成交量对比）
    avg_vol_5d = volume.iloc[-5:].mean() if len(volume) >= 5 else volume.mean()
    avg_vol_20d = volume.iloc[-20:].mean() if len(volume) >= 20 else avg_vol_5d
    avg_vol_60d = volume.iloc[-60:].mean() if len(volume) >= 60 else avg_vol_5d
    
    # 资金流代理：成交量增加 = 资金流入
    flow_5d_pct = (avg_vol_5d / avg_vol_60d - 1) * 100 if avg_vol_60d > 0 else 0
    flow_20d_pct = (avg_vol_20d / avg_vol_60d - 1) * 100 if avg_vol_60d > 0 else 0
    
    # 动量评分
    momentum_score = (
        min(100, max(0, change_1m * 3 + 50)) * 0.3 +
        min(100, max(0, change_1w * 6 + 50)) * 0.3 +
        min(100, max(0, flow_5d_pct * 2 + 50)) * 0.2 +
        (100 if trend == "UP" else 50 if trend == "SIDEWAYS" else 20) * 0.2
    )
    
    return SectorData(
        symbol=symbol,
        name=etf_config.get("name", symbol),
        price=round(price, 2),
        change_1d=round(change_1d, 2),
        change_1w=round(change_1w, 2),
        change_1m=round(change_1m, 2),
        change_3m=round(change_3m, 2),
        flow_5d_pct=round(flow_5d_pct, 2),
        flow_20d_pct=round(flow_20d_pct, 2),
        momentum_score=round(momentum_score, 1),
        relative_strength=0,  # 待计算
        signal="NEUTRAL",
        trend=trend,
        rank=0,
    )


def analyze_sector_rotation() -> Dict:
    """分析板块轮动"""
    logger.info("开始板块轮动分析")
    
    results = {}
    
    # 获取宽基 ETF 基准数据
    benchmark_data = {}
    for sym, config in BROAD_ETFS.items():
        data = compute_sector_data(sym, config)
        if data:
            benchmark_data[sym] = data
    
    spy_data = benchmark_data.get("SPY")
    
    # 获取所有板块 ETF
    sector_data = {}
    for sym, config in SECTOR_ETFS.items():
        data = compute_sector_data(sym, config)
        if data:
            sector_data[sym] = data
    
    # 计算相对强度（相对 SPY）
    for sym, data in sector_data.items():
        if spy_data and spy_data.change_1m != 0:
            rs = (data.change_1m - spy_data.change_1m)
        else:
            rs = 0
        data.relative_strength = round(rs, 2)
    
    # 排序和信号
    sorted_sectors = sorted(sector_data.values(), key=lambda x: x.momentum_score, reverse=True)
    
    for i, data in enumerate(sorted_sectors):
        data.rank = i + 1
        
        # 信号判断
        rs = data.relative_strength
        mom = data.momentum_score
        flow = data.flow_5d_pct
        
        if data.trend == "UP" and rs > 3 and mom > 65:
            data.signal = "LEADING"
        elif data.trend == "UP" and (rs > 0 or flow > 5):
            data.signal = "STRONG"
        elif data.trend == "DOWN" and rs < -5 and mom < 40:
            data.signal = "LAGGING"
        elif data.trend == "DOWN" or rs < -2:
            data.signal = "WEAK"
        else:
            data.signal = "NEUTRAL"
    
    # === 宏观信号判断 ===
    leading_count = sum(1 for d in sorted_sectors if d.signal == "LEADING")
    weak_count = sum(1 for d in sorted_sectors if d.signal in ["WEAK", "LAGGING"])
    avg_momentum = np.mean([d.momentum_score for d in sorted_sectors])
    
    if leading_count >= 4 and avg_momentum >= 60:
        macro_signal = "BULLISH"
        macro_desc = "多个板块领先，市场趋势向上"
    elif weak_count >= 5 and avg_momentum <= 40:
        macro_signal = "BEARISH"
        macro_desc = "多数板块偏弱，注意风险"
    elif spy_data and spy_data.change_1m > 2:
        macro_signal = "RISK_ON"
        macro_desc = "宽基 ETF 走强，风险偏好上升"
    elif spy_data and spy_data.change_1m < -2:
        macro_signal = "RISK_OFF"
        macro_desc = "宽基 ETF 走弱，风险偏好下降"
    else:
        macro_signal = "NEUTRAL"
        macro_desc = "板块分化，结构市"
    
    # === 板块轮动阶段识别 ===
    # 早期：金融、能源、材料、工业领先
    # 中期：科技、消费、医疗领先
    # 后期：公用事业、消费必需品防御
    
    cycle_sectors = {
        "early_cycle": [d for d in sorted_sectors if d.symbol in ["XLF", "XLE", "XLB", "XLI"]],
        "mid_cycle": [d for d in sorted_sectors if d.symbol in ["XLK", "XLY", "XLV"]],
        "late_cycle": [d for d in sorted_sectors if d.symbol in ["XLU", "XLP", "XLRE"]],
    }
    
    # 找出最强的板块
    top_3 = [d.symbol for d in sorted_sectors[:3]]
    
    return {
        "macro_signal": macro_signal,
        "macro_description": macro_desc,
        "avg_momentum": round(avg_momentum, 1),
        "leading_sectors": leading_count,
        "weak_sectors": weak_count,
        "top_performers": top_3,
        "cycle_analysis": {
            stage: [d.symbol for d in sectors]
            for stage, sectors in cycle_sectors.items()
        },
        "sectors": [
            {
                "symbol": d.symbol,
                "name": d.name,
                "rank": d.rank,
                "signal": d.signal,
                "trend": d.trend,
                "momentum_score": d.momentum_score,
                "change_1d": d.change_1d,
                "change_1w": d.change_1w,
                "change_1m": d.change_1m,
                "relative_strength": d.relative_strength,
                "flow_5d_pct": d.flow_5d_pct,
                "flow_20d_pct": d.flow_20d_pct,
            }
            for d in sorted_sectors
        ],
        "benchmark": [
            {
                "symbol": d.symbol,
                "name": d.name,
                "price": d.price,
                "change_1d": d.change_1d,
                "change_1w": d.change_1w,
                "change_1m": d.change_1m,
                "momentum_score": d.momentum_score,
            }
            for d in benchmark_data.values()
        ] if benchmark_data else [],
        "timestamp": datetime.now(SHANGHAI_TZ).isoformat(),
    }


def format_sector_rotation_report(report: Dict) -> str:
    """格式化板块轮动报告"""
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  📊 板块轮动分析")
    lines.append(f"{'='*70}")
    
    # 宏观信号
    ms = report["macro_signal"]
    ms_color = {"BULLISH": "green", "BEARISH": "red", "RISK_ON": "cyan", 
                "RISK_OFF": "yellow", "NEUTRAL": "dim"}.get(ms, "")
    
    lines.append(f"\n  🎯 宏观信号: [{ms_color}]{ms}[/] — {report['macro_description']}")
    lines.append(f"  📈 平均动量: {report['avg_momentum']:.1f}")
    lines.append(f"  📌 领先板块: {report['leading_sectors']} 个 | 偏弱: {report['weak_sectors']} 个")
    lines.append(f"  🏆 强势板块: {', '.join(report['top_performers'])}")
    
    lines.append(f"\n  板块排名 (按动量):")
    lines.append(f"  {'排名':<4} {'ETF':<6} {'名称':<22} {'信号':<10} {'趋势':<8} {'动量':>6} {'1月%':>7} {'相对强度':>8}")
    lines.append(f"  {'-'*72}")
    
    sig_symbols = {"LEADING": "🔴", "STRONG": "🟠", "NEUTRAL": "⚪", "WEAK": "🟡", "LAGGING": "🔵"}
    
    for s in report["sectors"]:
        sig_icon = sig_symbols.get(s["signal"], "⚪")
        rs = s["relative_strength"]
        rs_str = f"{rs:+.1f}%" if rs else "—"
        
        lines.append(
            f"  {s['rank']:<4} {s['symbol']:<6} {s['name']:<22} "
            f"{sig_icon}{s['signal']:<8} {s['trend']:<8} "
            f"{s['momentum_score']:>6.1f} {s['change_1m']:>+6.1f}% {rs_str:>8}"
        )
    
    # 宽基
    if report["benchmark"]:
        lines.append(f"\n  宽基 ETF:")
        for b in report["benchmark"]:
            lines.append(
                f"    {b['symbol']:<6} {b['name']:<20} "
                f"${b['price']:>9.2f}  1W: {b['change_1w']:>+5.1f}%  1M: {b['change_1m']:>+6.1f}%"
            )
    
    lines.append(f"\n{'='*70}")
    return "\n".join(lines)


# =====================================================
# 命令行入口
# =====================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="CC Invest 板块轮动分析")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    
    args = parser.parse_args()
    
    report = analyze_sector_rotation()
    
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_sector_rotation_report(report))


if __name__ == "__main__":
    main()

