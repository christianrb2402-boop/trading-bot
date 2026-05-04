from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class MarketStateAssessment:
    market_state: str
    confidence: float
    volatility_state: str
    trend_state: str
    volume_state: str
    recommended_risk_mode: str
    reason: str
    risk_flags: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "market_state": self.market_state,
            "confidence": self.confidence,
            "volatility_state": self.volatility_state,
            "trend_state": self.trend_state,
            "volume_state": self.volume_state,
            "recommended_risk_mode": self.recommended_risk_mode,
            "reason": self.reason,
            "risk_flags": self.risk_flags,
        }


class MarketStateAgent:
    def assess(
        self,
        *,
        features: dict[str, object],
        market_context: dict[str, object],
        is_stale: bool,
        data_quality_score: float,
        recent_drawdown_pct: float,
    ) -> MarketStateAssessment:
        trend = str(market_context.get("trend_direction", "SIDEWAYS"))
        regime = str(market_context.get("market_regime", "RANGING"))
        volatility_state = str(market_context.get("volatility_regime", "LOW"))
        volume_state = "SPIKE" if bool(features.get("volume_spike", False)) else str(market_context.get("volume_regime", "NORMAL"))
        compression_state = str(features.get("compression_state", market_context.get("compression_state", "STABLE")))
        relative_volume = float(features.get("relative_volume", 0.0))
        atr_pct = float(features.get("atr_pct", market_context.get("volatility_pct", 0.0)))
        roc = float(features.get("roc", 0.0))
        risk_flags: list[str] = []

        if is_stale:
            risk_flags.append("data_stale")
        if data_quality_score < 0.55:
            risk_flags.append("low_data_quality")
        if recent_drawdown_pct <= -3.0:
            risk_flags.append("recent_drawdown")

        if is_stale:
            market_state = "UNKNOWN"
            risk_mode = "DO_NOT_TRADE"
        elif regime == "TRENDING" and trend == "UP" and volume_state == "SPIKE":
            market_state = "BREAKOUT_CONFIRMED" if roc > 0.2 else "TREND_UP"
            risk_mode = "BALANCED"
        elif regime == "TRENDING" and trend == "DOWN" and volume_state == "SPIKE":
            market_state = "BREAKOUT_CONFIRMED" if roc < -0.2 else "TREND_DOWN"
            risk_mode = "BALANCED"
        elif compression_state == "COMPRESSION":
            market_state = "COMPRESSION"
            risk_mode = "CONSERVATIVE"
        elif volatility_state == "HIGH":
            market_state = "HIGH_VOLATILITY"
            risk_mode = "CONSERVATIVE"
        elif volatility_state == "LOW":
            market_state = "LOW_VOLATILITY"
            risk_mode = "CONSERVATIVE"
        elif trend == "SIDEWAYS" and atr_pct < 0.1:
            market_state = "CHOPPY"
            risk_mode = "DO_NOT_TRADE"
        elif trend == "SIDEWAYS":
            market_state = "RANGE"
            risk_mode = "CONSERVATIVE"
        else:
            market_state = "UNKNOWN"
            risk_mode = "DO_NOT_TRADE"

        if relative_volume >= 2.5 and abs(roc) >= max(atr_pct, 0.2):
            market_state = "NEWSLIKE_SPIKE"
            risk_mode = "CONSERVATIVE"
            risk_flags.append("newslike_spike")

        if recent_drawdown_pct <= -5.0:
            risk_mode = "CAPITAL_PROTECTION"
        elif data_quality_score < 0.55 and risk_mode != "DO_NOT_TRADE":
            risk_mode = "CONSERVATIVE"

        confidence = min(1.0, max(0.0, float(market_context.get("context_score", 0.0)) + (0.1 if volume_state == "SPIKE" else 0.0)))
        reason = (
            f"market state {market_state} with trend {trend}, volatility {volatility_state}, "
            f"volume {volume_state}, compression {compression_state}, drawdown {round(recent_drawdown_pct, 4)}%"
        )
        return MarketStateAssessment(
            market_state=market_state,
            confidence=round(confidence, 6),
            volatility_state=volatility_state,
            trend_state=trend,
            volume_state=volume_state,
            recommended_risk_mode=risk_mode,
            reason=reason,
            risk_flags=tuple(risk_flags),
        )

