#!/usr/bin/env python3
# =====================================================
# CC Invest - 美股每日/每周专业分析报告
# 整合市场扫描 + 板块轮动 + 财报日历 + 资金流
# 生成可执行的投资建议报告
# =====================================================

import os
import json
import time
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from loguru import logger

from dotenv import load_dotenv

load_dotenv()

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


# =====================================================
# 报告配置
# =====================================================

REPORT_SECTIONS = [
    "market_overview",    # 市场概览
    "top_picks",          # 精选机会
    "sector_rotation",     # 板块轮动
    "earnings_calendar",   # 财报日历
    "signals_summary",     # 信号汇总
    "risk_alert",         # 风险警示
    "trade_plan",         # 交易计划
]


@dataclass
class ReportConfig:
    """报告配置"""
    report_type: str          # "daily" / "weekly"
    period_label: str         # e.g. "2026年6月1日" / "2026年第23周"
    top_n_stocks: int = 20
    top_n_sectors: int = 5
    include_earnings: bool = True
    include_flow: bool = True
    min_confidence: float = 0.60


@dataclass
class DailyReport:
    """每日/每周报告"""
    report_type: str
    generated_at: str
    
    # 市场概览
    market_overview: Dict
    
    # 精选机会
    top_picks: List[Dict]      # 按 composite score 排序
    strong_buys: List[Dict]
    buy_candidates: List[Dict]
    hold_recommendations: List[Dict]
    
    # 板块轮动
    sector_rotation: Dict
    
    # 财报日历
    earnings_calendar: List[Dict]
    earnings_this_week: List[Dict]
    earnings_buys: List[Dict]   # 盈利预期上调的
    
    # 信号汇总
    signals_summary: Dict
    
    # 风险警示
    risk_alerts: List[Dict]
    
    # 综合建议
    recommendations: List[Dict]
    
    # 统计
    stats: Dict


@dataclass
class ReportRecommendation:
    """单一推荐"""
    symbol: str
    action: str       # BUY / SELL / HOLD
    confidence: float
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    rationale: str
    time_horizon: str  # short / medium / long
    sector: str
    key_signal: str
    risk_level: str


def generate_market_overview() -> Dict:
    """生成市场概览"""
    try:
        from src.market_scanner import scan_market, detect_money_flow
        
        # 扫描全部股票
        results = scan_market(top_n=500, min_score=0)
        
        if not results:
            return {"error": "无法获取市场数据"}
        
        gainers = [r for r in results if r["change_1d"] > 0]
        losers = [r for r in results if r["change_1d"] < 0]
        breadth = len(gainers) / max(1, len(results)) * 100
        
        # 强势股（综合评分 >= 60）
        strong = [r for r in results if r["composite"] >= 60]
        
        # 平均变化
        avg_change = sum(r["change_1d"] for r in results) / max(1, len(results))
        avg_1w = sum(r["change_1w"] for r in results) / max(1, len(results))
        avg_1m = sum(r["change_1m"] for r in results) / max(1, len(results))
        
        # 资金流
        flow = detect_money_flow()
        
        return {
            "total_scanned": len(results),
            "gainers": len(gainers),
            "losers": len(losers),
            "breadth_pct": round(breadth, 1),
            "avg_change_1d": round(avg_change, 2),
            "avg_change_1w": round(avg_1w, 2),
            "avg_change_1m": round(avg_1m, 2),
            "strong_stocks_count": len(strong),
            "sector_ranking": flow.get("sector_ranking", [])[:5],
            "market_signal": _infer_market_signal(results),
        }
        
    except Exception as e:
        logger.error(f"生成市场概览失败: {e}")
        return {"error": str(e)}


def _infer_market_signal(results: List[Dict]) -> str:
    """从扫描结果推断市场信号"""
    if not results:
        return "UNKNOWN"
    
    strong_buys = len([r for r in results if r["signal"] in ["STRONG_BUY", "BUY"]])
    sells = len([r for r in results if r["signal"] in ["SELL", "STRONG_SELL"]])
    avg_score = sum(r["composite"] for r in results) / len(results)
    
    if strong_buys >= 15 and sells <= 5 and avg_score >= 60:
        return "BULLISH"
    elif sells >= 15 and strong_buys <= 5 and avg_score <= 40:
        return "BEARISH"
    elif avg_score >= 55:
        return "RISK_ON"
    elif avg_score <= 45:
        return "RISK_OFF"
    else:
        return "NEUTRAL"


