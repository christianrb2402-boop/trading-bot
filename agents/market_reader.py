from __future__ import annotations

import logging

from core.database import Database
from data.market_data_service import MarketDataService, MarketSnapshot


logger = logging.getLogger(__name__)


class MarketReaderAgent:
    """Primer agente: solo lectura de mercado y persistencia de snapshots."""

    def __init__(self, market_data_service: MarketDataService, database: Database) -> None:
        self._market_data_service = market_data_service
        self._database = database

    def run(self, symbol: str, interval: str) -> MarketSnapshot:
        snapshot = self._market_data_service.read_snapshot(symbol, interval)
        self._database.insert_market_snapshot(
            symbol=snapshot.symbol,
            interval=snapshot.interval,
            price=snapshot.price,
            open_price=snapshot.open_price,
            high_price=snapshot.high_price,
            low_price=snapshot.low_price,
            close_price=snapshot.close_price,
            volume=snapshot.volume,
            source_time=snapshot.source_time,
        )
        self._database.log_event(
            "market_read",
            f"Snapshot guardado para {snapshot.symbol} en {snapshot.interval}",
        )
        logger.info(
            "Market snapshot stored",
            extra={"event": {"symbol": snapshot.symbol, "interval": snapshot.interval}},
        )
        return snapshot

