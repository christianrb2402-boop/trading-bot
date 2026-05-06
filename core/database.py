from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Any, Iterator, Sequence

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
    provider: str = "UNKNOWN"


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
class SignalLogRecord:
    symbol: str
    timeframe: str
    signal: str
    signal_tier: str
    k_value: float
    confidence: float
    timestamp: str
    provider_used: str = "UNKNOWN"


@dataclass(slots=True, frozen=True)
class AgentDecisionRecord:
    timestamp: str
    agent_name: str
    symbol: str
    timeframe: str
    decision: str
    confidence: float
    inputs_used: str
    reasoning_summary: str
    linked_signal_id: int | None
    linked_trade_id: int | None
    provider_used: str = "UNKNOWN"
    outcome_label: str | None = None


@dataclass(slots=True, frozen=True)
class ErrorEventRecord:
    timestamp: str
    component: str
    symbol: str | None
    error_type: str
    error_message: str
    recoverable: bool


@dataclass(slots=True, frozen=True)
class RejectedSignalRecord:
    symbol: str
    timeframe: str
    signal_tier: str
    reason: str
    context_payload: str
    thresholds_failed: str
    timestamp: str
    rejected_by_agent: str | None = None
    rejected_stage: str | None = None
    expected_move_pct: float = 0.0
    total_cost_pct: float = 0.0
    expected_net_edge_pct: float = 0.0
    risk_reward_ratio: float = 0.0
    cost_coverage_multiple: float = 0.0
    multi_timeframe_conflict: bool = False
    market_regime: str = "UNKNOWN"
    selected_strategy: str = "UNKNOWN"
    paper_mode: str = "OBSERVE_ONLY"
    would_trade_if_exploration_enabled: bool = False
    experiment_id: int | None = None
    experiment_name: str | None = None


@dataclass(slots=True, frozen=True)
class MarketContextRecord:
    timestamp: str
    source: str
    macro_regime: str
    risk_regime: str
    context_score: float
    reason: str
    raw_payload: str
    provider_used: str = "UNKNOWN"


@dataclass(slots=True, frozen=True)
class StrategyInsightRecord:
    timestamp: str
    insight_type: str
    setup_key: str
    trade_count: int
    winrate: float
    average_pnl: float
    summary: str


@dataclass(slots=True, frozen=True)
class FeatureSnapshotRecord:
    timestamp: str
    symbol: str
    timeframe: str
    feature_payload: str
    quality_score: float
    provider: str


@dataclass(slots=True, frozen=True)
class StrategyVoteRecord:
    timestamp: str
    symbol: str
    timeframe: str
    agent_name: str
    strategy_name: str
    decision: str
    confidence: float
    score: float
    expected_move_pct: float
    expected_net_edge_pct: float
    cost_estimate_pct: float
    risk_reward_ratio: float
    regime: str
    risk_mode: str
    approved: bool
    rejection_reason: str | None
    raw_payload: str
    experiment_id: int | None = None
    experiment_name: str | None = None


@dataclass(slots=True, frozen=True)
class StrategyEvaluationRecord:
    timestamp: str
    strategy_name: str
    symbol: str
    timeframe: str
    regime: str
    trades_count: int
    gross_winrate: float
    net_winrate: float
    avg_gross_pnl: float
    avg_net_pnl: float
    cost_drag: float
    max_drawdown: float
    confidence_adjustment: float
    recommendation: str
    raw_payload: str


@dataclass(slots=True, frozen=True)
class AgentPerformanceRecord:
    timestamp: str
    agent_name: str
    total_votes: int
    approved_votes: int
    rejected_votes: int
    winning_votes: int
    losing_votes: int
    missed_opportunities: int
    good_avoidances: int
    avg_net_pnl_after_vote: float
    reliability_score: float


@dataclass(slots=True, frozen=True)
class BrainDecisionRecord:
    timestamp: str
    symbol: str
    timeframe: str
    final_decision: str
    final_score: float
    market_state: str
    selected_strategy: str
    risk_mode: str
    expected_net_edge_pct: float
    risk_reward_ratio: float
    cost_coverage_multiple: float
    approved: bool
    reason: str
    raw_payload: str
    provider_used: str = "UNKNOWN"
    paper_mode: str = "OBSERVE_ONLY"
    rejected_by_agent: str | None = None
    rejected_stage: str | None = None
    outcome_label: str | None = None
    expected_move_pct: float = 0.0
    total_cost_pct: float = 0.0
    multi_timeframe_conflict: bool = False
    would_trade_if_exploration_enabled: bool = False
    experiment_id: int | None = None
    experiment_name: str | None = None


@dataclass(slots=True, frozen=True)
class RiskEventRecord:
    timestamp: str
    event_type: str
    severity: str
    symbol: str | None
    reason: str
    action_taken: str
    raw_payload: str


@dataclass(slots=True, frozen=True)
class ProviderStatusRecord:
    timestamp: str
    provider: str
    status: str
    latency_ms: float
    last_success_at: str | None
    last_error: str | None
    last_error_at: str | None = None
    source_type: str = "LIVE"
    is_current_live_provider: bool = False
    raw_payload: str | None = None


@dataclass(slots=True, frozen=True)
class DataQualityEventRecord:
    timestamp: str
    symbol: str
    timeframe: str
    event_type: str
    severity: str
    reason: str
    raw_payload: str


@dataclass(slots=True, frozen=True)
class WebsocketEventRecord:
    timestamp: str
    provider: str
    event_type: str
    status: str
    detail: str
    raw_payload: str


@dataclass(slots=True, frozen=True)
class GapRepairEventRecord:
    timestamp: str
    symbol: str
    timeframe: str
    gaps_detected: int
    gaps_repaired: int
    provider_used: str
    reason: str
    raw_payload: str


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


@dataclass(slots=True, frozen=True)
class SimulatedTradeRecord:
    id: int
    symbol: str
    timeframe: str
    direction: str
    status: str
    decision_type: str | None
    entry_time: str
    entry_price: float
    exit_time: str | None
    exit_price: float | None
    stop_loss: float | None
    take_profit: float | None
    pnl: float | None
    pnl_pct: float | None
    signal_strength: float | None
    fee_pct: float
    fees_paid: float
    slippage_pct: float
    signal_id: int | None
    outcome: str | None
    duration_seconds: int | None
    max_favorable_excursion: float | None
    max_adverse_excursion: float | None
    entry_trend: str | None
    entry_volatility_bucket: str | None
    entry_momentum_bucket: str | None
    entry_volume_regime: str | None
    entry_market_regime: str | None
    setup_signature: str | None
    reason_entry: str | None
    reason_exit: str | None
    created_at: str
    updated_at: str
    provider_used: str | None = None
    market_type: str | None = None
    leverage_simulated: float | None = None
    margin_used: float | None = None
    liquidation_price_estimate: float | None = None
    funding_rate_estimate: float | None = None
    funding_cost_estimate: float | None = None
    notional_exposure: float | None = None
    gross_pnl: float | None = None
    net_pnl_before_funding: float | None = None
    net_pnl: float | None = None
    net_pnl_pct: float | None = None
    final_net_pnl_after_all_costs: float | None = None
    final_net_pnl_after_all_costs_pct: float | None = None
    fees_open: float | None = None
    fees_close: float | None = None
    total_fees: float | None = None
    slippage_cost: float | None = None
    spread_cost: float | None = None
    total_cost_drag: float | None = None
    break_even_price: float | None = None
    minimum_required_move_to_profit: float | None = None
    entry_context: str | None = None
    exit_context: str | None = None
    agent_votes: str | None = None
    risk_reward_snapshot: str | None = None
    cost_snapshot: str | None = None
    paper_mode: str | None = None
    exploratory_trade: int | None = None
    experiment_id: int | None = None
    experiment_name: str | None = None


@dataclass(slots=True, frozen=True)
class PaperExperimentRecord:
    id: int
    name: str
    status: str
    started_at: str
    ended_at: str | None
    notes: str | None


@dataclass(slots=True, frozen=True)
class NewsEventRecord:
    source: str
    headline: str
    event_time: str
    detected_symbols: str
    sentiment_score: float
    confidence: float
    raw_payload: str


@dataclass(slots=True, frozen=True)
class SentimentSnapshotRecord:
    source: str
    sentiment_label: str
    sentiment_score: float
    confidence: float
    snapshot_time: str
    raw_payload: str


@dataclass(slots=True, frozen=True)
class MarketSnapshotRecord:
    timestamp: str
    symbol: str
    timeframe: str
    provider_used: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    is_valid: bool
    is_stale: bool
    notes: str


@dataclass(slots=True, frozen=True)
class PaperPortfolioRecord:
    timestamp: str
    starting_capital: float
    available_cash: float
    realized_pnl: float
    unrealized_pnl: float
    total_equity: float
    drawdown: float
    max_drawdown: float
    gross_exposure: float
    net_exposure: float
    open_positions: int
    total_fees_paid: float
    total_slippage_paid: float


@dataclass(slots=True, frozen=True)
class PaperPositionRecord:
    symbol: str
    timeframe: str
    trade_id: int
    direction: str
    quantity: float
    entry_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    exposure_pct: float
    status: str
    opened_at: str
    updated_at: str
    provider_used: str


@dataclass(slots=True, frozen=True)
class PaperOrderRecord:
    timestamp: str
    trade_id: int | None
    symbol: str
    timeframe: str
    side: str
    order_type: str
    requested_price: float
    filled_price: float
    quantity: float
    notional: float
    fees: float
    slippage_cost: float
    spread_cost: float
    status: str
    provider_used: str
    reason: str