def generate_top_picks(n: int = 20) -> Dict:
    """生成精选机会"""
    try:
        from src.market_scanner import scan_market, get_top_picks
        
        # 获取顶级机会
        top_all = scan_market(top_n=n * 2, min_score=50)
        
        strong_buys = [r for r in top_all if r["signal"] == "STRONG_BUY"][:8]
        buys = [r for r in top_all if r["signal"] == "BUY"][:12]
        holds = [r for r in top_all if r["signal"] == "HOLD"][:8]
        
        return {
            "strong_buys": strong_buys,
            "buy_candidates": buys,
            "hold_recommendations": holds,
            "all_top_picks": top_all[:n],
        }
        
    except Exception as e:
        logger.error(f"生成精选失败: {e}")
        return {}


def generate_sector_rotation() -> Dict:
    """生成板块轮动分析"""
    try:
        from src.sector_rotation import analyze_sector_rotation
        return analyze_sector_rotation()
    except Exception as e:
        logger.error(f"生成板块轮动失败: {e}")
        return {}


def generate_earnings_calendar() -> Dict:
    """生成财报日历"""
    try:
        from src.earnings_calendar import get_upcoming_earnings_analysis
        return get_upcoming_earnings_analysis(n=20)
    except Exception as e:
        logger.error(f"生成财报日历失败: {e}")
        return {}


def generate_signals_summary(top_picks: Dict, sector_rot: Dict) -> Dict:
    """生成信号汇总"""
    signals = {
        "STRONG_BUY": 0,
        "BUY": 0,
        "HOLD": 0,
        "SELL": 0,
        "STRONG_SELL": 0,
    }
    
    for r in top_picks.get("all_top_picks", []):
        sig = r.get("signal", "NEUTRAL")
        if sig in signals:
            signals[sig] += 1
    
    # 资金流信号
    flow_signal = sector_rot.get("macro_signal", "NEUTRAL")
    
    # 板块信号
    sector_signals = [s.get("signal", "NEUTRAL") for s in sector_rot.get("sectors", [])]
    leading = sector_signals.count("LEADING")
    weak = sector_signals.count("WEAK") + sector_signals.count("LAGGING")
    
    return {
        "stock_signals": signals,
        "flow_signal": flow_signal,
        "leading_sectors": leading,
        "weak_sectors": weak,
        "bullish_count": signals["STRONG_BUY"] + signals["BUY"],
        "bearish_count": signals["SELL"] + signals["STRONG_SELL"],
    }


def generate_risk_alerts(results: List[Dict], sector_rot: Dict) -> List[Dict]:
    """生成风险警示"""
    alerts = []
    
    # 高 RSI 超买警告
    for r in results[:30]:
        if r.get("rsi", 50) > 70:
            alerts.append({
                "type": "OVERBOUGHT",
                "severity": "medium",
                "symbol": r["symbol"],
                "message": f"{r['symbol']} RSI={r['rsi']:.0f} 进入超买区域",
                "action": "注意短期回调风险",
            })
    
    # 高 Beta 高波动警告
    for r in results[:20]:
        if r.get("beta") and r["beta"] > 1.8:
            alerts.append({
                "type": "HIGH_VOLATILITY",
                "severity": "high",
                "symbol": r["symbol"],
                "message": f"{r['symbol']} Beta={r['beta']:.1f} 高波动性",
                "action": "降低仓位或严格止损",
            })
    
    # 资金流偏弱板块
    for s in sector_rot.get("sectors", []):
        if s.get("signal") == "LAGGING":
            alerts.append({
                "type": "SECTOR_WEAKING",
                "severity": "medium",
                "symbol": s["symbol"],
                "message": f"板块 {s['name']} 走弱，动量排名靠后",
                "action": "避免抄底，等待企稳",
            })
    
    # PE 极端警告
    for r in results[:20]:
        pe = r.get("pe")
        if pe and pe > 80:
            alerts.append({
                "type": "EXTREME_VALUATION",
                "severity": "medium",
                "symbol": r["symbol"],
                "message": f"{r['symbol']} PE={pe:.0f} 估值偏高",
                "action": "谨慎追高，等待回调",
            })
    
    return alerts[:10]


