from __future__ import annotations

from dataclasses import dataclass
import logging

from core.database import Database, SimulatedTradeRecord, StoredCandle


logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class SimulatedTradeStats:
    symbol: str
    total_trades: int
    winrate: float
    cumulative_pnl: float
    drawdown: float


class SimulatedTradeTracker:
    def __init__(self, database: Database, exit_after_candles: int) -> None:
        self._database = database
        self._exit_after_candles = exit_after_candles

    def process_signal(
        self,
        *,
        symbol: str,
        timeframe: str,
        signal: dict[str, str | float | bool],
        latest_candle: StoredCandle,
    ) -> None:
        open_trade = self._database.get_open_simulated_trade(symbol)
        if open_trade:
            self._maybe_close_trade(symbol=symbol, timeframe=timeframe, trade=open_trade)

        signal_type = str(signal["signal_type"])
        if signal_type == "LONG" and not self._database.get_open_simulated_trade(symbol):
            self._open_trade(symbol=symbol, latest_candle=latest_candle)

    def build_stats(self, symbol: str) -> SimulatedTradeStats:
        trades = self._database.get_closed_simulated_trades(symbol)
        if not trades:
            return SimulatedTradeStats(symbol=symbol, total_trades=0, winrate=0.0, cumulative_pnl=0.0, drawdown=0.0)

        total_trades = len(trades)
        wins = sum(1 for trade in trades if (trade.pnl or 0.0) > 0)
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0

        for trade in trades:
            cumulative += trade.pnl or 0.0
            peak = max(peak, cumulative)
            max_drawdown = min(max_drawdown, cumulative - peak)

        return SimulatedTradeStats(
            symbol=symbol,
            total_trades=total_trades,
            winrate=round((wins / total_trades) * 100, 2),
            cumulative_pnl=round(cumulative, 6),
            drawdown=round(max_drawdown, 6),
        )

    def _open_trade(self, *, symbol: str, latest_candle: StoredCandle) -> None:
        trade_id = self._database.insert_simulated_trade(
            symbol=symbol,
            entry_price=latest_candle.close,
            direction="LONG",
            timestamp_entry=latest_candle.close_time,
        )
        logger.info(
            "Simulated trade opened",
            extra={
                "event": "trade_simulation_open",
                "context": {
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "entry_price": latest_candle.close,
                    "timestamp_entry": latest_candle.close_time,
                    "direction": "LONG",
                },
            },
        )

    def _maybe_close_trade(self, *, symbol: str, timeframe: str, trade: SimulatedTradeRecord) -> None:
        future_candles = self._database.get_candles_after_close_time(
            symbol=symbol,
            timeframe=timeframe,
            close_time=trade.timestamp_entry,
            limit=self._exit_after_candles,
        )
        if len(future_candles) < self._exit_after_candles:
            return

        exit_candle = future_candles[-1]
        pnl = ((exit_candle.close - trade.entry_price) / trade.entry_price) * 100
        self._database.close_simulated_trade(
            trade_id=trade.id,
            exit_price=exit_candle.close,
            pnl=round(pnl, 6),
            timestamp_exit=exit_candle.close_time,
        )
        logger.info(
            "Simulated trade closed",
            extra={
                "event": "trade_simulation_close",
                "context": {
                    "trade_id": trade.id,
                    "symbol": symbol,
                    "entry_price": trade.entry_price,
                    "exit_price": exit_candle.close,
                    "pnl": round(pnl, 6),
                    "timestamp_exit": exit_candle.close_time,
                },
            },
        )
