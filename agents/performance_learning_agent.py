from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings
from core.database import Database


@dataclass(slots=True, frozen=True)
class LearningAdjustment:
    setup_signature: str
    sample_size: int
    vote: str
    confidence_adjustment: float
    reason: str

    def as_dict(self) -> dict[str, str | int | float]:
        return {
            "setup_signature": self.setup_signature,
            "sample_size": self.sample_size,
            "vote": self.vote,
            "confidence_adjustment": self.confidence_adjustment,
            "reason": self.reason,
        }


class PerformanceLearningAgent:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    def assess(self, *, setup_signature: str, direction: str) -> LearningAdjustment:
        stats = self._database.get_similar_closed_trade_stats(setup_signature=setup_signature, direction=direction)
        sample_size = int(stats["total"] or 0)
        if sample_size < self._settings.performance_learning_min_sample:
            return LearningAdjustment(
                setup_signature=setup_signature,
                sample_size=sample_size,
                vote="HOLD",
                confidence_adjustment=0.0,
                reason="insufficient sample size to adjust confidence",
            )

        winrate = float(stats["winrate"] or 0.0)
        average_pnl_pct = float(stats["average_pnl_pct"] or 0.0)
        if winrate >= 55 and average_pnl_pct > 0:
            return LearningAdjustment(
                setup_signature=setup_signature,
                sample_size=sample_size,
                vote="BOOST",
                confidence_adjustment=0.1,
                reason=f"historically favorable setup with winrate {round(winrate, 2)}% and average pnl pct {round(average_pnl_pct, 6)}",
            )
        if winrate <= 45 or average_pnl_pct < 0:
            return LearningAdjustment(
                setup_signature=setup_signature,
                sample_size=sample_size,
                vote="REDUCE",
                confidence_adjustment=-0.1,
                reason=f"historically weak setup with winrate {round(winrate, 2)}% and average pnl pct {round(average_pnl_pct, 6)}",
            )
        return LearningAdjustment(
            setup_signature=setup_signature,
            sample_size=sample_size,
            vote="HOLD",
            confidence_adjustment=0.0,
            reason="historical setup was mixed, so confidence was left unchanged",
        )