def generate_recommendations(top_picks: Dict, sector_rot: Dict, 
                             earnings_cal: Dict) -> List[Dict]:
    """生成具体交易建议"""
    recommendations = []
    
    # 精选 BUY 信号
    for r in top_picks.get("strong_buys", [])[:5]:
        recommendations.append({
            "symbol": r["symbol"],
            "action": "BUY",
            "confidence": r["confidence"],
            "entry_price": r.get("price"),
            "stop_loss": r.get("trade_plan", {}).get("stop_loss"),
            "take_profit_1": r.get("trade_plan", {}).get("take_profit_1"),
            "take_profit_2": r.get("trade_plan", {}).get("take_profit_2"),
            "rationale": " / ".join(r.get("reasons", [])[:2]),
            "time_horizon": "medium",
            "sector": r.get("sector", ""),
            "key_signal": "技术+动量+机构联合看涨",
            "risk_level": "medium",
        })
    
    # 板块轮动领先板块
    leading_sectors = [s for s in sector_rot.get("sectors", []) if s.get("signal") == "LEADING"]
    for sector in leading_sectors[:3]:
        recommendations.append({
            "symbol": sector["symbol"],
            "action": "SECTOR_ROTATION",
            "confidence": 0.75,
            "entry_price": sector.get("price"),
            "stop_loss": None,
            "take_profit": None,
            "rationale": f"板块轮动领先: {sector['name']}，动量评分 {sector['momentum_score']:.0f}",
            "time_horizon": "medium",
            "sector": sector["name"],
            "key_signal": f"宏观信号: {sector_rot.get('macro_signal', 'NEUTRAL')}",
            "risk_level": "medium",
        })
    
    # 财报 PEAD 机会
    for c in earnings_cal.get("earnings_buys", [])[:3]:
        recommendations.append({
            "symbol": c["symbol"],
            "action": "EARNINGS_PEAD",
            "confidence": c.get("confidence", 0.65),
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
            "rationale": f"盈利预期上调，距财报 {c.get('days_to_earnings', '?')} 天",
            "time_horizon": "short",
            "sector": "",
            "key_signal": "PEAD 策略：财报后延续趋势",
            "risk_level": "high",
        })
    
    return recommendations


def generate_report(report_type: str = "daily") -> DailyReport:
    """生成完整报告"""
    logger.info(f"生成{'每日' if report_type == 'daily' else '每周'}分析报告")
    
    # 时间标签
    now = datetime.now(SHANGHAI_TZ)
    if report_type == "daily":
        period_label = now.strftime("%Y年%m月%d日 %A")
    else:
        week_num = now.isocalendar()[1]
        period_label = f"{now.year}年第{week_num}周 ({now.strftime('%m/%d')})"
    
    # 1. 市场概览
    market_overview = generate_market_overview()
    
    # 2. 精选机会
    top_picks = generate_top_picks(n=20)
    all_results = top_picks.get("all_top_picks", [])
    
    # 3. 板块轮动
    sector_rotation = generate_sector_rotation()
    
    # 4. 财报日历
    earnings_calendar = generate_earnings_calendar()
    
    # 5. 信号汇总
    signals_summary = generate_signals_summary(top_picks, sector_rotation)
    
    # 6. 风险警示
    risk_alerts = generate_risk_alerts(all_results, sector_rotation)
    
    # 7. 综合建议
    recommendations = generate_recommendations(top_picks, sector_rotation, earnings_calendar)
    
    # 统计
    stats = {
        "total_stocks_scanned": market_overview.get("total_scanned", 0),
        "strong_buy_signals": signals_summary.get("bullish_count", 0),
        "sell_signals": signals_summary.get("bearish_count", 0),
        "earnings_this_week": earnings_calendar.get("summary", {}).get("this_week", 0),
        "leading_sectors": signals_summary.get("leading_sectors", 0),
        "risk_alerts_count": len(risk_alerts),
    }
    
    return DailyReport(
        report_type=report_type,
        generated_at=now.isoformat(),
        period_label=period_label,
        market_overview=market_overview,
        top_picks=top_picks.get("all_top_picks", []),
        strong_buys=top_picks.get("strong_buys", []),
        buy_candidates=top_picks.get("buy_candidates", []),
        hold_recommendations=top_picks.get("hold_recommendations", []),
        sector_rotation=sector_rotation,
        earnings_calendar=earnings_calendar.get("calendar", []),
        earnings_this_week=earnings_calendar.get("this_week", []),
        earnings_buys=earnings_calendar.get("earnings_buys", []),
        signals_summary=signals_summary,
        risk_alerts=risk_alerts,
        recommendations=recommendations,
        stats=stats,
    )


