from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from core.database import Database, SimulatedTradeRecord, StrategyInsightRecord


@dataclass(slots=True, frozen=True)
class SetupPerformance:
    setup_key: str
    trade_count: int
    winrate: float
    average_pnl: float
    average_pnl_pct: float

    def as_dict(self) -> dict[str, str | int | float]:
        return {
            "setup_key": self.setup_key,
            "trade_count": self.trade_count,
            "winrate": self.winrate,
            "average_pnl": self.average_pnl,
            "average_pnl_pct": self.average_pnl_pct,
        }


class PerformanceAnalyzer:
    def __init__(self, database: Database) -> None:
        self._database = database

    def refresh(self) -> dict[str, object]:
        closed_trades = self._database.get_closed_simulated_trades()
        report = self._build_report(closed_trades)
        self._database.replace_strategy_insights(report["strategy_insights"])
        return report

    def _build_report(self, closed_trades: Sequence[SimulatedTradeRecord]) -> dict[str, object]:
        total_trades = len(closed_trades)
        wins = sum(1 for trade in closed_trades if trade.outcome == "WIN")
        losses = sum(1 for trade in closed_trades if trade.outcome in {"LOSS", "GROSS_WIN_NET_LOSS"})
        breakeven = sum(1 for trade in closed_trades if trade.outcome == "BREAKEVEN")
        gross_win_net_loss = sum(1 for trade in closed_trades if trade.outcome == "GROSS_WIN_NET_LOSS")
        average_pnl = sum((trade.pnl or 0.0) for trade in closed_trades) / total_trades if total_trades else 0.0
        best_setups = self._aggregate_by_key(closed_trades, key_name="setup_signature")
        trend_performance = self._aggregate_by_key(closed_trades, key_name="entry_trend")
        volatility_performance = self._aggregate_by_key(closed_trades, key_name="entry_volatility_bucket")
        momentum_performance = self._aggregate_by_key(closed_trades, key_name="entry_momentum_bucket")
        volume_performance = self._aggregate_by_key(closed_trades, key_name="entry_volume_regime")

        best_top = sorted(best_setups, key=lambda item: (item.average_pnl, item.winrate, item.trade_count), reverse=True)[:3]
        worst_top = sorted(best_setups, key=lambda item: (item.average_pnl, item.winrate, -item.trade_count))[:3]
        insights = self._build_strategy_insights(
            best_setups=best_setups,
            trend_performance=trend_performance,
            volatility_performance=volatility_performance,
            momentum_performance=momentum_performance,
            volume_performance=volume_performance,
        )

        return {
            "total_trades": total_trades,
            "winrate": round((wins / total_trades) * 100, 2) if total_trades else 0.0,
            "average_pnl": round(average_pnl, 6),
            "best_setup": best_top[0].as_dict() if best_top else None,
            "worst_setup": worst_top[0].as_dict() if worst_top else None,
            "best_setups": [item.as_dict() for item in best_top],
            "worst_setups": [item.as_dict() for item in worst_top],
            "performance_by_trend": [item.as_dict() for item in trend_performance],
            "performance_by_volatility": [item.as_dict() for item in volatility_performance],
            "performance_by_momentum": [item.as_dict() for item in momentum_performance],
            "performance_by_volume": [item.as_dict() for item in volume_performance],
            "pnl_distribution": {
                "wins": wins,
                "losses": losses,
                "breakeven": breakeven,
                "gross_win_net_loss": gross_win_net_loss,
            },
            "trade_distribution_by_regime": {
                "trend": self._distribution_rows(trend_performance),
                "volatility": self._distribution_rows(volatility_performance),
                "momentum": self._distribution_rows(momentum_performance),
                "volume": self._distribution_rows(volume_performance),
            },
            "strategy_insights": insights,
            "last_trades": closed_trades[-5:],
        }

    def _aggregate_by_key(self, trades: Sequence[SimulatedTradeRecord], *, key_name: str) -> list[SetupPerformance]:
        grouped: dict[str, list[SimulatedTradeRecord]] = {}
        for trade in trades:
            key_value = getattr(trade, key_name) or "UNKNOWN"
            grouped.setdefault(str(key_value), []).append(trade)

        rows: list[SetupPerformance] = []
        for key_value, group in grouped.items():
            wins = sum(1 for trade in group if trade.outcome == "WIN")
            average_pnl = sum((trade.pnl or 0.0) for trade in group) / len(group)
            average_pnl_pct = sum((trade.pnl_pct or 0.0) for trade in group) / len(group)
            rows.append(
                SetupPerformance(
                    setup_key=key_value,
                    trade_count=len(group),
                    winrate=round((wins / len(group)) * 100, 2) if group else 0.0,
                    average_pnl=round(average_pnl, 6),
                    average_pnl_pct=round(average_pnl_pct, 6),
                )
            )
        return sorted(rows, key=lambda item: (item.trade_count, item.average_pnl), reverse=True)

    def _build_strategy_insights(
        self,
        *,
        best_setups: Sequence[SetupPerformance],
        trend_performance: Sequence[SetupPerformance],
        volatility_performance: Sequence[SetupPerformance],
        momentum_performance: Sequence[SetupPerformance],
        volume_performance: Sequence[SetupPerformance],
    ) -> list[StrategyInsightRecord]:
        timestamp = datetime.now(timezone.utc).isoformat()
        insights: list[StrategyInsightRecord] = []

        for item in sorted(best_setups, key=lambda row: (row.average_pnl, row.winrate), reverse=True)[:3]:
            insights.append(
                StrategyInsightRecord(
                    timestamp=timestamp,
                    insight_type="BEST_SETUP",
                    setup_key=item.setup_key,
                    trade_count=item.trade_count,
                    winrate=item.winrate,
                    average_pnl=item.average_pnl,
                    summary=f"Best setup so far: {item.setup_key} with winrate {item.winrate}% and average pnl {item.average_pnl}.",
                )
            )

        for item in sorted(best_setups, key=lambda row: (row.average_pnl, row.winrate))[:3]:
            insights.append(
                StrategyInsightRecord(
                    timestamp=timestamp,
                    insight_type="WORST_SETUP",
                    setup_key=item.setup_key,
                    trade_count=item.trade_count,
                    winrate=item.winrate,
                    average_pnl=item.average_pnl,
                    summary=f"Worst setup so far: {item.setup_key} with winrate {item.winrate}% and average pnl {item.average_pnl}.",
                )
            )

        insights.extend(self._build_dimension_insights(timestamp=timestamp, dimension="TREND", rows=trend_performance))
        insights.extend(self._build_dimension_insights(timestamp=timestamp, dimension="VOLATILITY", rows=volatility_performance))
        insights.extend(self._build_dimension_insights(timestamp=timestamp, dimension="MOMENTUM", rows=momentum_performance))
        insights.extend(self._build_dimension_insights(timestamp=timestamp, dimension="VOLUME", rows=volume_performance))
        return insights

    @staticmethod
    def _distribution_rows(rows: Sequence[SetupPerformance]) -> list[dict[str, str | int | float]]:
        return [
            {
                "regime": row.setup_key,
                "trade_count": row.trade_count,
                "winrate": row.winrate,
                "average_pnl": row.average_pnl,
            }
            for row in rows
        ]

    @staticmethod
    def _build_dimension_insights(
        *,
        timestamp: str,
        dimension: str,
        rows: Sequence[SetupPerformance],
    ) -> list[StrategyInsightRecord]:
        if not rows:
            return []
        best = max(rows, key=lambda item: (item.average_pnl, item.winrate))
        worst = min(rows, key=lambda item: (item.average_pnl, item.winrate))
        return [
            StrategyInsightRecord(
                timestamp=timestamp,
                insight_type=f"{dimension}_WINNER",
                setup_key=best.setup_key,
                trade_count=best.trade_count,
                winrate=best.winrate,
                average_pnl=best.average_pnl,
                summary=f"{dimension} condition {best.setup_key} has the strongest results with winrate {best.winrate}% and average pnl {best.average_pnl}.",
            ),
            StrategyInsightRecord(
                timestamp=timestamp,
                insight_type=f"{dimension}_LOSER",
                setup_key=worst.setup_key,
                trade_count=worst.trade_count,
                winrate=worst.winrate,
                average_pnl=worst.average_pnl,
                summary=f"{dimension} condition {worst.setup_key} has the weakest results with winrate {worst.winrate}% and average pnl {worst.average_pnl}.",
            ),
        ]
