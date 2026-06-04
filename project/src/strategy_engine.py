"""
Multi-asset strategy engine for crypto and US equities.

The engine is deliberately conservative: it only emits a directional signal
when trend, momentum, volatility, and volume evidence line up. Otherwise it
returns WAIT_CONFIRMATION with explicit reasons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

import numpy as np
import pandas as pd


AssetClass = Literal["crypto", "us_equity"]


@dataclass(frozen=True)
class StrategyProfile:
    asset_class: AssetClass
    min_bars: int
    min_confidence: int
    high_atr_pct: float
    extreme_atr_pct: float
    base_risk_pct: float
    max_risk_pct: float
    volume_confirm_ratio: float
    overextension_atr_multiple: float


PROFILES: Dict[AssetClass, StrategyProfile] = {
    "crypto": StrategyProfile(
        asset_class="crypto",
        min_bars=50,                # 降低K线要求，加速信号
        min_confidence=58,          # 适度置信度
        high_atr_pct=10.0,          # 容许更大波动
        extreme_atr_pct=18.0,
        base_risk_pct=0.01,         # 基础仓位1%
        max_risk_pct=0.025,         # 最大2.5%
        volume_confirm_ratio=1.05,  # 轻微放量即可
        overextension_atr_multiple=3.0,
    ),
    "us_equity": StrategyProfile(
        asset_class="us_equity",
        min_bars=50,
        min_confidence=58,
        high_atr_pct=5.5,
        extreme_atr_pct=9.0,
        base_risk_pct=0.008,
        max_risk_pct=0.016,
        volume_confirm_ratio=1.15,
        overextension_atr_multiple=2.2,
    ),
}


class MultiAssetStrategyEngine:
    """Generate auditable signals for crypto and US stocks."""

    def generate_signal(
        self,
        rows: List[Dict],
        symbol: str,
        asset_class: AssetClass = "crypto",
        interval: str = "1d",
    ) -> Dict:
        profile = PROFILES.get(asset_class, PROFILES["crypto"])
        df = self._frame(rows)

        if len(df) < profile.min_bars:
            return self._wait(
                symbol,
                asset_class,
                interval,
                0,
                0,
                [f"有效K线数量不足：{len(df)} < {profile.min_bars}，拒绝给方向。"],
                {},
            )

        indicators = self._indicators(df)
        if not self._has_required(indicators):
            return self._wait(
                symbol,
                asset_class,
                interval,
                0,
                0,
                ["关键指标缺失或数据质量不足，拒绝给方向。"],
                indicators,
            )

        reasons: List[str] = []
        risk_notes: List[str] = []
        bull = 0
        bear = 0
        confidence = 42

        close = indicators["close"]
        atr = indicators["atr"]
        atr_pct = indicators["atr_pct"]
        is_2026_us_equity = asset_class == "us_equity"
        if is_2026_us_equity:
            reasons.append("2026美股策略：优先质量成长/AI受益顺势信号，通胀和利率粘性下避免无量追高。")

        trend_up = (
            close > indicators["sma20"]
            and indicators["sma20"] > indicators["sma50"]
            and indicators["sma50_slope"] >= 0
        )
        trend_down = (
            close < indicators["sma20"]
            and indicators["sma20"] < indicators["sma50"]
            and indicators["sma50_slope"] <= 0
        )
        long_term_bull = indicators.get("sma200") is not None and close > indicators["sma200"]
        long_term_bear = indicators.get("sma200") is not None and close < indicators["sma200"]

        if trend_up:
            bull += 2
            confidence += 12
            reasons.append("趋势：20/50均线多头排列，价格站在短中期均线上方。")
        elif trend_down:
            bear += 2
            confidence += 12
            reasons.append("趋势：20/50均线空头排列，价格低于短中期均线。")
        else:
            reasons.append("趋势：均线结构不顺，趋势优势不足。")

        if long_term_bull:
            bull += 1
            confidence += 7 if is_2026_us_equity else 5
            reasons.append("长期过滤：价格位于200均线上方。")
        elif long_term_bear and asset_class == "us_equity":
            bear += 1
            confidence += 8
            reasons.append("长期过滤：美股价格低于200均线，优先防守。")
        elif is_2026_us_equity:
            confidence -= 8
            risk_notes.append("长期过滤：缺少200均线确认，2026美股信号不放大仓位。")

        momentum_up = (
            45 <= indicators["rsi"] <= 68
            and indicators["macd_hist"] > 0
            and indicators["macd_hist_delta"] >= 0
        )
        momentum_down = (
            indicators["rsi"] <= 55
            and indicators["macd_hist"] < 0
            and indicators["macd_hist_delta"] <= 0
        )
        if momentum_up:
            bull += 2
            confidence += 12
            reasons.append("动量：RSI未过热，MACD柱体为正且改善。")
        elif momentum_down:
            bear += 2
            confidence += 12
            reasons.append("动量：MACD柱体为负且走弱，RSI缺少上行动能。")
        else:
            reasons.append("动量：RSI/MACD没有形成同向确认。")

        if indicators["adx"] >= 22:
            confidence += 6
            reasons.append(f"趋势强度：ADX {indicators['adx']:.1f}，具备一定趋势性。")
        else:
            confidence -= 8
            risk_notes.append("ADX偏低，行情可能处于震荡区，趋势策略胜率下降。")

        volume_confirmed = indicators["volume_ratio"] >= profile.volume_confirm_ratio
        if volume_confirmed:
            confidence += 8
            reasons.append("量能：当前成交量高于20期均量，信号有量能确认。")
        else:
            confidence -= 4 if asset_class == "crypto" else 12
            risk_notes.append("量能未确认，不适合激进追价。")

        if trend_up and momentum_up:
            bull += 1
            reasons.append("共振：趋势和动量同向偏多。")
        elif trend_down and momentum_down:
            bear += 1
            reasons.append("共振：趋势和动量同向偏空。")

        if indicators["adx"] >= 25 and bull != bear:
            if bull > bear:
                bull += 1
            else:
                bear += 1
            reasons.append("方向确认：ADX显示趋势信号有延续性。")

        if volume_confirmed and bull != bear:
            if bull > bear:
                bull += 1
            else:
                bear += 1
            reasons.append("方向确认：放量支持当前主导方向。")

        overbought = is_2026_us_equity and (
            indicators["rsi"] >= 74 or indicators["distance_sma20_pct"] >= 8
        )
        oversold = is_2026_us_equity and indicators["rsi"] <= 28
        if overbought:
            bull -= 1
            confidence -= 14
            risk_notes.append("短线过热或远离20均线，2026高估值环境下等待回踩。")
        if oversold:
            bear -= 1
            confidence -= 10
            risk_notes.append("短线超卖，继续追空容易遭遇反抽。")

        overextended = (
            is_2026_us_equity and
            indicators["distance_sma20_pct"] >= profile.overextension_atr_multiple * max(1.0, atr_pct)
        )
        if overextended:
            confidence -= 12
            risk_notes.append("价格偏离20均线过远，等待回踩/反抽确认更务实。")

        if atr_pct >= profile.extreme_atr_pct * 1.3:
            return self._wait(
                symbol,
                asset_class,
                interval,
                20,
                max(0, min(55, confidence)),
                reasons + risk_notes + [f"ATR% {atr_pct:.2f} 已进入极端波动区，拒绝给追价方向。"],
                indicators,
            )
        if atr_pct >= profile.high_atr_pct:
            confidence -= 10
            risk_notes.append(f"ATR% {atr_pct:.2f} 偏高，仓位必须降级。")

        gap = abs(bull - bear)
        strength = int(max(0, min(100, round(gap / 6 * 100))))
        confidence = int(max(0, min(92, confidence)))
        risk_pct = self._risk_pct(profile, confidence, atr_pct)

        long_threshold = 5 if asset_class == "crypto" else 4
        short_threshold = 5 if asset_class == "crypto" else 4
        long_ready = bull >= long_threshold and gap >= 2 and confidence >= profile.min_confidence
        long_label = "谨慎做多"
        if is_2026_us_equity:
            confirmed_quality_long = long_term_bull and (
                volume_confirmed or (trend_up and momentum_up and confidence >= profile.min_confidence + 8)
            )
            tactical_trend_long = (
                trend_up and
                momentum_up and
                indicators["adx"] >= 25 and
                confidence >= profile.min_confidence + 8
            )
            long_ready = (
                long_ready and
                not overbought and
                (confirmed_quality_long or tactical_trend_long)
            )
            long_label = "质量顺势多" if long_term_bull else "战术顺势多"

        if long_ready:
            stop = close - atr * (2.2 if asset_class == "crypto" else 1.7)
            target = close + atr * (3.0 if asset_class == "crypto" else 2.3)
            return self._result(
                symbol,
                asset_class,
                interval,
                "CAUTIOUS_LONG",
                long_label,
                "signal-buy",
                strength,
                confidence,
                risk_pct,
                stop,
                target,
                reasons + risk_notes + ["执行：只允许小仓顺势试多，跌破失效位必须退出。"],
                indicators,
            )

        if bear >= short_threshold and gap >= 2 and confidence >= profile.min_confidence:
            stop = close + atr * (2.0 if asset_class == "crypto" else 1.6)
            target = close - atr * (2.6 if asset_class == "crypto" else 2.1)
            return self._result(
                symbol,
                asset_class,
                interval,
                "RISK_OFF",
                "减仓/避险",
                "signal-sell",
                strength,
                confidence,
                risk_pct,
                stop,
                target,
                reasons + risk_notes + ["执行：优先降低风险暴露；若做空，需等待反抽失败。"],
                indicators,
            )

        return self._wait(
            symbol,
            asset_class,
            interval,
            min(strength, 55),
            min(confidence, 67),
            reasons + risk_notes + ["结论：优势不够清晰，等待趋势、动量、量能至少两项同步。"],
            indicators,
        )

    def _frame(self, rows: List[Dict]) -> pd.DataFrame:
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        for column in ["open", "high", "low", "close", "volume"]:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

    def _indicators(self, df: pd.DataFrame) -> Dict:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df.get("volume", pd.Series([0] * len(df)))
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_signal = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - macd_signal
        atr = self._atr(high, low, close, 14)
        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        latest_close = float(close.iloc[-1])
        latest_atr = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else None
        volume_avg20 = volume.rolling(20).mean()
        return {
            "close": latest_close,
            "sma20": self._last(sma20),
            "sma50": self._last(sma50),
            "sma200": self._last(sma200),
            "sma50_slope": self._last(sma50) - self._nth_from_end(sma50, 5) if self._last(sma50) is not None and self._nth_from_end(sma50, 5) is not None else 0,
            "rsi": self._rsi(close, 14),
            "macd": self._last(macd),
            "macd_hist": self._last(macd_hist),
            "macd_hist_delta": self._last(macd_hist) - self._nth_from_end(macd_hist, 3) if self._last(macd_hist) is not None and self._nth_from_end(macd_hist, 3) is not None else 0,
            "adx": self._adx(high, low, close, 14),
            "stoch_k": self._stochastic(high, low, close, 14),
            "atr": latest_atr,
            "atr_pct": latest_atr / latest_close * 100 if latest_atr and latest_close else None,
            "volume": float(volume.iloc[-1]) if len(volume) else 0.0,
            "volume_avg20": self._last(volume_avg20),
            "volume_ratio": float(volume.iloc[-1]) / self._last(volume_avg20) if self._last(volume_avg20) else 0,
            "distance_sma20_pct": abs((latest_close - self._last(sma20)) / self._last(sma20) * 100) if self._last(sma20) else 0,
        }

    def _has_required(self, indicators: Dict) -> bool:
        required = ["close", "sma20", "sma50", "rsi", "macd_hist", "adx", "atr", "atr_pct"]
        return all(indicators.get(key) is not None and np.isfinite(indicators.get(key)) for key in required)

    def _last(self, series: pd.Series) -> Optional[float]:
        value = series.iloc[-1]
        return float(value) if pd.notna(value) else None

    def _nth_from_end(self, series: pd.Series, offset: int) -> Optional[float]:
        if len(series) <= offset:
            return None
        value = series.iloc[-1 - offset]
        return float(value) if pd.notna(value) else None

    def _rsi(self, close: pd.Series, period: int) -> Optional[float]:
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        value = 100 - (100 / (1 + rs.iloc[-1])) if pd.notna(rs.iloc[-1]) else 100.0
        return float(value)

    def _atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def _adx(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> Optional[float]:
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        atr = self._atr(high, low, close, period)
        plus_di = 100 * plus_dm.rolling(period).sum() / atr.replace(0, np.nan)
        minus_di = 100 * minus_dm.rolling(period).sum() / atr.replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        return self._last(dx.rolling(period).mean())

    def _stochastic(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> Optional[float]:
        high_max = high.rolling(period).max().iloc[-1]
        low_min = low.rolling(period).min().iloc[-1]
        if pd.isna(high_max) or pd.isna(low_min) or high_max == low_min:
            return None
        return float((close.iloc[-1] - low_min) / (high_max - low_min) * 100)

    def _risk_pct(self, profile: StrategyProfile, confidence: int, atr_pct: float) -> float:
        scale = max(0.35, min(1.0, (confidence - 45) / 40))
        volatility_penalty = 0.6 if atr_pct >= profile.high_atr_pct else 1.0
        return round(min(profile.max_risk_pct, profile.base_risk_pct * scale * volatility_penalty), 4)

    def _wait(self, symbol, asset_class, interval, strength, confidence, reasons, indicators):
        return self._result(
            symbol,
            asset_class,
            interval,
            "WAIT_CONFIRMATION",
            "等待确认",
            "signal-hold",
            strength,
            confidence,
            0.0,
            None,
            None,
            reasons,
            indicators,
        )

    def _result(
        self,
        symbol,
        asset_class,
        interval,
        action,
        label,
        class_name,
        strength,
        confidence,
        risk_pct,
        stop_loss,
        take_profit,
        reasons,
        indicators,
    ) -> Dict:
        result = {
            "symbol": symbol,
            "asset_class": asset_class,
            "interval": interval,
            "action": action,
            "label": label,
            "recommendation": label,
            "class_name": class_name,
            "strength": int(strength),
            "confidence": int(confidence),
            "position_risk_pct": risk_pct,
            "stop_loss": round(stop_loss, 6) if stop_loss is not None else None,
            "take_profit": round(take_profit, 6) if take_profit is not None else None,
            "reasons": reasons,
            "indicators": {
                key: round(value, 6) if isinstance(value, (float, int)) and np.isfinite(value) else value
                for key, value in indicators.items()
            },
            "disclaimer": "研究信号，不是投资建议；必须结合回测、流动性、事件风险和个人风险承受能力。",
        }
        if asset_class == "us_equity":
            result["strategy_regime"] = {
                "name": "2026H2_QUALITY_AI_EARNINGS",
                "valid_until": "2026-12-31",
                "description": "优先质量成长、AI受益顺势、量能确认；通胀和利率粘性下避免无量追高。",
                "requires": ["long_term_trend", "volume_confirmation", "not_overheated"],
            }
        return result