def report_to_dict(report: DailyReport) -> Dict:
    """将报告转换为字典"""
    return {
        "report_type": report.report_type,
        "generated_at": report.generated_at,
        "period_label": report.period_label,
        "market_overview": report.market_overview,
        "top_picks": report.top_picks,
        "strong_buys": report.strong_buys,
        "buy_candidates": report.buy_candidates,
        "sector_rotation": {
            "macro_signal": report.sector_rotation.get("macro_signal", ""),
            "macro_description": report.sector_rotation.get("macro_description", ""),
            "sectors": report.sector_rotation.get("sectors", [])[:11],
            "top_performers": report.sector_rotation.get("top_performers", []),
        },
        "earnings_calendar": {
            "this_week": report.earnings_this_week,
            "earnings_buys": report.earnings_buys,
        },
        "signals_summary": report.signals_summary,
        "risk_alerts": report.risk_alerts,
        "recommendations": report.recommendations,
        "stats": report.stats,
    }


def format_report_text(report: DailyReport) -> str:
    """格式化为可读文本"""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    
    console = Console()
    lines = []
    
    # 标题
    lines.append(f"\n{'='*80}")
    lines.append(f"  📊 {'每日' if report.report_type == 'daily' else '每周'}美股分析报告")
    lines.append(f"  📅 {report.period_label}")
    lines.append(f"  🕐 生成时间: {report.generated_at[:19]}")
    lines.append(f"{'='*80}")
    
    # 市场概览
    mo = report.market_overview
    if "error" not in mo:
        ms = mo.get("market_signal", "UNKNOWN")
        ms_icon = {"BULLISH": "🟢", "BEARISH": "🔴", "RISK_ON": "🟢", 
                   "RISK_OFF": "🟡", "NEUTRAL": "⚪"}.get(ms, "⚪")
        
        lines.append(f"\n  🏛️ 市场概览")
        lines.append(f"  扫描股票: {mo.get('total_scanned', 0)} 只")
        lines.append(f"  上涨/下跌: {mo.get('gainers', 0)}/{mo.get('losers', 0)}")
        lines.append(f"  市场广度: {mo.get('breadth_pct', 0):.1f}%")
        lines.append(f"  平均变化: 1D={mo.get('avg_change_1d', 0):+.2f}% "
                     f"1W={mo.get('avg_change_1w', 0):+.2f}% "
                     f"1M={mo.get('avg_change_1m', 0):+.2f}%")
        lines.append(f"  市场信号: {ms_icon} {ms}")
    
    # 精选机会
    if report.strong_buys:
        lines.append(f"\n  🟢 强势买入 ({len(report.strong_buys)} 只)")
        lines.append(f"  {'代码':<8} {'价格':>10} {'综合':>6} {'趋势':>6} {'动量':>6} {'RSI':>5} {'理由':<30}")
        lines.append(f"  {'-'*85}")
        for r in report.strong_buys[:8]:
            name = r.get("name", "")
            if len(name) > 28:
                name = name[:26] + ".."
            reasons = r.get("reasons", [""])
            reason = reasons[0][:28] if reasons else ""
            lines.append(
                f"  {r['symbol']:<8} ${r['price']:>9.2f} {r['composite']:>6.1f} "
                f"{r['scores']['trend']:>6.1f} {r['scores']['momentum']:>6.1f} "
                f"{r['rsi']:>5.0f} {reason:<30}"
            )
    
    if report.buy_candidates:
        lines.append(f"\n  🟠 买入候选 ({len(report.buy_candidates)} 只)")
        for r in report.buy_candidates[:5]:
            lines.append(f"    {r['symbol']:<8} score={r['composite']:.0f}  price=${r['price']:.2f}")
    
    # 板块轮动
    sr = report.sector_rotation
    if sr and "error" not in sr:
        ms = sr.get("macro_signal", "NEUTRAL")
        lines.append(f"\n  📈 板块轮动 | 宏观信号: {ms} — {sr.get('macro_description', '')}")
        lines.append(f"  {'排名':<4} {'板块':<20} {'信号':<10} {'动量':>6} {'1月%':>7}")
        lines.append(f"  {'-'*56}")
        for s in sr.get("sectors", [])[:8]:
            lines.append(
                f"  {s['rank']:<4} {s['name']:<20} {s['signal']:<10} "
                f"{s['momentum_score']:>6.1f} {s['change_1m']:>+6.1f}%"
            )
    
    # 财报日历
    if report.earnings_this_week:
        lines.append(f"\n  📅 本周财报 ({len(report.earnings_this_week)} 只)")
        for c in report.earnings_this_week[:5]:
            lines.append(f"    {c['symbol']:<8} {c['earnings_date']}  {c['earnings_time'] or 'TBD':<12} {c['signal']}")
    
    # 风险警示
    if report.risk_alerts:
        lines.append(f"\n  ⚠️  风险警示 ({len(report.risk_alerts)} 条)")
        for a in report.risk_alerts[:5]:
            lines.append(f"    [{a['type']}] {a['symbol']}: {a['message']}")
    
    # 综合建议
    if report.recommendations:
        lines.append(f"\n  🎯 交易建议")
        for rec in report.recommendations[:8]:
            if rec["action"] == "BUY":
                tp = rec.get("take_profit_1") or rec.get("take_profit")
                sl = rec.get("stop_loss")
                lines.append(
                    f"    🟢 {rec['symbol']}: BUY @ ${rec['entry_price']:.2f} | "
                    f"止损 ${sl:.2f} | 目标 ${tp:.2f} | "
                    f"置信度 {rec['confidence']*100:.0f}% | {rec['rationale'][:40]}"
                )
    
    # 统计
    stats = report.stats
    lines.append(f"\n  📊 统计:")
    lines.append(f"  强势信号: {stats.get('strong_buy_signals', 0)} | "
                 f"弱势信号: {stats.get('sell_signals', 0)} | "
                 f"本周财报: {stats.get('earnings_this_week', 0)} | "
                 f"风险预警: {stats.get('risk_alerts_count', 0)}")
    
    lines.append(f"\n{'='*80}")
    lines.append(f"  ⚠️  本报告仅供研究参考，不构成投资建议")
    lines.append(f"{'='*80}")
    
    return "\n".join(lines)


