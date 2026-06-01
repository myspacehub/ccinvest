#!/usr/bin/env python3
# =====================================================
# CC Invest - 财报日历与盈利修正信号
# 追踪即将发布的财报、盈利修正、PEAD 信号
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
# 财报日历（高权重股票）
# =====================================================

# 未来 4 周内可能发布财报的大公司
EARNINGS_WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO",
    "ORCL", "CRM", "ADBE", "CSCO", "ACN", "AMD", "INTC", "QCOM", "TXN", "MU",
    "JPM", "BAC", "WFC", "GS", "MS",
    "UNH", "LLY", "JNJ", "PFE", "ABBV", "MRK", "BMY",
    "HD", "MCD", "NKE", "SBUX",
    "CAT", "HON", "BA", "GE", "UPS", "RTX", "LMT",
    "XOM", "CVX",
    "AMGN",
    "NOW", "SNOW", "PANW", "CRWD",
    "COST", "PG", "KO", "PEP", "WMT",
    "NFLX", "DIS",
]


@dataclass
class EarningsData:
    """单只股票的财报数据"""
    symbol: str
    name: str
    
    # 历史财报
    last_eps_actual: Optional[float]
    last_eps_estimate: Optional[float]
    last_surprise_pct: Optional[float]
    last_price_reaction: Optional[float]  # 财报后 5 日价格变化%
    
    # 当前共识
    current_eps_estimate: Optional[float]
    current_revenue_estimate: Optional[float]
    num_analysts: int
    
    # 修正趋势
    revision_30d_pct: Optional[float]  # 30 天 EPS 修正 %
    revision_direction: str  # UP / DOWN / STABLE
    
    # 下一财报日期
    next_earnings_date: Optional[str]
    next_earnings_time: Optional[str]  # BEFORE_MARKET / AFTER_MARKET / TBD
    
    # 信号
    signal: str  # EARNINGS_BUY / EARNINGS_SELL / NEUTRAL
    confidence: float
    pead_opportunity: bool  # 是否处于 PEAD 窗口
    days_to_earnings: Optional[int]
    
    reasons: List[str]
    timestamp: str


