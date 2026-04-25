from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Iterator, Sequence

from core.exceptions import DatabaseError

if TYPE_CHECKING:
    from data.binance_market_data import Candle


@dataclass(slots=True, frozen=True)
class InsertResult:
    inserted: int
    duplicates: int


@dataclass(slots=True, frozen=True)
class UpsertResult:
    inserted: int
    updated: int


@dataclass(slots=True, frozen=True)
class StoredCandle:
    symbol: str
    timeframe: str
    open_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: str


@dataclass(slots=True, frozen=True)
class SignalEvaluationRecord:
    agent_name: str
    symbol: str
    timeframe: str
    signal_time: str
    direction: str
    horizon_candles: int
    entry_price: float
    k_value: float
    max_favorable_return: float
    min_return: float
    close_return: float
    is_positive: bool


@dataclass(slots=True, frozen=True)
class TradeRecord:
    id: int
    symbol: str
    entry_time: str
    entry_price: float
    exit_time: str | None
    exit_price: float | None
    pnl_pct: float | None
    duration: int | None
    exit_reason: str | None


class Database:
    def __init__(self, sqlite_path: Path) -> None:
        self._db_path = sqlite_path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=MEMORY;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            yield conn
            conn.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(f"SQLite error: {exc}") from exc
        finally:
            if "conn" in locals():
                conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    open_time TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    close_time TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, timeframe, open_time)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candles_symbol_timeframe_open_time
                ON candles (symbol, timeframe, open_time)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_evaluation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    signal_time TEXT NOT NULL,
                    direction TEXT NOT NULL DEFAULT 'LONG',
                    horizon_candles INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    k_value REAL NOT NULL,
                    max_favorable_return REAL NOT NULL,
                    min_return REAL NOT NULL,
                    close_return REAL NOT NULL,
                    is_positive INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(agent_name, symbol, timeframe, signal_time, horizon_candles)
                )
                """
            )
            self._ensure_column(
                conn=conn,
                table_name="signal_evaluation",
                column_name="direction",
                column_sql="TEXT NOT NULL DEFAULT 'LONG'",
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_signal_evaluation_lookup
                ON signal_evaluation (agent_name, symbol, timeframe, horizon_candles)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    entry_time TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_time TEXT,
                    exit_price REAL,
                    pnl_pct REAL,
                    duration INTEGER,
                    exit_reason TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trades_symbol_entry_time
                ON trades (symbol, entry_time)
                """
            )

    def insert_candles(self, candles: Sequence["Candle"]) -> InsertResult:
        inserted = 0
        duplicates = 0
        created_at = datetime.now(timezone.utc).isoformat()

        with self.connection() as conn:
            for candle in candles:
                cursor = conn.execute(
                    """
                    INSERT INTO candles (
                        symbol,
                        timeframe,
                        open_time,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        close_time,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, timeframe, open_time) DO NOTHING
                    """,
                    (
                        candle.symbol,
                        candle.timeframe,
                        candle.open_time,
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close,
                        candle.volume,
                        candle.close_time,
                        created_at,
                    ),
                )
                if cursor.rowcount == 1:
                    inserted += 1
                else:
                    duplicates += 1

        return InsertResult(inserted=inserted, duplicates=duplicates)

    def count_candles(self, symbol: str, timeframe: str) -> int:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM candles
                WHERE symbol = ? AND timeframe = ?
                """,
                (symbol, timeframe),
            ).fetchone()
        return int(row["total"])

    def get_recent_candles(self, symbol: str, timeframe: str, limit: int = 2) -> list[StoredCandle]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, timeframe, open_time, open, high, low, close, volume, close_time
                FROM candles
                WHERE symbol = ? AND timeframe = ?
                ORDER BY open_time DESC
                LIMIT ?
                """,
                (symbol, timeframe, limit),
            ).fetchall()

        ordered_rows = list(reversed(rows))
        return [
            StoredCandle(
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                open_time=row["open_time"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                close_time=row["close_time"],
            )
            for row in ordered_rows
        ]

    def get_candles(self, symbol: str, timeframe: str) -> list[StoredCandle]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, timeframe, open_time, open, high, low, close, volume, close_time
                FROM candles
                WHERE symbol = ? AND timeframe = ?
                ORDER BY open_time ASC
                """,
                (symbol, timeframe),
            ).fetchall()

        return [
            StoredCandle(
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                open_time=row["open_time"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                close_time=row["close_time"],
            )
            for row in rows
        ]

    def upsert_signal_evaluations(self, evaluations: Sequence[SignalEvaluationRecord]) -> UpsertResult:
        inserted = 0
        updated = 0
        timestamp = datetime.now(timezone.utc).isoformat()

        with self.connection() as conn:
            for evaluation in evaluations:
                existing = conn.execute(
                    """
                    SELECT id
                    FROM signal_evaluation
                    WHERE agent_name = ?
                      AND symbol = ?
                      AND timeframe = ?
                      AND signal_time = ?
                      AND horizon_candles = ?
                    """,
                    (
                        evaluation.agent_name,
                        evaluation.symbol,
                        evaluation.timeframe,
                        evaluation.signal_time,
                        evaluation.horizon_candles,
                    ),
                ).fetchone()

                if existing:
                    conn.execute(
                        """
                        UPDATE signal_evaluation
                        SET direction = ?,
                            entry_price = ?,
                            k_value = ?,
                            max_favorable_return = ?,
                            min_return = ?,
                            close_return = ?,
                            is_positive = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            evaluation.direction,
                            evaluation.entry_price,
                            evaluation.k_value,
                            evaluation.max_favorable_return,
                            evaluation.min_return,
                            evaluation.close_return,
                            int(evaluation.is_positive),
                            timestamp,
                            existing["id"],
                        ),
                    )
                    updated += 1
                    continue

                conn.execute(
                    """
                    INSERT INTO signal_evaluation (
                        agent_name,
                        symbol,
                        timeframe,
                        signal_time,
                        direction,
                        horizon_candles,
                        entry_price,
                        k_value,
                        max_favorable_return,
                        min_return,
                        close_return,
                        is_positive,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evaluation.agent_name,
                        evaluation.symbol,
                        evaluation.timeframe,
                        evaluation.signal_time,
                        evaluation.direction,
                        evaluation.horizon_candles,
                        evaluation.entry_price,
                        evaluation.k_value,
                        evaluation.max_favorable_return,
                        evaluation.min_return,
                        evaluation.close_return,
                        int(evaluation.is_positive),
                        timestamp,
                        timestamp,
                    ),
                )
                inserted += 1

        return UpsertResult(inserted=inserted, updated=updated)

    def delete_signal_evaluations(self, agent_name: str, symbol: str, timeframe: str) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM signal_evaluation
                WHERE agent_name = ? AND symbol = ? AND timeframe = ?
                """,
                (agent_name, symbol, timeframe),
            )
        return int(cursor.rowcount)

    def get_open_trade(self, symbol: str) -> TradeRecord | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, symbol, entry_time, entry_price, exit_time, exit_price, pnl_pct, duration, exit_reason
                FROM trades
                WHERE symbol = ? AND exit_time IS NULL
                ORDER BY entry_time DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        return self._row_to_trade(row) if row else None

    def insert_trade(self, symbol: str, entry_time: str, entry_price: float) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO trades (
                    symbol,
                    entry_time,
                    entry_price,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (symbol, entry_time, entry_price, created_at),
            )
        return int(cursor.lastrowid)

    def close_trade(
        self,
        trade_id: int,
        exit_time: str,
        exit_price: float,
        pnl_pct: float,
        duration: int,
        exit_reason: str,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE trades
                SET exit_time = ?,
                    exit_price = ?,
                    pnl_pct = ?,
                    duration = ?,
                    exit_reason = ?
                WHERE id = ?
                """,
                (exit_time, exit_price, pnl_pct, duration, exit_reason, trade_id),
            )

    def get_closed_trades(self, symbol: str) -> list[TradeRecord]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, entry_time, entry_price, exit_time, exit_price, pnl_pct, duration, exit_reason
                FROM trades
                WHERE symbol = ? AND exit_time IS NOT NULL
                ORDER BY exit_time ASC
                """,
                (symbol,),
            ).fetchall()
        return [self._row_to_trade(row) for row in rows]

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> TradeRecord:
        return TradeRecord(
            id=row["id"],
            symbol=row["symbol"],
            entry_time=row["entry_time"],
            entry_price=row["entry_price"],
            exit_time=row["exit_time"],
            exit_price=row["exit_price"],
            pnl_pct=row["pnl_pct"],
            duration=row["duration"],
            exit_reason=row["exit_reason"],
        )

    @staticmethod
    def _ensure_column(
        *,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_sql: str,
    ) -> None:
        columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing_names = {column["name"] for column in columns}
        if column_name in existing_names:
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