# =====================================================
# 命令行入口
# =====================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="CC Invest 美股分析报告")
    parser.add_argument("--type", "-t", choices=["daily", "weekly"], 
                        default="daily", help="报告类型")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    parser.add_argument("--compact", "-c", action="store_true", help="精简输出")
    
    args = parser.parse_args()
    
    report = generate_report(report_type=args.type)
    
    if args.json:
        print(json.dumps(report_to_dict(report), indent=2, ensure_ascii=False))
    elif args.compact:
        # 精简输出：只显示核心数据
        data = report_to_dict(report)
        print(f"\n📊 {report.period_label}")
        print(f"市场: {data['market_overview'].get('market_signal', 'N/A')} | "
              f"广度: {data['market_overview'].get('breadth_pct', 0):.0f}%")
        
        if data["strong_buys"]:
            picks = [r["symbol"] for r in data["strong_buys"][:5]]
            print(f"🟢 强势买入: {', '.join(picks)}")
        
        if data["sector_rotation"].get("macro_signal"):
            print(f"📈 宏观: {data['sector_rotation']['macro_signal']}")
        
        if data["earnings_calendar"].get("this_week"):
            cal = [c["symbol"] for c in data["earnings_calendar"]["this_week"][:5]]
            print(f"📅 本周财报: {', '.join(cal)}")
        
        if data["recommendations"]:
            top = data["recommendations"][0]
            print(f"🎯 首选: {top['symbol']} @ ${top.get('entry_price', 0):.2f} "
                  f"(置信度 {top['confidence']*100:.0f}%)")
    else:
        print(format_report_text(report))


if __name__ == "__main__":
    main()