def _fetch_earnings_data(symbol: str) -> Tuple[Optional[Dict], Optional[pd.DataFrame], Dict]:
    """获取财报数据"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        
        # 财报日期
        earnings_dates = ticker.earnings_dates
        info = ticker.info or {}
        
        return earnings_dates, None, info
        
    except Exception as e:
        logger.debug(f"获取 {symbol} 财报数据失败: {e}")
        return None, None, {}


def _compute_earnings_signal(symbol: str) -> Optional[EarningsData]:
    """计算个股的财报信号"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        
        name = info.get("shortName", symbol)
        
        # 历史财报
        earnings_hist = None
        try:
            earnings_hist = ticker.earnings_history
        except:
            pass
        
        last_eps_actual = None
        last_eps_estimate = None
        last_surprise_pct = None
        last_price_reaction = None
        
        if earnings_hist is not None and not earnings_hist.empty:
            # 取最近一次财报
            last = earnings_hist.iloc[0]
            last_eps_actual = float(last.get("EPS Actual") or 0)
            last_eps_estimate = float(last.get("EPS Estimate") or 0)
            
            if last_eps_estimate and last_eps_estimate != 0:
                last_surprise_pct = (last_eps_actual - last_eps_estimate) / abs(last_eps_estimate) * 100
        
        # 当前共识
        trailing_eps = info.get("trailingEps", 0)
        forward_eps = info.get("forwardEps", 0)
        current_eps_estimate = forward_eps
        
        num_analysts = info.get("numberOfAnalystOpinions", 0) or 0
        
        # 估算 EPS 修正（基于盈利增长趋势）
        earnings_growth = info.get("earningsGrowth", 0) or 0
        if isinstance(earnings_growth, float):
            revision_30d_pct = earnings_growth * 30 * 100  # 简化估算
        else:
            revision_30d_pct = None
        
        revision_direction = "STABLE"
        if revision_30d_pct and revision_30d_pct > 3:
            revision_direction = "UP"
        elif revision_30d_pct and revision_30d_pct < -3:
            revision_direction = "DOWN"
        
        # 财报日期
        earnings_dates = None
        next_earnings_date = None
        next_earnings_time = None
        days_to_earnings = None
        
        try:
            ed = ticker.earnings_dates
            if ed is not None and not ed.empty:
                now = datetime.now()
                future_dates = ed[ed.index >= now].sort_values("Earnings Date")
                if not future_dates.empty:
                    next_ed = future_dates.iloc[0]
                    next_earnings_date = str(next_ed.name.date()) if hasattr(next_ed.name, "date") else str(next_ed.name)[:10]
                    next_earnings_time = next_ed.get("Reporting Time", "TBD")
                    ed_dt = datetime.strptime(next_earnings_date, "%Y-%m-%d") if next_earnings_date else None
                    if ed_dt:
                        days_to_earnings = (ed_dt.date() - date.today()).days
        except:
            pass
        
        # 信号判断
        signal = "NEUTRAL"
        confidence = 0.5
        reasons = []
        
        # 基于盈利修正方向
        if revision_direction == "UP":
            signal = "EARNINGS_BUY"
            confidence = 0.75
            reasons.append("盈利预期上调")
        elif revision_direction == "DOWN":
            signal = "EARNINGS_SELL"
            confidence = 0.70
            reasons.append("盈利预期下调")
        
        # 基于历史超预期
        if last_surprise_pct:
            if last_surprise_pct > 5:
                reasons.append(f"上季超预期 {last_surprise_pct:.0f}%")
                if signal == "NEUTRAL":
                    signal = "EARNINGS_BUY"
                    confidence = 0.65
            elif last_surprise_pct < -5:
                reasons.append(f"上季miss {last_surprise_pct:.0f}%")
                if signal == "NEUTRAL":
                    signal = "EARNINGS_SELL"
                    confidence = 0.65
        
        # PEAD 窗口（财报后 30 天内）
        pead_opportunity = False
        if days_to_earnings is not None:
            if 0 <= days_to_earnings <= 30:
                pead_opportunity = True
                reasons.append(f"距财报 {days_to_earnings} 天")
        
        # 分析评级加成
        rec = info.get("recommendationKey", "")
        if rec == "strongBuy":
            if signal == "NEUTRAL":
                signal = "EARNINGS_BUY"
                confidence = 0.70
            reasons.append("Strong Buy 评级")
        elif rec == "buy":
            reasons.append("Buy 评级")
        
        return EarningsData(
            symbol=symbol,
            name=name,
            last_eps_actual=last_eps_actual,
            last_eps_estimate=last_eps_estimate,
            last_surprise_pct=round(last_surprise_pct, 2) if last_surprise_pct else None,
            last_price_reaction=last_price_reaction,
            current_eps_estimate=current_eps_estimate,
            current_revenue_estimate=None,
            num_analysts=num_analysts,
            revision_30d_pct=round(revision_30d_pct, 2) if revision_30d_pct else None,
            revision_direction=revision_direction,
            next_earnings_date=next_earnings_date,
            next_earnings_time=next_earnings_time,
            signal=signal,
            confidence=round(confidence, 2),
            pead_opportunity=pead_opportunity,
            days_to_earnings=days_to_earnings,
            reasons=reasons,
            timestamp=datetime.now(SHANGHAI_TZ).isoformat(),
        )
        
    except Exception as e:
        logger.debug(f"计算 {symbol} 财报信号失败: {e}")
        return None


def get_earnings_calendar(days_ahead: int = 28) -> List[Dict]:
    """获取未来 N 天的财报日历"""
    logger.info(f"获取财报日历（未来 {days_ahead} 天）")
    
    results = []
    cutoff = date.today() + timedelta(days=days_ahead)
    
    for sym in EARNINGS_WATCHLIST:
        try:
            import yfinance as yf
            ticker = yf.Ticker(sym)
            info = ticker.info or {}
            name = info.get("shortName", sym)
            
            earnings_data = _compute_earnings_signal(sym)
            if not earnings_data:
                continue
            
            # 过滤在日期范围内的
            if earnings_data.next_earnings_date:
                ed = datetime.strptime(earnings_data.next_earnings_date, "%Y-%m-%d").date()
                if ed <= cutoff:
                    results.append({
                        "symbol": sym,
                        "name": name,
                        "earnings_date": earnings_data.next_earnings_date,
                        "earnings_time": earnings_data.next_earnings_time,
                        "days_to_earnings": earnings_data.days_to_earnings,
                        "signal": earnings_data.signal,
                        "confidence": earnings_data.confidence,
                        "revision_direction": earnings_data.revision_direction,
                        "last_surprise_pct": earnings_data.last_surprise_pct,
                        "num_analysts": earnings_data.num_analysts,
                        "reasons": earnings_data.reasons,
                    })
            
        except Exception:
            continue
        
        time.sleep(0.1)
    
    # 按日期排序
    results.sort(key=lambda x: x["earnings_date"] if x["earnings_date"] else "9999-99-99")
    
    return results


