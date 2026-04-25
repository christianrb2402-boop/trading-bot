from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import time
from typing import Sequence

from agents.delta_agent import DeltaAgent
from config.settings import Settings
from core.database import Database, TradeRecord
from data.binance_market_data import BinanceMarketDataService, Candle


logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class PaperTradeStats:
    symbol: str
    closed_trades: int
    open_trades: int
    winrate: float
    cumulative_pnl_pct: float
    max_drawdown_pct: float


class PaperTrader:
    def __init__(
        self,
        *,
        database: Database,
        market_data_service: BinanceMarketDataService,
        delta_agent: DeltaAgent,
        settings: Settings,
    ) -> None:
        self._database = database
        self._market_data_service = market_data_service
        self._delta_agent = delta_agent
        self._settings = settings
        self._last_processed_open_time: dict[str, str] = {}

    def run(
        self,
        *,
        symbols: Sequence[str],
        timeframe: str,
        max_cycles: int | None = None,
    ) -> None:
        cycle = 0
        while True:
            cycle += 1
            logger.info(
                "Paper trading cycle started",
                extra={
                    "event": "paper_trade_cycle",
                    "context": {"cycle": cycle, "symbols": list(symbols), "timeframe": timeframe},
                },
            )

            for symbol in symbols:
                self._process_symbol(symbol=symbol, timeframe=timeframe)

            if max_cycles is not None and cycle >= max_cycles:
                logger.info(
                    "Paper trading finished by max cycles",
                    extra={"event": "paper_trade_shutdown", "context": {"cycle": cycle}},
                )
                return

            time.sleep(self._settings.paper_poll_seconds)

    def _process_symbol(self, *, symbol: str, timeframe: str) -> None:
        closed_candles = self._market_data_service.fetch_latest_closed_candles(symbol=symbol, timeframe=timeframe, limit=2)
        if len(closed_candles) < 2:
            return

        latest_candle = closed_candles[-1]
        if self._last_processed_open_time.get(symbol) == latest_candle.open_time:
            return

        insert_result = self._database.insert_candles(closed_candles)
        logger.info(
            "Paper trader synced candles",
            extra={
                "event": "paper_trade_sync",
                "context": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "inserted": insert_result.inserted,
                    "duplicates": insert_result.duplicates,
                    "open_time": latest_candle.open_time,
                },
            },
        )

        open_trade = self._database.get_open_trade(symbol)
        if open_trade:
            self._maybe_close_trade(symbol=symbol, latest_candle=latest_candle, previous_candle=closed_candles[-2], trade=open_trade)

        signal = self._delta_agent.evaluate(symbol=symbol, timeframe=timeframe)
        if signal["signal"] and signal["direction"] == "LONG" and not self._database.get_open_trade(symbol):
            self._open_trade(symbol=symbol, candle=latest_candle)

        stats = self._build_stats(symbol)
        print(
            f"Paper {symbol}: closed_trades={stats.closed_trades} open_trades={stats.open_trades} "
            f"winrate={stats.winrate}% pnl={stats.cumulative_pnl_pct}% drawdown={stats.max_drawdown_pct}%"
        )
        self._last_processed_open_time[symbol] = latest_candle.open_time

    def _open_trade(self, *, symbol: str, candle: Candle) -> None:
        entry_price = candle.close * (1 + self._settings.paper_slippage_pct / 100)
        entry_price *= 1 + self._settings.paper_commission_pct / 100
        trade_id = self._database.insert_trade(symbol=symbol, entry_time=candle.close_time, entry_price=round(entry_price, 6))
        logger.info(
            "Paper trade opened",
            extra={
                "event": "paper_trade_open",
                "context": {
                    "symbol": symbol,
                    "trade_id": trade_id,
                    "entry_time": candle.close_time,
                    "entry_price": round(entry_price, 6),
                },
            },
        )

    def _maybe_close_trade(
        self,
        *,
        symbol: str,
        latest_candle: Candle,
        previous_candle: Candle,
        trade: TradeRecord,
    ) -> None:
        stop_price = trade.entry_price * (1 - self._settings.paper_stop_loss_pct / 100)
        take_profit_price = trade.entry_price * (1 + self._settings.paper_take_profit_pct / 100)

        if latest_candle.low <= stop_price:
            self._close_trade(trade=trade, exit_time=latest_candle.close_time, raw_exit_price=stop_price, exit_reason="STOP_LOSS")
            return

        if latest_candle.high >= take_profit_price:
            self._close_trade(
                trade=trade,
                exit_time=latest_candle.close_time,
                raw_exit_price=take_profit_price,
                exit_reason="TAKE_PROFIT",
            )
            return

        if latest_candle.close < previous_candle.close:
            self._close_trade(
                trade=trade,
                exit_time=latest_candle.close_time,
                raw_exit_price=latest_candle.close,
                exit_reason="DELTA_CONTRACTION",
            )

    def _close_trade(
        self,
        *,
        trade: TradeRecord,
        exit_time: str,
        raw_exit_price: float,
        exit_reason: str,
    ) -> None:
        exit_price = raw_exit_price * (1 - self._settings.paper_commission_pct / 100)
        pnl_pct = ((exit_price - trade.entry_price) / trade.entry_price) * 100
        duration = self._duration_minutes(trade.entry_time, exit_time)
        self._database.close_trade(
            trade_id=trade.id,
            exit_time=exit_time,
            exit_price=round(exit_price, 6),
            pnl_pct=round(pnl_pct, 6),
            duration=duration,
            exit_reason=exit_reason,
        )
        logger.info(
            "Paper trade closed",
            extra={
                "event": "paper_trade_close",
                "context": {
                    "symbol": trade.symbol,
                    "trade_id": trade.id,
                    "exit_time": exit_time,
                    "exit_price": round(exit_price, 6),
                    "pnl_pct": round(pnl_pct, 6),
                    "duration": duration,
                    "exit_reason": exit_reason,
                },
            },
        )

    def _build_stats(self, symbol: str) -> PaperTradeStats:
        trades = self._database.get_closed_trades(symbol)
        open_trade = self._database.get_open_trade(symbol)
        if not trades:
            return PaperTradeStats(
                symbol=symbol,
                closed_trades=0,
                open_trades=1 if open_trade else 0,
                winrate=0.0,
                cumulative_pnl_pct=0.0,
                max_drawdown_pct=0.0,
            )

        total_trades = len(trades)
        wins = sum(1 for trade in trades if (trade.pnl_pct or 0.0) > 0)
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0

        for trade in trades:
            cumulative += trade.pnl_pct or 0.0
            peak = max(peak, cumulative)
            max_drawdown = min(max_drawdown, cumulative - peak)

        return PaperTradeStats(
            symbol=symbol,
            closed_trades=total_trades,
            open_trades=1 if open_trade else 0,
            winrate=round((wins / total_trades) * 100, 2),
            cumulative_pnl_pct=round(cumulative, 6),
            max_drawdown_pct=round(max_drawdown, 6),
        )

    @staticmethod
    def _duration_minutes(entry_time: str, exit_time: str) -> int:
        entry_dt = datetime.fromisoformat(entry_time)
        exit_dt = datetime.fromisoformat(exit_time)
        return max(int((exit_dt - entry_dt).total_seconds() // 60), 0)