@dataclass(slots=True, frozen=True)
class PaperTradeLedgerRecord:
    trade_id: int
    symbol: str
    timeframe: str
    direction: str
    status: str
    gross_pnl: float
    net_pnl: float
    total_fees: float
    slippage_cost: float
    spread_cost: float
    funding_cost_estimate: float
    notes: str
    timestamp: str


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
        timestamp = datetime.now(timezone.utc).isoformat()
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
                    provider TEXT NOT NULL DEFAULT 'UNKNOWN',
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, timeframe, open_time)
                )
                """
            )
            self._ensure_column(
                conn=conn,
                table_name="candles",
                column_name="provider",
                column_sql="TEXT NOT NULL DEFAULT 'UNKNOWN'",
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

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signals_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    signal_tier TEXT NOT NULL DEFAULT 'REJECTED',
                    k_value REAL NOT NULL,
                    confidence REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    provider_used TEXT NOT NULL DEFAULT 'UNKNOWN'
                )
                """
            )
            self._ensure_column(
                conn=conn,
                table_name="signals_log",
                column_name="signal_tier",
                column_sql="TEXT NOT NULL DEFAULT 'REJECTED'",
            )
            self._ensure_column(
                conn=conn,
                table_name="signals_log",
                column_name="provider_used",
                column_sql="TEXT NOT NULL DEFAULT 'UNKNOWN'",
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_signals_log_symbol_timestamp
                ON signals_log (symbol, timeframe, timestamp)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rejected_signals_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    signal_tier TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    context_payload TEXT NOT NULL,
                    thresholds_failed TEXT NOT NULL,
                    rejected_by_agent TEXT,
                    rejected_stage TEXT,
                    expected_move_pct REAL NOT NULL DEFAULT 0,
                    total_cost_pct REAL NOT NULL DEFAULT 0,
                    expected_net_edge_pct REAL NOT NULL DEFAULT 0,
                    risk_reward_ratio REAL NOT NULL DEFAULT 0,
                    cost_coverage_multiple REAL NOT NULL DEFAULT 0,
                    multi_timeframe_conflict INTEGER NOT NULL DEFAULT 0,
                    market_regime TEXT NOT NULL DEFAULT 'UNKNOWN',
                    selected_strategy TEXT NOT NULL DEFAULT 'UNKNOWN',
                    paper_mode TEXT NOT NULL DEFAULT 'OBSERVE_ONLY',
                    would_trade_if_exploration_enabled INTEGER NOT NULL DEFAULT 0,
                    experiment_id INTEGER,
                    experiment_name TEXT,
                    timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="rejected_by_agent", column_sql="TEXT")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="rejected_stage", column_sql="TEXT")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="expected_move_pct", column_sql="REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="total_cost_pct", column_sql="REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="expected_net_edge_pct", column_sql="REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="risk_reward_ratio", column_sql="REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="cost_coverage_multiple", column_sql="REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="multi_timeframe_conflict", column_sql="INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="market_regime", column_sql="TEXT NOT NULL DEFAULT 'UNKNOWN'")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="selected_strategy", column_sql="TEXT NOT NULL DEFAULT 'UNKNOWN'")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="paper_mode", column_sql="TEXT NOT NULL DEFAULT 'OBSERVE_ONLY'")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="would_trade_if_exploration_enabled", column_sql="INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="experiment_id", column_sql="INTEGER")
            self._ensure_column(conn=conn, table_name="rejected_signals_log", column_name="experiment_name", column_sql="TEXT")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rejected_signals_symbol_time
                ON rejected_signals_log (symbol, timeframe, timestamp DESC)
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS simulated_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    direction TEXT NOT NULL,
                    pnl REAL,
                    timestamp_entry TEXT NOT NULL,
                    timestamp_exit TEXT
                )
                """
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="timeframe",
                column_sql="TEXT DEFAULT '1m'",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="status",
                column_sql="TEXT DEFAULT 'OPEN'",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="decision_type",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="entry_time",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="exit_time",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="stop_loss",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="take_profit",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="pnl_pct",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="signal_strength",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="fee_pct",
                column_sql="REAL DEFAULT 0",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="fees_paid",
                column_sql="REAL DEFAULT 0",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="slippage_pct",
                column_sql="REAL DEFAULT 0",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="signal_id",
                column_sql="INTEGER",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="outcome",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="duration_seconds",
                column_sql="INTEGER",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="max_favorable_excursion",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="max_adverse_excursion",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="entry_trend",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="entry_volatility_bucket",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="entry_momentum_bucket",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="entry_volume_regime",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="entry_market_regime",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="setup_signature",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="reason_entry",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="reason_exit",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="created_at",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="updated_at",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="provider_used",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="market_type",
                column_sql="TEXT DEFAULT 'SPOT'",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="leverage_simulated",
                column_sql="REAL DEFAULT 1",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="margin_used",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="liquidation_price_estimate",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="funding_rate_estimate",
                column_sql="REAL DEFAULT 0",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="funding_cost_estimate",
                column_sql="REAL DEFAULT 0",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="notional_exposure",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="gross_pnl",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="net_pnl_before_funding",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="net_pnl",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="net_pnl_pct",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="final_net_pnl_after_all_costs",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="final_net_pnl_after_all_costs_pct",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="fees_open",
                column_sql="REAL DEFAULT 0",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="fees_close",
                column_sql="REAL DEFAULT 0",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="total_fees",
                column_sql="REAL DEFAULT 0",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="slippage_cost",
                column_sql="REAL DEFAULT 0",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="spread_cost",
                column_sql="REAL DEFAULT 0",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="total_cost_drag",
                column_sql="REAL DEFAULT 0",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="break_even_price",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="minimum_required_move_to_profit",
                column_sql="REAL",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="entry_context",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="exit_context",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="agent_votes",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="risk_reward_snapshot",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="cost_snapshot",
                column_sql="TEXT",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="paper_mode",
                column_sql="TEXT DEFAULT 'OBSERVE_ONLY'",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="exploratory_trade",
                column_sql="INTEGER DEFAULT 0",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="experiment_id",
                column_sql="INTEGER",
            )
            self._ensure_column(
                conn=conn,
                table_name="simulated_trades",
                column_name="experiment_name",
                column_sql="TEXT",
            )
            self._backfill_simulated_trades(conn=conn, timestamp=timestamp)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_simulated_trades_symbol_timeframe_entry
                ON simulated_trades (symbol, timeframe, entry_time)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_simulated_trades_status
                ON simulated_trades (status, symbol, timeframe)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_simulated_trades_setup_signature
                ON simulated_trades (setup_signature, direction, status)
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    inputs_used TEXT NOT NULL,
                    reasoning_summary TEXT NOT NULL,
                    linked_signal_id INTEGER,
                    linked_trade_id INTEGER,
                    provider_used TEXT NOT NULL DEFAULT 'UNKNOWN',
                    outcome_label TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(
                conn=conn,
                table_name="agent_decisions",
                column_name="provider_used",
                column_sql="TEXT NOT NULL DEFAULT 'UNKNOWN'",
            )
            self._ensure_column(
                conn=conn,
                table_name="agent_decisions",
                column_name="outcome_label",
                column_sql="TEXT",
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_decisions_symbol_time
                ON agent_decisions (agent_name, symbol, timeframe, timestamp)
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS error_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    component TEXT NOT NULL,
                    symbol TEXT,
                    error_type TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    recoverable INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_error_events_time
                ON error_events (timestamp DESC)
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    macro_regime TEXT NOT NULL,
                    risk_regime TEXT NOT NULL,
                    context_score REAL NOT NULL,
                    reason TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    provider_used TEXT NOT NULL DEFAULT 'UNKNOWN',
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(
                conn=conn,
                table_name="market_context",
                column_name="provider_used",
                column_sql="TEXT NOT NULL DEFAULT 'UNKNOWN'",
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_context_time
                ON market_context (source, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    provider_used TEXT NOT NULL,
                    open_price REAL NOT NULL,
                    high_price REAL NOT NULL,
                    low_price REAL NOT NULL,
                    close_price REAL NOT NULL,
                    volume REAL NOT NULL,
                    is_valid INTEGER NOT NULL,
                    is_stale INTEGER NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_time
                ON market_snapshots (symbol, timeframe, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_insights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    insight_type TEXT NOT NULL,
                    setup_key TEXT NOT NULL,
                    trade_count INTEGER NOT NULL,
                    winrate REAL NOT NULL,
                    average_pnl REAL NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_insights_type_time
                ON strategy_insights (insight_type, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    feature_payload TEXT NOT NULL,
                    quality_score REAL NOT NULL,
                    provider TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_feature_snapshots_lookup
                ON feature_snapshots (symbol, timeframe, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    score REAL NOT NULL,
                    expected_move_pct REAL NOT NULL,
                    expected_net_edge_pct REAL NOT NULL,
                    cost_estimate_pct REAL NOT NULL,
                    risk_reward_ratio REAL NOT NULL,
                    regime TEXT NOT NULL,
                    risk_mode TEXT NOT NULL,
                    approved INTEGER NOT NULL,
                    rejection_reason TEXT,
                    experiment_id INTEGER,
                    experiment_name TEXT,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn=conn, table_name="strategy_votes", column_name="experiment_id", column_sql="INTEGER")
            self._ensure_column(conn=conn, table_name="strategy_votes", column_name="experiment_name", column_sql="TEXT")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_votes_lookup
                ON strategy_votes (symbol, timeframe, strategy_name, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    trades_count INTEGER NOT NULL,
                    gross_winrate REAL NOT NULL,
                    net_winrate REAL NOT NULL,
                    avg_gross_pnl REAL NOT NULL,
                    avg_net_pnl REAL NOT NULL,
                    cost_drag REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    confidence_adjustment REAL NOT NULL,
                    recommendation TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_evaluations_lookup
                ON strategy_evaluations (strategy_name, symbol, timeframe, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    total_votes INTEGER NOT NULL,
                    approved_votes INTEGER NOT NULL,
                    rejected_votes INTEGER NOT NULL,
                    winning_votes INTEGER NOT NULL,
                    losing_votes INTEGER NOT NULL,
                    missed_opportunities INTEGER NOT NULL,
                    good_avoidances INTEGER NOT NULL,
                    avg_net_pnl_after_vote REAL NOT NULL,
                    reliability_score REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_performance_lookup
                ON agent_performance (agent_name, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    final_decision TEXT NOT NULL,
                    final_score REAL NOT NULL,
                    market_state TEXT NOT NULL,
                    selected_strategy TEXT NOT NULL,
                    risk_mode TEXT NOT NULL,
                    expected_net_edge_pct REAL NOT NULL,
                    risk_reward_ratio REAL NOT NULL,
                    cost_coverage_multiple REAL NOT NULL,
                    approved INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    provider_used TEXT NOT NULL DEFAULT 'UNKNOWN',
                    paper_mode TEXT NOT NULL DEFAULT 'OBSERVE_ONLY',
                    rejected_by_agent TEXT,
                    rejected_stage TEXT,
                    outcome_label TEXT,
                    expected_move_pct REAL NOT NULL DEFAULT 0,
                    total_cost_pct REAL NOT NULL DEFAULT 0,
                    multi_timeframe_conflict INTEGER NOT NULL DEFAULT 0,
                    would_trade_if_exploration_enabled INTEGER NOT NULL DEFAULT 0,
                    experiment_id INTEGER,
                    experiment_name TEXT,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn=conn, table_name="brain_decisions", column_name="provider_used", column_sql="TEXT NOT NULL DEFAULT 'UNKNOWN'")
            self._ensure_column(conn=conn, table_name="brain_decisions", column_name="paper_mode", column_sql="TEXT NOT NULL DEFAULT 'OBSERVE_ONLY'")
            self._ensure_column(conn=conn, table_name="brain_decisions", column_name="rejected_by_agent", column_sql="TEXT")
            self._ensure_column(conn=conn, table_name="brain_decisions", column_name="rejected_stage", column_sql="TEXT")
            self._ensure_column(conn=conn, table_name="brain_decisions", column_name="outcome_label", column_sql="TEXT")
            self._ensure_column(conn=conn, table_name="brain_decisions", column_name="expected_move_pct", column_sql="REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn=conn, table_name="brain_decisions", column_name="total_cost_pct", column_sql="REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn=conn, table_name="brain_decisions", column_name="multi_timeframe_conflict", column_sql="INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn=conn, table_name="brain_decisions", column_name="would_trade_if_exploration_enabled", column_sql="INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn=conn, table_name="brain_decisions", column_name="experiment_id", column_sql="INTEGER")
            self._ensure_column(conn=conn, table_name="brain_decisions", column_name="experiment_name", column_sql="TEXT")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_brain_decisions_lookup
                ON brain_decisions (symbol, timeframe, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    symbol TEXT,
                    reason TEXT NOT NULL,
                    action_taken TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    last_success_at TEXT,
                    last_error TEXT,
                    last_error_at TEXT,
                    source_type TEXT NOT NULL DEFAULT 'LIVE',
                    is_current_live_provider INTEGER NOT NULL DEFAULT 0,
                    raw_payload TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn=conn, table_name="provider_status", column_name="last_error_at", column_sql="TEXT")
            self._ensure_column(conn=conn, table_name="provider_status", column_name="source_type", column_sql="TEXT NOT NULL DEFAULT 'LIVE'")
            self._ensure_column(conn=conn, table_name="provider_status", column_name="is_current_live_provider", column_sql="INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn=conn, table_name="provider_status", column_name="raw_payload", column_sql="TEXT")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_provider_status_lookup
                ON provider_status (provider, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_experiments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_experiments_status
                ON paper_experiments (status, started_at DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS news_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    detected_symbols TEXT NOT NULL,
                    sentiment_score REAL NOT NULL,
                    confidence REAL NOT NULL,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sentiment_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    sentiment_label TEXT NOT NULL,
                    sentiment_score REAL NOT NULL,
                    confidence REAL NOT NULL,
                    snapshot_time TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS data_quality_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_data_quality_events_lookup
                ON data_quality_events (symbol, timeframe, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS websocket_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gap_repair_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    gaps_detected INTEGER NOT NULL,
                    gaps_repaired INTEGER NOT NULL,
                    provider_used TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_gap_repair_events_lookup
                ON gap_repair_events (symbol, timeframe, timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_portfolio (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    timestamp TEXT NOT NULL,
                    starting_capital REAL NOT NULL,
                    available_cash REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    total_equity REAL NOT NULL,
                    drawdown REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    gross_exposure REAL NOT NULL,
                    net_exposure REAL NOT NULL,
                    open_positions INTEGER NOT NULL,
                    total_fees_paid REAL NOT NULL,
                    total_slippage_paid REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    trade_id INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    market_value REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    exposure_pct REAL NOT NULL,
                    status TEXT NOT NULL,
                    provider_used TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_positions_status
                ON paper_positions (status, symbol, timeframe)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    trade_id INTEGER,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    requested_price REAL NOT NULL,
                    filled_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    notional REAL NOT NULL,
                    fees REAL NOT NULL,
                    slippage_cost REAL NOT NULL,
                    spread_cost REAL NOT NULL,
                    status TEXT NOT NULL,
                    provider_used TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_orders_time
                ON paper_orders (timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trade_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    status TEXT NOT NULL,
                    gross_pnl REAL NOT NULL,
                    net_pnl REAL NOT NULL,
                    total_fees REAL NOT NULL,
                    slippage_cost REAL NOT NULL,
                    spread_cost REAL NOT NULL,
                    funding_cost_estimate REAL NOT NULL,
                    notes TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_trade_ledger_time
                ON paper_trade_ledger (timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_equity_curve (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    available_cash REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    total_equity REAL NOT NULL,
                    drawdown REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    gross_exposure REAL NOT NULL,
                    net_exposure REAL NOT NULL,
                    open_positions INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_paper_equity_curve_time
                ON paper_equity_curve (timestamp DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS benchmark_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    benchmark_name TEXT NOT NULL,
                    symbols TEXT NOT NULL,
                    timeframes TEXT NOT NULL,
                    trade_count INTEGER NOT NULL,
                    winrate REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    profit_factor REAL NOT NULL,
                    average_trade REAL NOT NULL,
                    total_net_pnl REAL NOT NULL,
                    total_cost REAL NOT NULL,
                    sharpe_simple REAL NOT NULL,
                    edge_vs_strategy REAL,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS walk_forward_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    train_pct REAL NOT NULL,
                    limit_used INTEGER NOT NULL,
                    symbols TEXT NOT NULL,
                    timeframes TEXT NOT NULL,
                    selected_relaxation REAL NOT NULL,
                    train_trade_count INTEGER NOT NULL,
                    test_trade_count INTEGER NOT NULL,
                    train_net_pnl REAL NOT NULL,
                    test_net_pnl REAL NOT NULL,
                    train_winrate REAL NOT NULL,
                    test_winrate REAL NOT NULL,
                    survived_out_of_sample INTEGER NOT NULL,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
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
                        provider,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        getattr(candle, "provider", "UNKNOWN"),
                        created_at,
                    ),
                )
                if cursor.rowcount == 1:
                    inserted += 1
                else:
                    duplicates += 1

        return InsertResult(inserted=inserted, duplicates=duplicates)

    def count_candles(self, symbol: str, timeframe: str) -> int:
        if timeframe != "1m":
            direct = self._load_direct_candles(symbol=symbol, timeframe=timeframe, descending=False, limit=None)
            if direct:
                return len(direct)
            return len(self.get_candles(symbol=symbol, timeframe=timeframe))
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
        direct = self._load_direct_candles(symbol=symbol, timeframe=timeframe, descending=True, limit=limit)
        if direct:
            return list(reversed(direct))
        if timeframe == "1m":
            return []
        materialized = self._materialize_timeframe_candles(symbol=symbol, timeframe=timeframe)
        return materialized[-limit:]

    def get_candles(self, symbol: str, timeframe: str) -> list[StoredCandle]:
        direct = self._load_direct_candles(symbol=symbol, timeframe=timeframe, descending=False, limit=None)
        if direct:
            return direct
        if timeframe == "1m":
            return []
        return self._materialize_timeframe_candles(symbol=symbol, timeframe=timeframe)

    def get_candles_after_close_time(
        self,
        *,
        symbol: str,
        timeframe: str,
        close_time: str,
        limit: int,
    ) -> list[StoredCandle]:
        candles = self.get_candles(symbol=symbol, timeframe=timeframe)
        return [candle for candle in candles if candle.close_time > close_time][:limit]

    def count_candles_between(
        self,
        *,
        symbol: str,
        timeframe: str,
        start_time_exclusive: str,
        end_time_inclusive: str,
    ) -> int:
        candles = self.get_candles(symbol=symbol, timeframe=timeframe)
        return sum(1 for candle in candles if candle.close_time > start_time_exclusive and candle.close_time <= end_time_inclusive)

    def get_candles_between_close_times(
        self,
        *,
        symbol: str,
        timeframe: str,
        start_time_inclusive: str,
        end_time_inclusive: str,
    ) -> list[StoredCandle]:
        candles = self.get_candles(symbol=symbol, timeframe=timeframe)
        return [
            candle
            for candle in candles
            if candle.close_time >= start_time_inclusive and candle.close_time <= end_time_inclusive
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

    def insert_signal_log(self, record: SignalLogRecord) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO signals_log (
                    symbol,
                    timeframe,
                    signal,
                    signal_tier,
                    k_value,
                    confidence,
                    timestamp,
                    provider_used
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.symbol,
                    record.timeframe,
                    record.signal,
                    record.signal_tier,
                    record.k_value,
                    record.confidence,
                    record.timestamp,
                    record.provider_used,
                ),
            )
        return int(cursor.lastrowid)

    def insert_rejected_signal(self, record: RejectedSignalRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            active_experiment = self._get_active_experiment(conn)
            resolved_experiment_id = record.experiment_id if record.experiment_id is not None else active_experiment["id"] if active_experiment else None
            resolved_experiment_name = record.experiment_name if record.experiment_name is not None else active_experiment["name"] if active_experiment else None
            cursor = conn.execute(
                """
                INSERT INTO rejected_signals_log (
                    symbol,
                    timeframe,
                    signal_tier,
                    reason,
                    context_payload,
                    thresholds_failed,
                    rejected_by_agent,
                    rejected_stage,
                    expected_move_pct,
                    total_cost_pct,
                    expected_net_edge_pct,
                    risk_reward_ratio,
                    cost_coverage_multiple,
                    multi_timeframe_conflict,
                    market_regime,
                    selected_strategy,
                    paper_mode,
                    would_trade_if_exploration_enabled,
                    experiment_id,
                    experiment_name,
                    timestamp,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.symbol,
                    record.timeframe,
                    record.signal_tier,
                    record.reason,
                    record.context_payload,
                    record.thresholds_failed,
                    record.rejected_by_agent,
                    record.rejected_stage,
                    record.expected_move_pct,
                    record.total_cost_pct,
                    record.expected_net_edge_pct,
                    record.risk_reward_ratio,
                    record.cost_coverage_multiple,
                    1 if record.multi_timeframe_conflict else 0,
                    record.market_regime,
                    record.selected_strategy,
                    record.paper_mode,
                    1 if record.would_trade_if_exploration_enabled else 0,
                    resolved_experiment_id,
                    resolved_experiment_name,
                    record.timestamp,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def insert_agent_decision(self, record: AgentDecisionRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_decisions (
                    timestamp,
                    agent_name,
                    symbol,
                    timeframe,
                    decision,
                    confidence,
                    inputs_used,
                    reasoning_summary,
                    linked_signal_id,
                    linked_trade_id,
                    provider_used,
                    outcome_label,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.agent_name,
                    record.symbol,
                    record.timeframe,
                    record.decision,
                    record.confidence,
                    record.inputs_used,
                    record.reasoning_summary,
                    record.linked_signal_id,
                    record.linked_trade_id,
                    record.provider_used,
                    record.outcome_label,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def update_agent_decision_outcome(self, *, decision_id: int, outcome_label: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE agent_decisions
                SET outcome_label = ?
                WHERE id = ?
                """,
                (outcome_label, decision_id),
            )

    def get_pending_no_trade_decisions(self, *, timeframe: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, symbol, timeframe, decision, confidence, inputs_used
                FROM agent_decisions
                WHERE agent_name = 'DecisionOrchestrator'
                  AND decision = 'NO_TRADE'
                  AND outcome_label IS NULL
                  AND timeframe = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (timeframe, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_error_event(self, record: ErrorEventRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO error_events (
                    timestamp,
                    component,
                    symbol,
                    error_type,
                    error_message,
                    recoverable,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.component,
                    record.symbol,
                    record.error_type,
                    record.error_message,
                    int(record.recoverable),
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def insert_market_context(self, record: MarketContextRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO market_context (
                    timestamp,
                    source,
                    macro_regime,
                    risk_regime,
                    context_score,
                    reason,
                    raw_payload,
                    provider_used,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.source,
                    record.macro_regime,
                    record.risk_regime,
                    record.context_score,
                    record.reason,
                    record.raw_payload,
                    record.provider_used,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def replace_strategy_insights(self, records: Sequence[StrategyInsightRecord]) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute("DELETE FROM strategy_insights")
            for record in records:
                conn.execute(
                    """
                    INSERT INTO strategy_insights (
                        timestamp,
                        insight_type,
                        setup_key,
                        trade_count,
                        winrate,
                        average_pnl,
                        summary,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.timestamp,
                        record.insight_type,
                        record.setup_key,
                        record.trade_count,
                        record.winrate,
                        record.average_pnl,
                        record.summary,
                        created_at,
                    ),
                )
        return len(records)

    def reset_backtest_state(self) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute("DELETE FROM signals_log")
            conn.execute("DELETE FROM rejected_signals_log")
            conn.execute("DELETE FROM agent_decisions")
            conn.execute("DELETE FROM simulated_trades")
            conn.execute("DELETE FROM strategy_insights")
            conn.execute("DELETE FROM paper_positions")
            conn.execute("DELETE FROM paper_orders")
            conn.execute("DELETE FROM paper_trade_ledger")
            conn.execute("DELETE FROM paper_equity_curve")
            conn.execute("DELETE FROM paper_portfolio")
            conn.execute(
                """
                DELETE FROM sqlite_sequence
                WHERE name IN (
                    'signals_log',
                    'rejected_signals_log',
                    'agent_decisions',
                    'simulated_trades',
                    'strategy_insights',
                    'paper_positions',
                    'paper_orders',
                    'paper_trade_ledger',
                    'paper_equity_curve'
                )
                """
            )

    def get_open_simulated_trade(self, symbol: str, timeframe: str) -> SimulatedTradeRecord | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT
                    id,
                    symbol,
                    COALESCE(timeframe, '1m') AS timeframe,
                    direction,
                    COALESCE(status, 'OPEN') AS status,
                    decision_type,
                    COALESCE(entry_time, timestamp_entry) AS entry_time,
                    entry_price,
                    COALESCE(exit_time, timestamp_exit) AS exit_time,
                    exit_price,
                    stop_loss,
                    take_profit,
                    pnl,
                    pnl_pct,
                    signal_strength,
                    COALESCE(fee_pct, 0) AS fee_pct,
                    COALESCE(fees_paid, 0) AS fees_paid,
                    COALESCE(slippage_pct, 0) AS slippage_pct,
                    signal_id,
                    outcome,
                    duration_seconds,
                    max_favorable_excursion,
                    max_adverse_excursion,
                    entry_trend,
                    entry_volatility_bucket,
                    entry_momentum_bucket,
                    entry_volume_regime,
                    entry_market_regime,
                    setup_signature,
                    reason_entry,
                    reason_exit,
                    COALESCE(created_at, '') AS created_at,
                    COALESCE(updated_at, '') AS updated_at,
                    provider_used,
                    COALESCE(market_type, 'SPOT') AS market_type,
                    COALESCE(leverage_simulated, 1) AS leverage_simulated,
                    margin_used,
                    liquidation_price_estimate,
                    COALESCE(funding_rate_estimate, 0) AS funding_rate_estimate,
                    COALESCE(funding_cost_estimate, 0) AS funding_cost_estimate,
                    notional_exposure,
                    gross_pnl,
                    net_pnl_before_funding,
                    net_pnl,
                    net_pnl_pct,
                    final_net_pnl_after_all_costs,
                    final_net_pnl_after_all_costs_pct,
                    COALESCE(fees_open, 0) AS fees_open,
                    COALESCE(fees_close, 0) AS fees_close,
                    COALESCE(total_fees, fees_paid, 0) AS total_fees,
                    COALESCE(slippage_cost, 0) AS slippage_cost,
                    COALESCE(spread_cost, 0) AS spread_cost,
                    COALESCE(total_cost_drag, COALESCE(total_fees, fees_paid, 0) + COALESCE(slippage_cost, 0) + COALESCE(spread_cost, 0) + COALESCE(funding_cost_estimate, 0)) AS total_cost_drag,
                    break_even_price,
                    minimum_required_move_to_profit,
                    entry_context,
                    exit_context,
                    agent_votes,
                    risk_reward_snapshot,
                    cost_snapshot,
                    COALESCE(paper_mode, 'OBSERVE_ONLY') AS paper_mode,
                    COALESCE(exploratory_trade, 0) AS exploratory_trade
                FROM simulated_trades
                WHERE symbol = ?
                  AND COALESCE(timeframe, '1m') = ?
                  AND COALESCE(status, 'OPEN') = 'OPEN'
                ORDER BY COALESCE(entry_time, timestamp_entry) DESC
                LIMIT 1
                """,
                (symbol, timeframe),
            ).fetchone()
        return self._row_to_simulated_trade(row) if row else None

    def get_open_simulated_trades(self) -> list[SimulatedTradeRecord]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    symbol,
                    COALESCE(timeframe, '1m') AS timeframe,
                    direction,
                    COALESCE(status, 'OPEN') AS status,
                    decision_type,
                    COALESCE(entry_time, timestamp_entry) AS entry_time,
                    entry_price,
                    COALESCE(exit_time, timestamp_exit) AS exit_time,
                    exit_price,
                    stop_loss,
                    take_profit,
                    pnl,
                    pnl_pct,
                    signal_strength,
                    COALESCE(fee_pct, 0) AS fee_pct,
                    COALESCE(fees_paid, 0) AS fees_paid,
                    COALESCE(slippage_pct, 0) AS slippage_pct,
                    signal_id,
                    outcome,
                    duration_seconds,
                    max_favorable_excursion,
                    max_adverse_excursion,
                    entry_trend,
                    entry_volatility_bucket,
                    entry_momentum_bucket,
                    entry_volume_regime,
                    entry_market_regime,
                    setup_signature,
                    reason_entry,
                    reason_exit,
                    COALESCE(created_at, '') AS created_at,
                    COALESCE(updated_at, '') AS updated_at,
                    provider_used,
                    COALESCE(market_type, 'SPOT') AS market_type,
                    COALESCE(leverage_simulated, 1) AS leverage_simulated,
                    margin_used,
                    liquidation_price_estimate,
                    COALESCE(funding_rate_estimate, 0) AS funding_rate_estimate,
                    COALESCE(funding_cost_estimate, 0) AS funding_cost_estimate,
                    notional_exposure,
                    gross_pnl,
                    net_pnl_before_funding,
                    net_pnl,
                    net_pnl_pct,
                    final_net_pnl_after_all_costs,
                    final_net_pnl_after_all_costs_pct,
                    COALESCE(fees_open, 0) AS fees_open,
                    COALESCE(fees_close, 0) AS fees_close,
                    COALESCE(total_fees, fees_paid, 0) AS total_fees,
                    COALESCE(slippage_cost, 0) AS slippage_cost,
                    COALESCE(spread_cost, 0) AS spread_cost,
                    COALESCE(total_cost_drag, COALESCE(total_fees, fees_paid, 0) + COALESCE(slippage_cost, 0) + COALESCE(spread_cost, 0) + COALESCE(funding_cost_estimate, 0)) AS total_cost_drag,
                    break_even_price,
                    minimum_required_move_to_profit,
                    entry_context,
                    exit_context,
                    agent_votes,
                    risk_reward_snapshot,
                    cost_snapshot,
                    COALESCE(paper_mode, 'OBSERVE_ONLY') AS paper_mode,
                    COALESCE(exploratory_trade, 0) AS exploratory_trade
                FROM simulated_trades
                WHERE COALESCE(status, 'OPEN') = 'OPEN'
                ORDER BY COALESCE(entry_time, timestamp_entry) ASC
                """
            ).fetchall()
        return [self._row_to_simulated_trade(row) for row in rows]

    def insert_simulated_trade(
        self,
        *,
        symbol: str,
        timeframe: str,
        direction: str,
        status: str,
        decision_type: str,
        entry_time: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        signal_strength: float | None,
        fee_pct: float,
        fees_paid: float,
        slippage_pct: float,
        signal_id: int | None,
        entry_trend: str | None,
        entry_volatility_bucket: str | None,
        entry_momentum_bucket: str | None,
        entry_volume_regime: str | None,
        entry_market_regime: str | None,
        setup_signature: str | None,
        reason_entry: str,
        provider_used: str | None = None,
        market_type: str = "SPOT",
        leverage_simulated: float = 1.0,
        margin_used: float | None = None,
        liquidation_price_estimate: float | None = None,
        funding_rate_estimate: float = 0.0,
        funding_cost_estimate: float = 0.0,
        notional_exposure: float | None = None,
        fees_open: float = 0.0,
        slippage_cost: float = 0.0,
        spread_cost: float = 0.0,
        break_even_price: float | None = None,
        minimum_required_move_to_profit: float | None = None,
        entry_context: str | None = None,
        agent_votes: str | None = None,
        risk_reward_snapshot: str | None = None,
        cost_snapshot: str | None = None,
        paper_mode: str = "OBSERVE_ONLY",
        exploratory_trade: bool = False,
        experiment_id: int | None = None,
        experiment_name: str | None = None,
    ) -> int:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            active_experiment = self._get_active_experiment(conn)
            resolved_experiment_id = experiment_id if experiment_id is not None else active_experiment["id"] if active_experiment else None
            resolved_experiment_name = experiment_name if experiment_name is not None else active_experiment["name"] if active_experiment else None
            cursor = conn.execute(
                """
                INSERT INTO simulated_trades (
                    symbol,
                    timeframe,
                    direction,
                    status,
                    decision_type,
                    entry_time,
                    entry_price,
                    stop_loss,
                    take_profit,
                    signal_strength,
                    fee_pct,
                    fees_paid,
                    slippage_pct,
                    signal_id,
                    entry_trend,
                    entry_volatility_bucket,
                    entry_momentum_bucket,
                    entry_volume_regime,
                    entry_market_regime,
                    setup_signature,
                    reason_entry,
                    provider_used,
                    market_type,
                    leverage_simulated,
                    margin_used,
                    liquidation_price_estimate,
                    funding_rate_estimate,
                    funding_cost_estimate,
                    notional_exposure,
                    fees_open,
                    total_fees,
                    slippage_cost,
                    spread_cost,
                    break_even_price,
                    minimum_required_move_to_profit,
                    entry_context,
                    agent_votes,
                    risk_reward_snapshot,
                    cost_snapshot,
                    paper_mode,
                    exploratory_trade,
                    experiment_id,
                    experiment_name,
                    created_at,
                    updated_at,
                    timestamp_entry
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    timeframe,
                    direction,
                    status,
                    decision_type,
                    entry_time,
                    entry_price,
                    stop_loss,
                    take_profit,
                    signal_strength,
                    fee_pct,
                    fees_paid,
                    slippage_pct,
                    signal_id,
                    entry_trend,
                    entry_volatility_bucket,
                    entry_momentum_bucket,
                    entry_volume_regime,
                    entry_market_regime,
                    setup_signature,
                    reason_entry,
                    provider_used,
                    market_type,
                    leverage_simulated,
                    margin_used,
                    liquidation_price_estimate,
                    funding_rate_estimate,
                    funding_cost_estimate,
                    notional_exposure,
                    fees_open,
                    fees_paid,
                    slippage_cost,
                    spread_cost,
                    break_even_price,
                    minimum_required_move_to_profit,
                    entry_context,
                    agent_votes,
                    risk_reward_snapshot,
                    cost_snapshot,
                    paper_mode,
                    1 if exploratory_trade else 0,
                    resolved_experiment_id,
                    resolved_experiment_name,
                    timestamp,
                    timestamp,
                    entry_time,
                ),
            )
        return int(cursor.lastrowid)

    def close_simulated_trade(
        self,
        *,
        trade_id: int,
        status: str,
        exit_time: str,
        exit_price: float,
        fees_paid: float,
        pnl: float,
        pnl_pct: float,
        outcome: str,
        duration_seconds: int,
        max_favorable_excursion: float,
        max_adverse_excursion: float,
        reason_exit: str,
        gross_pnl: float | None = None,
        net_pnl_before_funding: float | None = None,
        net_pnl: float | None = None,
        net_pnl_pct: float | None = None,
        final_net_pnl_after_all_costs: float | None = None,
        final_net_pnl_after_all_costs_pct: float | None = None,
        fees_close: float | None = None,
        total_fees: float | None = None,
        slippage_cost: float | None = None,
        spread_cost: float | None = None,
        funding_cost_estimate: float | None = None,
        total_cost_drag: float | None = None,
        exit_context: str | None = None,
        cost_snapshot: str | None = None,
    ) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE simulated_trades
                SET status = ?,
                    exit_time = ?,
                    exit_price = ?,
                    fees_paid = ?,
                    pnl = ?,
                    pnl_pct = ?,
                    gross_pnl = COALESCE(?, gross_pnl),
                    net_pnl_before_funding = COALESCE(?, net_pnl_before_funding, ?),
                    net_pnl = COALESCE(?, ?),
                    net_pnl_pct = COALESCE(?, ?),
                    final_net_pnl_after_all_costs = COALESCE(?, final_net_pnl_after_all_costs, ?, ?),
                    final_net_pnl_after_all_costs_pct = COALESCE(?, final_net_pnl_after_all_costs_pct, ?, ?),
                    fees_close = COALESCE(?, fees_close),
                    total_fees = COALESCE(?, ?),
                    slippage_cost = COALESCE(?, slippage_cost),
                    spread_cost = COALESCE(?, spread_cost),
                    funding_cost_estimate = COALESCE(?, funding_cost_estimate),
                    total_cost_drag = COALESCE(?, total_cost_drag, COALESCE(?, 0) + COALESCE(?, 0) + COALESCE(?, 0) + COALESCE(?, 0)),
                    outcome = ?,
                    duration_seconds = ?,
                    max_favorable_excursion = ?,
                    max_adverse_excursion = ?,
                    reason_exit = ?,
                    exit_context = COALESCE(?, exit_context),
                    cost_snapshot = COALESCE(?, cost_snapshot),
                    updated_at = ?,
                    timestamp_exit = ?
                WHERE id = ?
                """,
                (
                    status,
                    exit_time,
                    exit_price,
                    fees_paid,
                    pnl,
                    pnl_pct,
                    gross_pnl,
                    net_pnl_before_funding,
                    pnl,
                    net_pnl,
                    pnl,
                    net_pnl_pct,
                    pnl_pct,
                    final_net_pnl_after_all_costs,
                    net_pnl,
                    pnl,
                    final_net_pnl_after_all_costs_pct,
                    net_pnl_pct,
                    pnl_pct,
                    fees_close,
                    total_fees,
                    fees_paid,
                    slippage_cost,
                    spread_cost,
                    funding_cost_estimate,
                    total_cost_drag,
                    total_fees,
                    slippage_cost,
                    spread_cost,
                    funding_cost_estimate,
                    outcome,
                    duration_seconds,
                    max_favorable_excursion,
                    max_adverse_excursion,
                    reason_exit,
                    exit_context,
                    cost_snapshot,
                    updated_at,
                    exit_time,
                    trade_id,
                ),
            )

    def update_simulated_trade_levels(
        self,
        *,
        trade_id: int,
        stop_loss: float,
        take_profit: float,
        reason_entry: str | None = None,
    ) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE simulated_trades
                SET stop_loss = ?,
                    take_profit = ?,
                    reason_entry = COALESCE(?, reason_entry),
                    updated_at = ?
                WHERE id = ?
                """,
                (stop_loss, take_profit, reason_entry, updated_at, trade_id),
            )

    def mark_simulated_trade_error(self, *, trade_id: int, reason_exit: str) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE simulated_trades
                SET status = 'ERROR',
                    reason_exit = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (reason_exit, updated_at, trade_id),
            )

    def get_closed_simulated_trades(self, symbol: str | None = None) -> list[SimulatedTradeRecord]:
        query = """
            SELECT
                id,
                symbol,
                COALESCE(timeframe, '1m') AS timeframe,
                direction,
                COALESCE(status, 'CLOSED') AS status,
                decision_type,
                COALESCE(entry_time, timestamp_entry) AS entry_time,
                entry_price,
                COALESCE(exit_time, timestamp_exit) AS exit_time,
                exit_price,
                stop_loss,
                take_profit,
                pnl,
                pnl_pct,
                signal_strength,
                COALESCE(fee_pct, 0) AS fee_pct,
                COALESCE(fees_paid, 0) AS fees_paid,
                COALESCE(slippage_pct, 0) AS slippage_pct,
                signal_id,
                outcome,
                duration_seconds,
                max_favorable_excursion,
                max_adverse_excursion,
                entry_trend,
                entry_volatility_bucket,
                entry_momentum_bucket,
                entry_volume_regime,
                entry_market_regime,
                setup_signature,
                reason_entry,
                reason_exit,
                COALESCE(created_at, '') AS created_at,
                COALESCE(updated_at, '') AS updated_at,
                provider_used,
                COALESCE(market_type, 'SPOT') AS market_type,
                COALESCE(leverage_simulated, 1) AS leverage_simulated,
                margin_used,
                liquidation_price_estimate,
                COALESCE(funding_rate_estimate, 0) AS funding_rate_estimate,
                COALESCE(funding_cost_estimate, 0) AS funding_cost_estimate,
                notional_exposure,
                gross_pnl,
                net_pnl_before_funding,
                net_pnl,
                net_pnl_pct,
                final_net_pnl_after_all_costs,
                final_net_pnl_after_all_costs_pct,
                COALESCE(fees_open, 0) AS fees_open,
                COALESCE(fees_close, 0) AS fees_close,
                COALESCE(total_fees, fees_paid, 0) AS total_fees,
                COALESCE(slippage_cost, 0) AS slippage_cost,
                COALESCE(spread_cost, 0) AS spread_cost,
                COALESCE(total_cost_drag, COALESCE(total_fees, fees_paid, 0) + COALESCE(slippage_cost, 0) + COALESCE(spread_cost, 0) + COALESCE(funding_cost_estimate, 0)) AS total_cost_drag,
                break_even_price,
                minimum_required_move_to_profit,
                entry_context,
                exit_context,
                agent_votes,
                risk_reward_snapshot,
                cost_snapshot,
                COALESCE(paper_mode, 'OBSERVE_ONLY') AS paper_mode,
                COALESCE(exploratory_trade, 0) AS exploratory_trade
            FROM simulated_trades
            WHERE COALESCE(status, 'OPEN') <> 'OPEN'
        """
        params: tuple[Any, ...] = ()
        if symbol:
            query += " AND symbol = ?"
            params = (symbol,)
        query += " ORDER BY COALESCE(exit_time, timestamp_exit) ASC"

        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_simulated_trade(row) for row in rows]

    def get_recent_simulated_trades(self, limit: int = 10, *, experiment_id: int | None = None) -> list[SimulatedTradeRecord]:
        query = """
                SELECT
                    id,
                    symbol,
                    COALESCE(timeframe, '1m') AS timeframe,
                    direction,
                    COALESCE(status, 'OPEN') AS status,
                    decision_type,
                    COALESCE(entry_time, timestamp_entry) AS entry_time,
                    entry_price,
                    COALESCE(exit_time, timestamp_exit) AS exit_time,
                    exit_price,
                    stop_loss,
                    take_profit,
                    pnl,
                    pnl_pct,
                    signal_strength,
                    COALESCE(fee_pct, 0) AS fee_pct,
                    COALESCE(fees_paid, 0) AS fees_paid,
                    COALESCE(slippage_pct, 0) AS slippage_pct,
                    signal_id,
                    outcome,
                    duration_seconds,
                    max_favorable_excursion,
                    max_adverse_excursion,
                    entry_trend,
                    entry_volatility_bucket,
                    entry_momentum_bucket,
                    entry_volume_regime,
                    entry_market_regime,
                    setup_signature,
                    reason_entry,
                    reason_exit,
                    COALESCE(created_at, '') AS created_at,
                    COALESCE(updated_at, '') AS updated_at,
                    provider_used,
                    COALESCE(market_type, 'SPOT') AS market_type,
                    COALESCE(leverage_simulated, 1) AS leverage_simulated,
                    margin_used,
                    liquidation_price_estimate,
                    COALESCE(funding_rate_estimate, 0) AS funding_rate_estimate,
                    COALESCE(funding_cost_estimate, 0) AS funding_cost_estimate,
                    notional_exposure,
                    gross_pnl,
                    net_pnl_before_funding,
                    net_pnl,
                    net_pnl_pct,
                    final_net_pnl_after_all_costs,
                    final_net_pnl_after_all_costs_pct,
                    COALESCE(fees_open, 0) AS fees_open,
                    COALESCE(fees_close, 0) AS fees_close,
                    COALESCE(total_fees, fees_paid, 0) AS total_fees,
                    COALESCE(slippage_cost, 0) AS slippage_cost,
                    COALESCE(spread_cost, 0) AS spread_cost,
                    COALESCE(total_cost_drag, COALESCE(total_fees, fees_paid, 0) + COALESCE(slippage_cost, 0) + COALESCE(spread_cost, 0) + COALESCE(funding_cost_estimate, 0)) AS total_cost_drag,
                    break_even_price,
                    minimum_required_move_to_profit,
                    entry_context,
                    exit_context,
                    agent_votes,
                    risk_reward_snapshot,
                    cost_snapshot,
                    COALESCE(paper_mode, 'OBSERVE_ONLY') AS paper_mode,
                    COALESCE(exploratory_trade, 0) AS exploratory_trade
                FROM simulated_trades
                """
        params: list[Any] = []
        if experiment_id is not None:
            query += " WHERE experiment_id = ?"
            params.append(experiment_id)
        query += " ORDER BY COALESCE(updated_at, created_at, COALESCE(entry_time, timestamp_entry)) DESC LIMIT ?"
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_simulated_trade(row) for row in rows]

    def get_simulated_trade_metrics(self, *, experiment_id: int | None = None) -> dict[str, float | int]:
        query = """
                SELECT
                    COUNT(*) AS closed_trades,
                    SUM(CASE WHEN outcome IN ('WIN_NET', 'WIN') THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN outcome IN ('BREAKEVEN_NET', 'BREAKEVEN') THEN 1 ELSE 0 END) AS breakeven_count,
                    SUM(CASE WHEN outcome IN ('WIN_GROSS_ONLY_NET_LOSS', 'GROSS_WIN_NET_LOSS') THEN 1 ELSE 0 END) AS gross_win_net_loss_count,
                    SUM(CASE WHEN COALESCE(gross_pnl, pnl, 0) > 0 THEN 1 ELSE 0 END) AS gross_wins,
                    SUM(COALESCE(gross_pnl, pnl, 0)) AS total_gross_pnl,
                    AVG(COALESCE(net_pnl_before_funding, net_pnl, pnl, 0)) AS average_net_pnl_before_funding,
                    SUM(COALESCE(net_pnl_before_funding, net_pnl, pnl, 0)) AS total_net_pnl_before_funding,
                    AVG(COALESCE(final_net_pnl_after_all_costs, net_pnl, pnl, 0)) AS average_pnl,
                    SUM(COALESCE(final_net_pnl_after_all_costs, net_pnl, pnl, 0)) AS total_pnl,
                    AVG(COALESCE(final_net_pnl_after_all_costs_pct, net_pnl_pct, pnl_pct, 0)) AS average_pnl_pct,
                    SUM(COALESCE(total_fees, fees_paid, 0)) AS total_fees_paid,
                    SUM(COALESCE(slippage_cost, 0)) AS total_slippage_paid,
                    SUM(COALESCE(spread_cost, 0)) AS total_spread_paid,
                    SUM(COALESCE(funding_cost_estimate, 0)) AS total_funding_cost,
                    AVG(COALESCE(minimum_required_move_to_profit, 0)) AS average_required_move_to_break_even,
                    AVG(CASE WHEN COALESCE(gross_pnl, pnl, 0) > 0 THEN COALESCE(gross_pnl, pnl, 0) END) AS average_gross_win,
                    AVG(CASE WHEN COALESCE(final_net_pnl_after_all_costs, net_pnl, pnl, 0) < 0 THEN ABS(COALESCE(final_net_pnl_after_all_costs, net_pnl, pnl, 0)) END) AS average_net_loss
                FROM simulated_trades
                WHERE COALESCE(status, 'OPEN') <> 'OPEN'
                """
        params: list[Any] = []
        if experiment_id is not None:
            query += " AND experiment_id = ?"
            params.append(experiment_id)
        with self.connection() as conn:
            row = conn.execute(query, tuple(params)).fetchone()

        closed_trades = int(row["closed_trades"] or 0)
        wins = int(row["wins"] or 0)
        breakeven_count = int(row["breakeven_count"] or 0)
        gross_win_net_loss_count = int(row["gross_win_net_loss_count"] or 0)
        gross_wins = int(row["gross_wins"] or 0)
        winrate = round((wins / closed_trades) * 100, 2) if closed_trades else 0.0
        gross_winrate = round((gross_wins / closed_trades) * 100, 2) if closed_trades else 0.0
        total_fees_paid = float(row["total_fees_paid"] or 0.0)
        total_slippage_paid = float(row["total_slippage_paid"] or 0.0)
        total_spread_paid = float(row["total_spread_paid"] or 0.0)
        total_funding_cost = float(row["total_funding_cost"] or 0.0)
        total_cost_drag = total_fees_paid + total_slippage_paid + total_spread_paid + total_funding_cost
        average_gross_win = float(row["average_gross_win"] or 0.0)
        average_net_loss = float(row["average_net_loss"] or 0.0)
        if average_gross_win > 0 and average_net_loss > 0:
            breakeven_winrate = round((average_net_loss / (average_gross_win + average_net_loss)) * 100, 2)
        elif average_gross_win > 0:
            breakeven_winrate = 0.0
        else:
            breakeven_winrate = 100.0 if closed_trades else 0.0
        return {
            "closed_trades": closed_trades,
            "wins": wins,
            "winrate": winrate,
            "net_wins": wins,
            "gross_wins": gross_wins,
            "gross_winrate": gross_winrate,
            "total_gross_pnl": round(float(row["total_gross_pnl"] or 0.0), 6),
            "average_net_pnl_before_funding": round(float(row["average_net_pnl_before_funding"] or 0.0), 6),
            "total_net_pnl_before_funding": round(float(row["total_net_pnl_before_funding"] or 0.0), 6),
            "average_pnl": round(float(row["average_pnl"] or 0.0), 6),
            "total_pnl": round(float(row["total_pnl"] or 0.0), 6),
            "average_pnl_pct": round(float(row["average_pnl_pct"] or 0.0), 6),
            "total_fees_paid": round(total_fees_paid, 6),
            "total_slippage_paid": round(total_slippage_paid, 6),
            "total_spread_paid": round(total_spread_paid, 6),
            "total_funding_cost": round(total_funding_cost, 6),
            "total_cost_drag": round(total_cost_drag, 6),
            "gross_win_net_loss": gross_win_net_loss_count,
            "breakeven_count": breakeven_count,
            "average_cost_per_trade": round(
                total_cost_drag / max(closed_trades, 1),
                6,
            ) if closed_trades else 0.0,
            "average_required_move_to_break_even": round(float(row["average_required_move_to_break_even"] or 0.0), 6),
            "breakeven_winrate_approx": breakeven_winrate,
        }

    def list_candle_counts(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, timeframe, COUNT(*) AS total
                FROM candles
                GROUP BY symbol, timeframe
                ORDER BY symbol, timeframe
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_signal_counts(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, COUNT(*) AS total
                FROM signals_log
                GROUP BY symbol
                ORDER BY symbol
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def count_agent_decisions(self) -> int:
        with self.connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM agent_decisions").fetchone()
        return int(row["total"] or 0)

    def count_paper_orders(self) -> int:
        with self.connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM paper_orders").fetchone()
        return int(row["total"] or 0)

    def count_open_paper_positions(self) -> int:
        with self.connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM paper_positions WHERE status = 'OPEN'").fetchone()
        return int(row["total"] or 0)

    def get_recent_benchmark_results(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM benchmark_results ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_walk_forward_results(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM walk_forward_results ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_signals(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, timeframe, signal, signal_tier, k_value, confidence, timestamp, provider_used
                FROM signals_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_rejected_signals(self, limit: int = 10, *, experiment_id: int | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            query = """
                SELECT
                    id,
                    symbol,
                    timeframe,
                    signal_tier,
                    reason,
                    context_payload,
                    thresholds_failed,
                    rejected_by_agent,
                    rejected_stage,
                    expected_move_pct,
                    total_cost_pct,
                    expected_net_edge_pct,
                    risk_reward_ratio,
                    cost_coverage_multiple,
                    multi_timeframe_conflict,
                    market_regime,
                    selected_strategy,
                    paper_mode,
                    would_trade_if_exploration_enabled,
                    experiment_id,
                    experiment_name,
                    timestamp
                FROM rejected_signals_log
            """
            params: list[Any] = []
            if experiment_id is not None:
                query += " WHERE experiment_id = ?"
                params.append(experiment_id)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def get_recent_error_events(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, component, symbol, error_type, error_message, recoverable, created_at
                FROM error_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_agent_decisions(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    timestamp,
                    agent_name,
                    symbol,
                    timeframe,
                    decision,
                    confidence,
                    inputs_used,
                    reasoning_summary,
                    linked_signal_id,
                    linked_trade_id,
                    provider_used,
                    outcome_label,
                    created_at
                FROM agent_decisions
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_latest_agent_decisions_by_agent(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT d.*
                FROM agent_decisions d
                INNER JOIN (
                    SELECT agent_name, MAX(id) AS max_id
                    FROM agent_decisions
                    GROUP BY agent_name
                ) latest
                    ON d.agent_name = latest.agent_name
                   AND d.id = latest.max_id
                ORDER BY d.agent_name ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_market_snapshot(self, record: MarketSnapshotRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO market_snapshots (
                    timestamp,
                    symbol,
                    timeframe,
                    provider_used,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume,
                    is_valid,
                    is_stale,
                    notes,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.symbol,
                    record.timeframe,
                    record.provider_used,
                    record.open_price,
                    record.high_price,
                    record.low_price,
                    record.close_price,
                    record.volume,
                    int(record.is_valid),
                    int(record.is_stale),
                    record.notes,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_recent_market_snapshots(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, symbol, timeframe, provider_used, close_price, volume, is_valid, is_stale, notes
                FROM market_snapshots
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_paper_portfolio(self, record: PaperPortfolioRecord) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO paper_portfolio (
                    id, timestamp, starting_capital, available_cash, realized_pnl, unrealized_pnl, total_equity,
                    drawdown, max_drawdown, gross_exposure, net_exposure, open_positions, total_fees_paid,
                    total_slippage_paid, created_at, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    starting_capital = excluded.starting_capital,
                    available_cash = excluded.available_cash,
                    realized_pnl = excluded.realized_pnl,
                    unrealized_pnl = excluded.unrealized_pnl,
                    total_equity = excluded.total_equity,
                    drawdown = excluded.drawdown,
                    max_drawdown = excluded.max_drawdown,
                    gross_exposure = excluded.gross_exposure,
                    net_exposure = excluded.net_exposure,
                    open_positions = excluded.open_positions,
                    total_fees_paid = excluded.total_fees_paid,
                    total_slippage_paid = excluded.total_slippage_paid,
                    updated_at = excluded.updated_at
                """,
                (
                    record.timestamp,
                    record.starting_capital,
                    record.available_cash,
                    record.realized_pnl,
                    record.unrealized_pnl,
                    record.total_equity,
                    record.drawdown,
                    record.max_drawdown,
                    record.gross_exposure,
                    record.net_exposure,
                    record.open_positions,
                    record.total_fees_paid,
                    record.total_slippage_paid,
                    now,
                    now,
                ),
            )

    def get_paper_portfolio(self) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM paper_portfolio WHERE id = 1").fetchone()
        return dict(row) if row else None

    def append_paper_equity_curve(self, record: PaperPortfolioRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO paper_equity_curve (
                    timestamp, available_cash, realized_pnl, unrealized_pnl, total_equity, drawdown,
                    max_drawdown, gross_exposure, net_exposure, open_positions, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.available_cash,
                    record.realized_pnl,
                    record.unrealized_pnl,
                    record.total_equity,
                    record.drawdown,
                    record.max_drawdown,
                    record.gross_exposure,
                    record.net_exposure,
                    record.open_positions,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def upsert_paper_position(self, record: PaperPositionRecord) -> None:
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT id FROM paper_positions WHERE trade_id = ?",
                (record.trade_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE paper_positions
                    SET current_price = ?, market_value = ?, unrealized_pnl = ?, exposure_pct = ?, status = ?,
                        provider_used = ?, updated_at = ?
                    WHERE trade_id = ?
                    """,
                    (
                        record.current_price,
                        record.market_value,
                        record.unrealized_pnl,
                        record.exposure_pct,
                        record.status,
                        record.provider_used,
                        record.updated_at,
                        record.trade_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO paper_positions (
                        symbol, timeframe, trade_id, direction, quantity, entry_price, current_price, market_value,
                        unrealized_pnl, exposure_pct, status, provider_used, opened_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.symbol,
                        record.timeframe,
                        record.trade_id,
                        record.direction,
                        record.quantity,
                        record.entry_price,
                        record.current_price,
                        record.market_value,
                        record.unrealized_pnl,
                        record.exposure_pct,
                        record.status,
                        record.provider_used,
                        record.opened_at,
                        record.updated_at,
                    ),
                )

    def close_paper_position(self, trade_id: int, updated_at: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE paper_positions
                SET status = 'CLOSED', updated_at = ?
                WHERE trade_id = ?
                """,
                (updated_at, trade_id),
            )

    def get_open_paper_positions(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM paper_positions
                WHERE status = 'OPEN'
                ORDER BY opened_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_paper_order(self, record: PaperOrderRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO paper_orders (
                    timestamp, trade_id, symbol, timeframe, side, order_type, requested_price, filled_price,
                    quantity, notional, fees, slippage_cost, spread_cost, status, provider_used, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.trade_id,
                    record.symbol,
                    record.timeframe,
                    record.side,
                    record.order_type,
                    record.requested_price,
                    record.filled_price,
                    record.quantity,
                    record.notional,
                    record.fees,
                    record.slippage_cost,
                    record.spread_cost,
                    record.status,
                    record.provider_used,
                    record.reason,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def insert_paper_trade_ledger(self, record: PaperTradeLedgerRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO paper_trade_ledger (
                    trade_id, symbol, timeframe, direction, status, gross_pnl, net_pnl, total_fees,
                    slippage_cost, spread_cost, funding_cost_estimate, notes, timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.trade_id,
                    record.symbol,
                    record.timeframe,
                    record.direction,
                    record.status,
                    record.gross_pnl,
                    record.net_pnl,
                    record.total_fees,
                    record.slippage_cost,
                    record.spread_cost,
                    record.funding_cost_estimate,
                    record.notes,
                    record.timestamp,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_recent_paper_orders(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM paper_orders ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_performance_by_symbol(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    symbol,
                    COUNT(*) AS trade_count,
                    SUM(CASE WHEN outcome IN ('WIN_NET', 'WIN') THEN 1 ELSE 0 END) AS wins,
                    AVG(COALESCE(final_net_pnl_after_all_costs, net_pnl, pnl, 0)) AS average_net_pnl,
                    SUM(COALESCE(final_net_pnl_after_all_costs, net_pnl, pnl, 0)) AS total_net_pnl
                FROM simulated_trades
                WHERE COALESCE(status, 'OPEN') <> 'OPEN'
                GROUP BY symbol
                ORDER BY total_net_pnl DESC, symbol ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_performance_by_timeframe(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    COALESCE(timeframe, '1m') AS timeframe,
                    COUNT(*) AS trade_count,
                    SUM(CASE WHEN outcome IN ('WIN_NET', 'WIN') THEN 1 ELSE 0 END) AS wins,
                    AVG(COALESCE(final_net_pnl_after_all_costs, net_pnl, pnl, 0)) AS average_net_pnl,
                    SUM(COALESCE(final_net_pnl_after_all_costs, net_pnl, pnl, 0)) AS total_net_pnl
                FROM simulated_trades
                WHERE COALESCE(status, 'OPEN') <> 'OPEN'
                GROUP BY COALESCE(timeframe, '1m')
                ORDER BY total_net_pnl DESC, timeframe ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_market_context(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    timestamp,
                    source,
                    macro_regime,
                    risk_regime,
                    context_score,
                    reason,
                    provider_used,
                    raw_payload,
                    created_at
                FROM market_context
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_strategy_insights(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, insight_type, setup_key, trade_count, winrate, average_pnl, summary, created_at
                FROM strategy_insights
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_feature_snapshot(self, record: FeatureSnapshotRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO feature_snapshots (
                    timestamp, symbol, timeframe, feature_payload, quality_score, provider, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.symbol,
                    record.timeframe,
                    record.feature_payload,
                    record.quality_score,
                    record.provider,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_latest_feature_snapshot(self, *, symbol: str, timeframe: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM feature_snapshots
                WHERE symbol = ? AND timeframe = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (symbol, timeframe),
            ).fetchone()
        return dict(row) if row else None

    def get_recent_feature_snapshots(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM feature_snapshots ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_strategy_vote(self, record: StrategyVoteRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            active_experiment = self._get_active_experiment(conn)
            resolved_experiment_id = record.experiment_id if record.experiment_id is not None else active_experiment["id"] if active_experiment else None
            resolved_experiment_name = record.experiment_name if record.experiment_name is not None else active_experiment["name"] if active_experiment else None
            cursor = conn.execute(
                """
                INSERT INTO strategy_votes (
                    timestamp, symbol, timeframe, agent_name, strategy_name, decision, confidence, score,
                    expected_move_pct, expected_net_edge_pct, cost_estimate_pct, risk_reward_ratio, regime,
                    risk_mode, approved, rejection_reason, experiment_id, experiment_name, raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.symbol,
                    record.timeframe,
                    record.agent_name,
                    record.strategy_name,
                    record.decision,
                    record.confidence,
                    record.score,
                    record.expected_move_pct,
                    record.expected_net_edge_pct,
                    record.cost_estimate_pct,
                    record.risk_reward_ratio,
                    record.regime,
                    record.risk_mode,
                    1 if record.approved else 0,
                    record.rejection_reason,
                    resolved_experiment_id,
                    resolved_experiment_name,
                    record.raw_payload,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_recent_strategy_votes(self, limit: int = 20, *, experiment_id: int | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            query = "SELECT * FROM strategy_votes"
            params: list[Any] = []
            if experiment_id is not None:
                query += " WHERE experiment_id = ?"
                params.append(experiment_id)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def insert_strategy_evaluation(self, record: StrategyEvaluationRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO strategy_evaluations (
                    timestamp, strategy_name, symbol, timeframe, regime, trades_count, gross_winrate,
                    net_winrate, avg_gross_pnl, avg_net_pnl, cost_drag, max_drawdown, confidence_adjustment,
                    recommendation, raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.strategy_name,
                    record.symbol,
                    record.timeframe,
                    record.regime,
                    record.trades_count,
                    record.gross_winrate,
                    record.net_winrate,
                    record.avg_gross_pnl,
                    record.avg_net_pnl,
                    record.cost_drag,
                    record.max_drawdown,
                    record.confidence_adjustment,
                    record.recommendation,
                    record.raw_payload,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_recent_strategy_evaluations(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM strategy_evaluations ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_agent_performance(self, record: AgentPerformanceRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_performance (
                    timestamp, agent_name, total_votes, approved_votes, rejected_votes, winning_votes,
                    losing_votes, missed_opportunities, good_avoidances, avg_net_pnl_after_vote,
                    reliability_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.agent_name,
                    record.total_votes,
                    record.approved_votes,
                    record.rejected_votes,
                    record.winning_votes,
                    record.losing_votes,
                    record.missed_opportunities,
                    record.good_avoidances,
                    record.avg_net_pnl_after_vote,
                    record.reliability_score,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_recent_agent_performance(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_performance ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_brain_decision(self, record: BrainDecisionRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            active_experiment = self._get_active_experiment(conn)
            resolved_experiment_id = record.experiment_id if record.experiment_id is not None else active_experiment["id"] if active_experiment else None
            resolved_experiment_name = record.experiment_name if record.experiment_name is not None else active_experiment["name"] if active_experiment else None
            cursor = conn.execute(
                """
                INSERT INTO brain_decisions (
                    timestamp, symbol, timeframe, final_decision, final_score, market_state, selected_strategy,
                    risk_mode, expected_net_edge_pct, risk_reward_ratio, cost_coverage_multiple, approved,
                    reason, provider_used, paper_mode, rejected_by_agent, rejected_stage, outcome_label,
                    expected_move_pct, total_cost_pct, multi_timeframe_conflict, would_trade_if_exploration_enabled,
                    experiment_id, experiment_name,
                    raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.symbol,
                    record.timeframe,
                    record.final_decision,
                    record.final_score,
                    record.market_state,
                    record.selected_strategy,
                    record.risk_mode,
                    record.expected_net_edge_pct,
                    record.risk_reward_ratio,
                    record.cost_coverage_multiple,
                    1 if record.approved else 0,
                    record.reason,
                    record.provider_used,
                    record.paper_mode,
                    record.rejected_by_agent,
                    record.rejected_stage,
                    record.outcome_label,
                    record.expected_move_pct,
                    record.total_cost_pct,
                    1 if record.multi_timeframe_conflict else 0,
                    1 if record.would_trade_if_exploration_enabled else 0,
                    resolved_experiment_id,
                    resolved_experiment_name,
                    record.raw_payload,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_recent_brain_decisions(self, limit: int = 20, *, experiment_id: int | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            query = "SELECT * FROM brain_decisions"
            params: list[Any] = []
            if experiment_id is not None:
                query += " WHERE experiment_id = ?"
                params.append(experiment_id)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def update_brain_decision_outcome(self, *, decision_id: int, outcome_label: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE brain_decisions
                SET outcome_label = ?
                WHERE id = ?
                """,
                (outcome_label, decision_id),
            )

    def get_unevaluated_no_trade_brain_decisions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM brain_decisions
                WHERE final_decision = 'NO_TRADE'
                  AND outcome_label IS NULL
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_next_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        after_close_time: str,
        limit: int,
    ) -> list[StoredCandle]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    symbol,
                    timeframe,
                    open_time,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    close_time,
                    provider
                FROM candles
                WHERE symbol = ?
                  AND timeframe = ?
                  AND close_time > ?
                ORDER BY close_time ASC
                LIMIT ?
                """,
                (symbol, timeframe, after_close_time, limit),
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
                provider=row["provider"],
            )
            for row in rows
        ]

    def get_current_provider_summary(self) -> dict[str, Any]:
        with self.connection() as conn:
            current_live = conn.execute(
                """
                SELECT *
                FROM provider_status
                WHERE is_current_live_provider = 1
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            last_success = conn.execute(
                """
                SELECT *
                FROM provider_status
                WHERE status = 'OK'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            latest_brain = conn.execute(
                """
                SELECT provider_used, paper_mode, timestamp
                FROM brain_decisions
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            latest_snapshot = conn.execute(
                """
                SELECT provider_used, timestamp, symbol, timeframe
                FROM market_snapshots
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return {
            "current_live_provider": dict(current_live) if current_live else None,
            "last_successful_provider": dict(last_success) if last_success else None,
            "latest_brain_provider": dict(latest_brain) if latest_brain else None,
            "latest_market_snapshot_provider": dict(latest_snapshot) if latest_snapshot else None,
        }

    def create_paper_experiment(self, name: str, notes: str | None = None) -> PaperExperimentRecord:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE paper_experiments
                SET status = 'ARCHIVED',
                    ended_at = COALESCE(ended_at, ?)
                WHERE status = 'ACTIVE'
                """,
                (timestamp,),
            )
            cursor = conn.execute(
                """
                INSERT INTO paper_experiments (
                    name, status, started_at, ended_at, notes, created_at
                ) VALUES (?, 'ACTIVE', ?, NULL, ?, ?)
                """,
                (name, timestamp, notes, timestamp),
            )
        return PaperExperimentRecord(
            id=int(cursor.lastrowid),
            name=name,
            status="ACTIVE",
            started_at=timestamp,
            ended_at=None,
            notes=notes,
        )

    def get_current_paper_experiment(self) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM paper_experiments
                WHERE status = 'ACTIVE'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def get_latest_paper_experiment(self) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM paper_experiments
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def insert_news_event(self, record: NewsEventRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO news_events (
                    source, headline, event_time, detected_symbols, sentiment_score, confidence, raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.source,
                    record.headline,
                    record.event_time,
                    record.detected_symbols,
                    record.sentiment_score,
                    record.confidence,
                    record.raw_payload,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_recent_news_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM news_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_sentiment_snapshot(self, record: SentimentSnapshotRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO sentiment_snapshots (
                    source, sentiment_label, sentiment_score, confidence, snapshot_time, raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.source,
                    record.sentiment_label,
                    record.sentiment_score,
                    record.confidence,
                    record.snapshot_time,
                    record.raw_payload,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_recent_sentiment_snapshots(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM sentiment_snapshots ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_risk_event(self, record: RiskEventRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO risk_events (
                    timestamp, event_type, severity, symbol, reason, action_taken, raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.event_type,
                    record.severity,
                    record.symbol,
                    record.reason,
                    record.action_taken,
                    record.raw_payload,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_recent_risk_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM risk_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_provider_status(self, record: ProviderStatusRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            if record.is_current_live_provider or record.source_type in {"LIVE", "FALLBACK"}:
                conn.execute("UPDATE provider_status SET is_current_live_provider = 0")
            cursor = conn.execute(
                """
                INSERT INTO provider_status (
                    timestamp, provider, status, latency_ms, last_success_at, last_error, last_error_at,
                    source_type, is_current_live_provider, raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.provider,
                    record.status,
                    record.latency_ms,
                    record.last_success_at,
                    record.last_error,
                    record.last_error_at,
                    record.source_type,
                    1 if record.is_current_live_provider else 0,
                    record.raw_payload,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_recent_provider_status(self, limit: int = 20, *, source_type: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            if source_type:
                rows = conn.execute(
                    "SELECT * FROM provider_status WHERE source_type = ? ORDER BY id DESC LIMIT ?",
                    (source_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM provider_status ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def insert_data_quality_event(self, record: DataQualityEventRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO data_quality_events (
                    timestamp, symbol, timeframe, event_type, severity, reason, raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.symbol,
                    record.timeframe,
                    record.event_type,
                    record.severity,
                    record.reason,
                    record.raw_payload,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_recent_data_quality_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM data_quality_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_websocket_event(self, record: WebsocketEventRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO websocket_events (
                    timestamp, provider, event_type, status, detail, raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.provider,
                    record.event_type,
                    record.status,
                    record.detail,
                    record.raw_payload,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def insert_gap_repair_event(self, record: GapRepairEventRecord) -> int:
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO gap_repair_events (
                    timestamp, symbol, timeframe, gaps_detected, gaps_repaired, provider_used, reason, raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.symbol,
                    record.timeframe,
                    record.gaps_detected,
                    record.gaps_repaired,
                    record.provider_used,
                    record.reason,
                    record.raw_payload,
                    created_at,
                ),
            )
        return int(cursor.lastrowid)

    def get_recent_gap_repair_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM gap_repair_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_websocket_events(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM websocket_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_similar_closed_trade_stats(self, *, setup_signature: str, direction: str) -> dict[str, float | int]:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN COALESCE(final_net_pnl_after_all_costs, net_pnl, pnl, 0) > 0 THEN 1 ELSE 0 END) AS wins,
                    AVG(COALESCE(final_net_pnl_after_all_costs_pct, net_pnl_pct, pnl_pct, 0)) AS average_pnl_pct
                FROM simulated_trades
                WHERE COALESCE(status, 'OPEN') <> 'OPEN'
                  AND COALESCE(setup_signature, '') = ?
                  AND direction = ?
                """,
                (setup_signature, direction),
            ).fetchone()
        total = int(row["total"] or 0)
        wins = int(row["wins"] or 0)
        return {
            "total": total,
            "wins": wins,
            "winrate": round((wins / total) * 100, 2) if total else 0.0,
            "average_pnl_pct": round(float(row["average_pnl_pct"] or 0.0), 6),
        }

    @staticmethod
    def _row_to_candle(row: sqlite3.Row) -> StoredCandle:
        return StoredCandle(
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            open_time=row["open_time"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
            close_time=row["close_time"],
            provider=row["provider"],
        )

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
    def _row_to_simulated_trade(row: sqlite3.Row) -> SimulatedTradeRecord:
        return SimulatedTradeRecord(
            id=row["id"],
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            direction=row["direction"],
            status=row["status"],
            decision_type=row["decision_type"],
            entry_time=row["entry_time"],
            entry_price=row["entry_price"],
            exit_time=row["exit_time"],
            exit_price=row["exit_price"],
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            pnl=row["pnl"],
            pnl_pct=row["pnl_pct"],
            signal_strength=row["signal_strength"],
            fee_pct=row["fee_pct"],
            fees_paid=row["fees_paid"],
            slippage_pct=row["slippage_pct"],
            signal_id=row["signal_id"],
            outcome=row["outcome"],
            duration_seconds=row["duration_seconds"],
            max_favorable_excursion=row["max_favorable_excursion"],
            max_adverse_excursion=row["max_adverse_excursion"],
            entry_trend=row["entry_trend"],
            entry_volatility_bucket=row["entry_volatility_bucket"],
            entry_momentum_bucket=row["entry_momentum_bucket"],
            entry_volume_regime=row["entry_volume_regime"],
            entry_market_regime=row["entry_market_regime"],
            setup_signature=row["setup_signature"],
            reason_entry=row["reason_entry"],
            reason_exit=row["reason_exit"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            provider_used=row["provider_used"],
            market_type=row["market_type"],
            leverage_simulated=row["leverage_simulated"],
            margin_used=row["margin_used"],
            liquidation_price_estimate=row["liquidation_price_estimate"],
            funding_rate_estimate=row["funding_rate_estimate"],
            funding_cost_estimate=row["funding_cost_estimate"],
            notional_exposure=row["notional_exposure"],
            gross_pnl=row["gross_pnl"],
            net_pnl_before_funding=row["net_pnl_before_funding"],
            net_pnl=row["net_pnl"],
            net_pnl_pct=row["net_pnl_pct"],
            final_net_pnl_after_all_costs=row["final_net_pnl_after_all_costs"],
            final_net_pnl_after_all_costs_pct=row["final_net_pnl_after_all_costs_pct"],
            fees_open=row["fees_open"],
            fees_close=row["fees_close"],
            total_fees=row["total_fees"],
            slippage_cost=row["slippage_cost"],
            spread_cost=row["spread_cost"],
            total_cost_drag=row["total_cost_drag"],
            break_even_price=row["break_even_price"],
            minimum_required_move_to_profit=row["minimum_required_move_to_profit"],
            entry_context=row["entry_context"],
            exit_context=row["exit_context"],
            agent_votes=row["agent_votes"],
            risk_reward_snapshot=row["risk_reward_snapshot"],
            cost_snapshot=row["cost_snapshot"],
            paper_mode=row["paper_mode"],
            exploratory_trade=row["exploratory_trade"],
        )

    def _load_direct_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        descending: bool,
        limit: int | None,
    ) -> list[StoredCandle]:
        order = "DESC" if descending else "ASC"
        query = f"""
                SELECT symbol, timeframe, open_time, open, high, low, close, volume, close_time, COALESCE(provider, 'UNKNOWN') AS provider
                FROM candles
                WHERE symbol = ? AND timeframe = ?
                ORDER BY open_time {order}
                """
        params: list[Any] = [symbol, timeframe]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_candle(row) for row in rows]

    def _materialize_timeframe_candles(self, *, symbol: str, timeframe: str) -> list[StoredCandle]:
        base_candles = self._load_direct_candles(symbol=symbol, timeframe="1m", descending=False, limit=None)
        if not base_candles:
            return []
        minutes = self._timeframe_minutes(timeframe)
        if minutes <= 1:
            return base_candles
        buckets: list[list[StoredCandle]] = []
        current_bucket: list[StoredCandle] = []
        current_bucket_start: int | None = None
        for candle in base_candles:
            open_dt = datetime.fromisoformat(candle.open_time)
            bucket_start = int(open_dt.timestamp()) // (minutes * 60)
            if current_bucket_start is None or bucket_start != current_bucket_start:
                if current_bucket:
                    buckets.append(current_bucket)
                current_bucket = [candle]
                current_bucket_start = bucket_start
            else:
                current_bucket.append(candle)
        if current_bucket:
            buckets.append(current_bucket)

        materialized: list[StoredCandle] = []
        for bucket in buckets:
            first = bucket[0]
            last = bucket[-1]
            materialized.append(
                StoredCandle(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=first.open_time,
                    open=first.open,
                    high=max(item.high for item in bucket),
                    low=min(item.low for item in bucket),
                    close=last.close,
                    volume=sum(item.volume for item in bucket),
                    close_time=last.close_time,
                    provider="LOCAL_SQLITE",
                )
            )
        return materialized

    def _get_active_experiment(self, conn: sqlite3.Connection) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT id, name
            FROM paper_experiments
            WHERE status = 'ACTIVE'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    @staticmethod
    def _timeframe_minutes(timeframe: str) -> int:
        raw = timeframe.strip()
        lower = raw.lower()
        if raw.endswith("M"):
            return 43200
        if lower.endswith("m"):
            return max(1, int(lower[:-1]))
        if lower.endswith("h"):
            return max(1, int(lower[:-1])) * 60
        if lower.endswith("d"):
            return max(1, int(lower[:-1])) * 1440
        if lower.endswith("w"):
            return max(1, int(lower[:-1])) * 10080
        return 1

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
        try:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" in str(exc).lower():
                return
            raise

    @staticmethod
    def _backfill_simulated_trades(*, conn: sqlite3.Connection, timestamp: str) -> None:
        conn.execute(
            """
            UPDATE simulated_trades
            SET timeframe = COALESCE(timeframe, '1m'),
                entry_time = COALESCE(entry_time, timestamp_entry),
                exit_time = COALESCE(exit_time, timestamp_exit),
                status = CASE
                    WHEN status IS NOT NULL AND status <> '' THEN status
                    WHEN COALESCE(exit_time, timestamp_exit) IS NULL THEN 'OPEN'
                    ELSE 'CLOSED'
                END,
                pnl_pct = COALESCE(pnl_pct, NULL),
                fee_pct = COALESCE(fee_pct, 0),
                fees_paid = COALESCE(fees_paid, 0),
                provider_used = COALESCE(provider_used, 'UNKNOWN'),
                market_type = COALESCE(market_type, 'SPOT'),
                leverage_simulated = COALESCE(leverage_simulated, 1),
                funding_rate_estimate = COALESCE(funding_rate_estimate, 0),
                funding_cost_estimate = COALESCE(funding_cost_estimate, 0),
                net_pnl_before_funding = COALESCE(net_pnl_before_funding, net_pnl, pnl, 0),
                fees_open = COALESCE(fees_open, 0),
                fees_close = COALESCE(fees_close, 0),
                total_fees = COALESCE(total_fees, fees_paid, 0),
                slippage_cost = COALESCE(slippage_cost, 0),
                spread_cost = COALESCE(spread_cost, 0),
                final_net_pnl_after_all_costs = COALESCE(final_net_pnl_after_all_costs, net_pnl, pnl, 0),
                final_net_pnl_after_all_costs_pct = COALESCE(final_net_pnl_after_all_costs_pct, net_pnl_pct, pnl_pct, 0),
                total_cost_drag = COALESCE(total_cost_drag, total_fees, 0) + COALESCE(slippage_cost, 0) + COALESCE(spread_cost, 0) + COALESCE(funding_cost_estimate, 0),
                slippage_pct = COALESCE(slippage_pct, 0),
                paper_mode = COALESCE(paper_mode, 'OBSERVE_ONLY'),
                exploratory_trade = COALESCE(exploratory_trade, 0),
                created_at = COALESCE(created_at, ?),
                updated_at = COALESCE(updated_at, ?)
            """
            ,
            (timestamp, timestamp),
        )