def get_upcoming_earnings_analysis(n: int = 10) -> Dict:
    """分析即将发布财报的高重要性股票"""
    calendar = get_earnings_calendar(28)
    
    if not calendar:
        return {"error": "no upcoming earnings found"}
    
    # 按信号分类
    earnings_buys = [c for c in calendar if c["signal"] == "EARNINGS_BUY"]
    earnings_sells = [c for c in calendar if c["signal"] == "EARNINGS_SELL"]
    
    # 本周/下周
    today = date.today()
    this_week = [c for c in calendar if c["days_to_earnings"] is not None and 0 <= c["days_to_earnings"] <= 7]
    next_week = [c for c in calendar if c["days_to_earnings"] is not None and 7 < c["days_to_earnings"] <= 14]
    
    return {
        "calendar": calendar[:n],
        "summary": {
            "total_upcoming": len(calendar),
            "earnings_buys": len(earnings_buys),
            "earnings_sells": len(earnings_sells),
            "this_week": len(this_week),
            "next_week": len(next_week),
        },
        "earnings_buys": earnings_buys[:5],
        "earnings_sells": earnings_sells[:5],
        "this_week": this_week,
        "next_week": next_week,
        "timestamp": datetime.now(SHANGHAI_TZ).isoformat(),
    }


def format_earnings_report(report: Dict) -> str:
    """格式化财报分析报告"""
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  📅 财报日历分析")
    lines.append(f"{'='*70}")
    
    if "error" in report:
        lines.append(f"  {report['error']}")
        lines.append(f"{'='*70}")
        return "\n".join(lines)
    
    summary = report["summary"]
    lines.append(f"\n  📊 概览: 未来 28 天 {summary['total_upcoming']} 只发布财报")
    lines.append(f"  🟢 盈利看涨: {summary['earnings_buys']} 只 | 🔴 盈利看跌: {summary['earnings_sells']} 只")
    lines.append(f"  📆 本周: {summary['this_week']} 只 | 下周: {summary['next_week']} 只")
    
    # 本周财报
    if report["this_week"]:
        lines.append(f"\n  📆 本周财报:")
        lines.append(f"  {'代码':<8} {'名称':<18} {'日期':<12} {'时间':<12} {'信号':<14} {'天数':>4}")
        lines.append(f"  {'-'*68}")
        for c in report["this_week"]:
            time_str = c.get("earnings_time", "TBD") or "TBD"
            sig_color = {"EARNINGS_BUY": "green", "EARNINGS_SELL": "red"}.get(c["signal"], "dim")
            lines.append(
                f"  {c['symbol']:<8} {c['name'][:16]:<18} {c['earnings_date']:<12} "
                f"{time_str:<12} [{sig_color}]{c['signal']}[/] {c['days_to_earnings']:>4}d"
            )
    
    # 盈利看涨
    if report["earnings_buys"]:
        lines.append(f"\n  🟢 盈利预期上调:")
        for c in report["earnings_buys"]:
            reasons_str = ", ".join(c["reasons"][:2])
            lines.append(f"    {c['symbol']:6} | {c['earnings_date']} | {reasons_str}")
    
    # 完整日历
    if report["calendar"]:
        lines.append(f"\n  📋 完整日历（近期）:")
        lines.append(f"  {'代码':<8} {'日期':<12} {'修正':<8} {'上季':<8} {'信号':<12}")
        lines.append(f"  {'-'*58}")
        for c in report["calendar"][:15]:
            rev = c.get("revision_direction", "-") or "-"
            surprise = c.get("last_surprise_pct")
            surprise_str = f"{surprise:+.1f}%" if surprise else "-"
            lines.append(
                f"  {c['symbol']:<8} {c['earnings_date']:<12} {rev:<8} {surprise_str:<8} {c['signal']:<12}"
            )
        
        if len(report["calendar"]) > 15:
            lines.append(f"  ... 共 {len(report['calendar'])} 只")
    
    lines.append(f"\n{'='*70}")
    return "\n".join(lines)


# =====================================================
# 命令行入口
# =====================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="CC Invest 财报日历分析")
    parser.add_argument("--days", type=int, default=28, help="前瞻天数")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    parser.add_argument("--calendar", action="store_true", help="仅显示日历")
    
    args = parser.parse_args()
    
    report = get_upcoming_earnings_analysis(n=30)
    
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_earnings_report(report))


if __name__ == "__main__":
    main()

