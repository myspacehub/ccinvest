#!/usr/bin/env python3
# =====================================================
# CC Invest - 技术分析执行器
# 直接运行 OpenClaw 技能进行技术分析
# =====================================================

import sys
import json
from datetime import datetime
from typing import Dict, List, Optional

from dotenv import load_dotenv
from loguru import logger

load_dotenv()


class TechnicalAnalyzer:
    """技术分析执行器"""
    
    def __init__(self):
        self.indicators_cache = {}
    
    def analyze(self, symbol: str, timeframe: str = "1h") -> Dict:
        """执行完整技术分析"""
        from src.collector import DataCollector
        
        # 获取数据
        collector = DataCollector()
        df = collector.compute_indicators(symbol, timeframe)
        
        if df.empty:
            return {"error": "数据不足"}
        
        # 获取最新数据
        latest = df.iloc[-1]
        
        # 获取市场数据
        market_result = collector.fetch_binance_ticker(symbol)
        if isinstance(market_result, tuple):
            market_data, _ = market_result
        else:
            market_data = market_result
        current_price = market_data.get("price") if market_data else latest.get("close", 0)
        change_24h = market_data.get("change_24h") if market_data else None
        
        # 生成信号
        signal = self._generate_signal(df, current_price)
        
        # 计算信号强度和置信度
        strength = self._calculate_strength(df)
        confidence = self._calculate_confidence(df, signal)
        
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "current_price": current_price,
            "change_24h": change_24h,
            "indicators": {
                "MA": {
                    "MA5": float(latest.get("ma_short", 0)),
                    "MA20": float(latest.get("ma_medium", 0)),
                    "MA50": float(latest.get("ma_long", 0)),
                    "trend": "bullish" if current_price > latest.get("ma_short", 0) else "bearish"
                },
                "RSI": {
                    "value": float(latest.get("rsi", 50)),
                    "status": self._get_rsi_status(latest.get("rsi", 50))
                },
                "MACD": {
                    "value": float(latest.get("macd", 0)),
                    "signal": float(latest.get("signal", 0)),
                    "histogram": float(latest.get("histogram", 0)),
                    "crossover": "bullish" if latest.get("histogram", 0) > 0 else "bearish"
                },
                "Bollinger": {
                    "upper": float(latest.get("bb_upper", 0)),
                    "middle": float(latest.get("bb_middle", 0)),
                    "lower": float(latest.get("bb_lower", 0)),
                    "bandwidth": float(latest.get("bb_std", 0)) * 2 / float(latest.get("bb_middle", 1))
                },
                "ATR": float(latest.get("atr", 0)),
                "Stochastic": {
                    "k": float(latest.get("stoch_k", 50)),
                    "d": float(latest.get("stoch_d", 50)),
                    "status": "overbought" if latest.get("stoch_k", 50) > 80 else "oversold" if latest.get("stoch_k", 50) < 20 else "neutral"
                },
                "ADX": {
                    "value": float(latest.get("adx", 0)),
                    "trend": "strong" if latest.get("adx", 0) > 25 else "weak"
                },
                "CCI": {
                    "value": float(latest.get("cci", 0)),
                    "status": "overbought" if latest.get("cci", 0) > 100 else "oversold" if latest.get("cci", 0) < -100 else "neutral"
                },
                "MFI": {
                    "value": float(latest.get("mfi", 50)),
                    "status": "overbought" if latest.get("mfi", 50) > 80 else "oversold" if latest.get("mfi", 50) < 20 else "neutral"
                },
                "Williams_R": {
                    "value": float(latest.get("williams_r", -50))
                },
                "OBV": {
                    "value": float(latest.get("obv", 0))
                },
                "VWAP": {
                    "value": float(latest.get("vwap", 0))
                },
                "Aroon": {
                    "up": float(latest.get("aroon_up", 0)),
                    "down": float(latest.get("aroon_down", 0)),
                    "oscillator": float(latest.get("aroon_osc", 0))
                },
                "Fibonacci": {
                    "level_236": float(latest.get("fib_236", 0)),
                    "level_382": float(latest.get("fib_382", 0)),
                    "level_500": float(latest.get("fib_500", 0)),
                    "level_618": float(latest.get("fib_618", 0)),
                    "level_786": float(latest.get("fib_786", 0))
                },
                "Parabolic_SAR": {
                    "value": float(latest.get("sar", 0))
                },
                "Keltner": {
                    "upper": float(latest.get("kc_upper", 0)),
                    "middle": float(latest.get("kc_middle", 0)),
                    "lower": float(latest.get("kc_lower", 0))
                }
            },
            "signal": signal,
            "strength": strength,
            "confidence": confidence,
            "reasoning": self._generate_reasoning(df, signal, latest),
            "recommendations": self._generate_recommendations(signal, strength, confidence),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def _generate_signal(self, df, current_price: float) -> Dict:
        """生成交易信号"""
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        
        signals = []
        strength_sum = 0
        count = 0
        
        # RSI 分析
        rsi = latest.get("rsi", 50)
        if rsi < 30:
            signals.append(("BUY", 0.8))
        elif rsi > 70:
            signals.append(("SELL", 0.8))
        elif rsi < 45:
            signals.append(("BUY", 0.3))
        elif rsi > 55:
            signals.append(("SELL", 0.3))
        strength_sum += rsi
        count += 1
        
        # MACD 分析
        macd_hist = latest.get("histogram", 0)
        prev_hist = prev.get("histogram", 0)
        if macd_hist > 0 and prev_hist <= 0:
            signals.append(("BUY", 0.9))  # 金叉
        elif macd_hist < 0 and prev_hist >= 0:
            signals.append(("SELL", 0.9))  # 死叉
        elif macd_hist > 0:
            signals.append(("BUY", 0.5))
        else:
            signals.append(("SELL", 0.5))
        
        # 布林带分析
        bb_upper = latest.get("bb_upper", current_price * 1.02)
        bb_lower = latest.get("bb_lower", current_price * 0.98)
        if current_price < bb_lower:
            signals.append(("BUY", 0.7))  # 超卖
        elif current_price > bb_upper:
            signals.append(("SELL", 0.7))  # 超买
        
        # 均线分析
        ma_short = latest.get("ma_short", current_price)
        ma_long = latest.get("ma_long", current_price)
        if current_price > ma_short and ma_short > ma_long:
            signals.append(("BUY", 0.6))
        elif current_price < ma_short and ma_short < ma_long:
            signals.append(("SELL", 0.6))
        
        # 综合评分
        buy_score = sum(s[1] for s in signals if s[0] == "BUY")
        sell_score = sum(s[1] for s in signals if s[0] == "SELL")
        
        if buy_score > sell_score * 1.2:
            signal_type = "BUY"
            signal_strength = min(buy_score / (count * 4), 1.0)
        elif sell_score > buy_score * 1.2:
            signal_type = "SELL"
            signal_strength = min(sell_score / (count * 4), 1.0)
        else:
            signal_type = "HOLD"
            signal_strength = 0.5
        
        return {
            "type": signal_type,
            "strength": signal_strength,
            "scores": {"buy": buy_score, "sell": sell_score}
        }
    
    def _calculate_strength(self, df) -> float:
        """计算信号强度"""
        return 0.75  # 简化实现
    
    def _calculate_confidence(self, df, signal: Dict) -> float:
        """计算置信度"""
        # 基于指标一致性
        scores = signal.get("scores", {"buy": 0, "sell": 0})
        total = scores.get("buy", 0) + scores.get("sell", 0)
        
        if total == 0:
            return 0.5
        
        dominant = max(scores.values())
        consistency = dominant / total
        
        return min(consistency * 0.9 + 0.1, 1.0)
    
    def _get_rsi_status(self, rsi: float) -> str:
        """RSI 状态"""
        if rsi < 30:
            return "oversold"
        elif rsi > 70:
            return "overbought"
        elif rsi < 45:
            return "weak"
        elif rsi > 55:
            return "strong"
        return "neutral"
    
    def _generate_reasoning(self, df, signal: Dict, latest) -> List[str]:
        """生成理由说明"""
        reasoning = []
        
        signal_type = signal.get("type")
        
        # RSI 理由
        rsi = latest.get("rsi", 50)
        if signal_type == "BUY" and rsi < 50:
            reasoning.append(f"RSI 从超卖区域反弹 (RSI: {rsi:.1f})")
        elif signal_type == "SELL" and rsi > 50:
            reasoning.append(f"RSI 进入超买区域 (RSI: {rsi:.1f})")
        
        # MACD 理由
        macd_hist = latest.get("histogram", 0)
        if macd_hist > 0:
            reasoning.append("MACD 柱状图持续放大")
        else:
            reasoning.append("MACD 柱状图持续收缩")
        
        # 布林带理由
        current_price = latest.get("close", 0)
        bb_lower = latest.get("bb_lower", 0)
        bb_upper = latest.get("bb_upper", 0)
        
        if current_price < bb_lower:
            reasoning.append("价格触及布林带下轨")
        elif current_price > bb_upper:
            reasoning.append("价格触及布林带上轨")
        
        return reasoning if reasoning else ["信号不明确，建议观望"]
    
    def _generate_recommendations(self, signal: Dict, strength: float, confidence: float) -> Dict:
        """生成交易建议"""
        signal_type = signal.get("type", "HOLD")
        
        if signal_type == "HOLD" or confidence < 0.6:
            return {
                "action": "观望",
                "entry_price": None,
                "stop_loss": None,
                "take_profit": None,
                "risk_level": "low",
                "message": "信号不明确，建议等待确认"
            }
        
        recommendations = {
            "action": signal_type,
            "confidence": f"{confidence * 100:.0f}%",
            "position_size": "正常" if strength > 0.6 else "轻仓"
        }
        
        if signal_type == "BUY":
            recommendations.update({
                "stop_loss": "入场价 - 2% ATR",
                "take_profit": ["入场价 + 3%", "入场价 + 5%"],
                "risk_level": "medium" if strength > 0.7 else "high"
            })
        else:
            recommendations.update({
                "stop_loss": "入场价 + 2% ATR",
                "take_profit": ["入场价 - 3%", "入场价 - 5%"],
                "risk_level": "medium" if strength > 0.7 else "high"
            })
        
        return recommendations


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='CC Invest 技术分析')
    parser.add_argument('--symbol', '-s', default='BTCUSDT', help='交易对')
    parser.add_argument('--timeframe', '-t', default='1h', help='时间周期')
    parser.add_argument('--json', '-j', action='store_true', help='输出 JSON')
    
    args = parser.parse_args()
    
    analyzer = TechnicalAnalyzer()
    result = analyzer.analyze(args.symbol, args.timeframe)
    
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"\n📊 {result['symbol']} 技术分析 ({result['timeframe']})")
        print("=" * 50)
        print(f"当前价格: ${result['current_price']:,.2f}")
        print(f"24h 涨跌: {result['change_24h']:+.2f}%")
        print()
        print("📈 技术指标:")
        for name, data in result['indicators'].items():
            if isinstance(data, dict):
                print(f"  {name}: {data}")
            else:
                print(f"  {name}: {data}")
        print()
        print(f"📌 信号: {result['signal']['type']} (强度: {result['signal']['strength']:.2f})")
        print(f"🎯 置信度: {result['confidence']:.2f}")
        print()
        print("💡 理由:")
        for reason in result['reasoning']:
            print(f"  • {reason}")


if __name__ == "__main__":
    main()