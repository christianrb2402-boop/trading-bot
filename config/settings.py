from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"


@dataclass(slots=True, frozen=True)
class Settings:
    app_name: str
    app_env: str
    log_level: str
    sqlite_path: Path
    logs_dir: Path
    binance_base_url: str
    binance_timeout_seconds: int
    market_symbols: tuple[str, ...]
    core_symbols: tuple[str, ...]
    watchlist_symbols: tuple[str, ...]
    enable_watchlist: bool
    market_timeframe: str
    market_timeframes: tuple[str, ...]
    execution_timeframes: tuple[str, ...]
    context_timeframes: tuple[str, ...]
    structural_timeframes: tuple[str, ...]
    binance_klines_limit: int
    delta_k_threshold: float
    delta_weak_threshold_factor: float
    delta_strong_threshold_factor: float
    delta_test_windows: tuple[int, ...]
    signal_evaluation_windows: tuple[int, ...]
    delta_optimization_thresholds: tuple[float, ...]
    paper_slippage_pct: float
    paper_commission_pct: float
    paper_stop_loss_pct: float
    paper_take_profit_pct: float
    paper_poll_seconds: int
    binance_max_retries: int
    binance_retry_delay_seconds: int
    continuous_loop_seconds: int
    simulated_trade_exit_candles: int
    simulated_initial_capital: float
    simulated_position_size_usd: float
    simulated_fee_pct: float
    simulated_maker_fee_pct: float
    simulated_taker_fee_pct: float
    simulated_slippage_pct: float
    simulated_spread_pct: float
    simulated_stop_loss_pct: float
    simulated_take_profit_pct: float
    simulated_max_hold_candles: int
    simulated_market_type: str
    simulated_default_leverage: float
    simulated_max_leverage: float
    simulated_funding_rate_estimate: float
    max_position_pct_of_capital: float
    max_open_positions: int
    max_daily_simulated_loss_pct: float
    min_reward_risk_ratio: float
    min_net_reward_risk_ratio: float
    min_expected_net_edge_pct: float
    min_cost_coverage_multiple: float
    max_cost_drag_pct: float
    allow_weak_signals: bool
    allow_medium_signals: bool
    allow_strong_signals: bool
    aggressiveness_level: str
    max_daily_drawdown_pct: float
    max_consecutive_losses: int
    max_position_size_pct: float
    max_symbol_exposure_pct: float
    max_strategy_exposure_pct: float
    min_cost_coverage_multiple_conservative: float
    min_cost_coverage_multiple_balanced: float
    min_cost_coverage_multiple_aggressive: float
    paper_mode_auto: bool
    exploration_max_trades_per_hour: int
    exploration_max_open_positions: int
    exploration_risk_per_trade_pct: float
    exploration_max_daily_drawdown_pct: float
    exploration_min_rr: float
    selective_min_rr: float
    exploration_min_cost_coverage_multiple: float
    selective_min_cost_coverage_multiple: float
    min_sample_size_for_profitability_claim: int
    brain_min_final_score: float
    autonomous_loop_seconds: int
    market_watch_loop_seconds: int
    feature_store_lookback: int
    performance_learning_min_sample: int
    backtest_min_trades: int


def _load_env_file(env_file: Path) -> None:
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _default_sqlite_path() -> Path:
    return ROOT_DIR / "runtime" / "market_data.db"


def _resolve_path(raw_value: str, default_path: Path) -> Path:
    if not raw_value.strip():
        return default_path

    path = Path(raw_value)
    if path.is_absolute():
        return path
    return ROOT_DIR / path


def _parse_symbols(raw_symbols: str) -> tuple[str, ...]:
    symbols = tuple(symbol.strip().upper() for symbol in raw_symbols.split(",") if symbol.strip())
    if not symbols:
        return ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
    return symbols


def _parse_windows(raw_windows: str) -> tuple[int, ...]:
    windows = tuple(int(window.strip()) for window in raw_windows.split(",") if window.strip())
    if not windows:
        return (10, 20, 50)
    return windows


def _parse_float_values(raw_values: str) -> tuple[float, ...]:
    values = tuple(float(value.strip()) for value in raw_values.split(",") if value.strip())
    if not values:
        return (0.5, 1.0, 1.5, 2.0)
    return values


def _parse_timeframes(raw_timeframes: str) -> tuple[str, ...]:
    timeframes = tuple(item.strip() for item in raw_timeframes.split(",") if item.strip())
    if not timeframes:
        return ("1m",)
    return timeframes


def _parse_pct_fraction(raw_value: str, default_fraction: float) -> float:
    cleaned = raw_value.strip()
    if not cleaned:
        return default_fraction
    value = float(cleaned)
    # Accept both fractional notation (0.005 = 0.5%) and percentage-point notation (0.5 = 0.5%).
    if value >= 0.02:
        return value / 100
    return value


def _parse_bool(raw_value: str, default: bool) -> bool:
    normalized = raw_value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def load_settings() -> Settings:
    _load_env_file(ENV_FILE)

    sqlite_path = _resolve_path(
        os.getenv("SQLITE_PATH", ""),
        _default_sqlite_path(),
    )
    logs_dir = _resolve_path(
        os.getenv("LOGS_DIR", "logs"),
        ROOT_DIR / "logs",
    )
    market_timeframes = _parse_timeframes(os.getenv("MARKET_TIMEFRAMES", "1m,5m,15m,30m,1h,4h,1d"))
    market_timeframe = os.getenv("MARKET_TIMEFRAME", market_timeframes[0] if market_timeframes else "1m")
    execution_timeframes = _parse_timeframes(os.getenv("EXECUTION_TIMEFRAMES", "1m,5m,15m"))
    context_timeframes = _parse_timeframes(os.getenv("CONTEXT_TIMEFRAMES", "30m,1h,4h,1d"))
    structural_timeframes = _parse_timeframes(os.getenv("STRUCTURAL_TIMEFRAMES", "1w,1M"))

    return Settings(
        app_name=os.getenv("APP_NAME", "multiagent-trading-system"),
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        sqlite_path=sqlite_path,
        logs_dir=logs_dir,
        binance_base_url=os.getenv("BINANCE_BASE_URL", "https://api.binance.com").rstrip("/"),
        binance_timeout_seconds=int(os.getenv("BINANCE_TIMEOUT_SECONDS", "10")),
        market_symbols=_parse_symbols(os.getenv("MARKET_SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT")),
        core_symbols=_parse_symbols(os.getenv("CORE_SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT")),
        watchlist_symbols=_parse_symbols(
            os.getenv(
                "WATCHLIST_SYMBOLS",
                "DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,LTCUSDT,DOTUSDT,MATICUSDT,TRXUSDT,BCHUSDT,NEARUSDT,ARBUSDT,OPUSDT",
            )
        ),
        enable_watchlist=_parse_bool(os.getenv("ENABLE_WATCHLIST", "false"), False),
        market_timeframe=market_timeframe,
        market_timeframes=market_timeframes,
        execution_timeframes=execution_timeframes,
        context_timeframes=context_timeframes,
        structural_timeframes=structural_timeframes,
        binance_klines_limit=int(os.getenv("BINANCE_KLINES_LIMIT", "5")),
        delta_k_threshold=float(os.getenv("DELTA_K_THRESHOLD", "0.5")),
        delta_weak_threshold_factor=float(os.getenv("DELTA_WEAK_THRESHOLD_FACTOR", "0.1")),
        delta_strong_threshold_factor=float(os.getenv("DELTA_STRONG_THRESHOLD_FACTOR", "2.0")),
        delta_test_windows=_parse_windows(os.getenv("DELTA_TEST_WINDOWS", "10,20,50")),
        signal_evaluation_windows=_parse_windows(os.getenv("SIGNAL_EVALUATION_WINDOWS", "5,10,15")),
        delta_optimization_thresholds=_parse_float_values(
            os.getenv("DELTA_OPTIMIZATION_THRESHOLDS", "0.5,1.0,1.5,2.0")
        ),
        paper_slippage_pct=float(os.getenv("PAPER_SLIPPAGE_PCT", "0.05")),
        paper_commission_pct=float(os.getenv("PAPER_COMMISSION_PCT", "0.1")),
        paper_stop_loss_pct=float(os.getenv("PAPER_STOP_LOSS_PCT", "0.5")),
        paper_take_profit_pct=float(os.getenv("PAPER_TAKE_PROFIT_PCT", "1.0")),
        paper_poll_seconds=int(os.getenv("PAPER_POLL_SECONDS", "5")),
        binance_max_retries=int(os.getenv("BINANCE_MAX_RETRIES", "3")),
        binance_retry_delay_seconds=int(os.getenv("BINANCE_RETRY_DELAY_SECONDS", "2")),
        continuous_loop_seconds=int(os.getenv("CONTINUOUS_LOOP_SECONDS", "60")),
        simulated_trade_exit_candles=int(os.getenv("SIMULATED_TRADE_EXIT_CANDLES", "5")),
        simulated_initial_capital=float(os.getenv("SIMULATED_INITIAL_CAPITAL", "1000")),
        simulated_position_size_usd=float(os.getenv("SIMULATED_POSITION_SIZE_USD", "100")),
        simulated_fee_pct=_parse_pct_fraction(os.getenv("SIMULATED_FEE_PCT", "0.1"), 0.001),
        simulated_maker_fee_pct=_parse_pct_fraction(os.getenv("SIMULATED_MAKER_FEE_PCT", "0.1"), 0.001),
        simulated_taker_fee_pct=_parse_pct_fraction(os.getenv("SIMULATED_TAKER_FEE_PCT", "0.1"), 0.001),
        simulated_slippage_pct=_parse_pct_fraction(os.getenv("SIMULATED_SLIPPAGE_PCT", "0.05"), 0.0005),
        simulated_spread_pct=_parse_pct_fraction(os.getenv("SIMULATED_SPREAD_PCT", "0.02"), 0.0002),
        simulated_stop_loss_pct=_parse_pct_fraction(os.getenv("SIMULATED_STOP_LOSS_PCT", "0.005"), 0.005),
        simulated_take_profit_pct=_parse_pct_fraction(os.getenv("SIMULATED_TAKE_PROFIT_PCT", "0.01"), 0.01),
        simulated_max_hold_candles=int(os.getenv("SIMULATED_MAX_HOLD_CANDLES", "15")),
        simulated_market_type=os.getenv("SIMULATED_MARKET_TYPE", "SPOT").upper(),
        simulated_default_leverage=float(os.getenv("SIMULATED_DEFAULT_LEVERAGE", "1")),
        simulated_max_leverage=float(os.getenv("SIMULATED_MAX_LEVERAGE", "3")),
        simulated_funding_rate_estimate=float(os.getenv("SIMULATED_FUNDING_RATE_ESTIMATE", "0.0")),
        max_position_pct_of_capital=float(os.getenv("MAX_POSITION_PCT_OF_CAPITAL", "0.1")),
        max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "5")),
        max_daily_simulated_loss_pct=float(os.getenv("MAX_DAILY_SIMULATED_LOSS_PCT", "0.03")),
        min_reward_risk_ratio=float(os.getenv("MIN_REWARD_RISK_RATIO", "1.5")),
        min_net_reward_risk_ratio=float(os.getenv("MIN_NET_REWARD_RISK_RATIO", "1.5")),
        min_expected_net_edge_pct=float(os.getenv("MIN_EXPECTED_NET_EDGE_PCT", "0.15")),
        min_cost_coverage_multiple=float(os.getenv("MIN_COST_COVERAGE_MULTIPLE", "2.5")),
        max_cost_drag_pct=float(os.getenv("MAX_COST_DRAG_PCT", "0.35")),
        allow_weak_signals=_parse_bool(os.getenv("ALLOW_WEAK_SIGNALS", "true"), True),
        allow_medium_signals=_parse_bool(os.getenv("ALLOW_MEDIUM_SIGNALS", "true"), True),
        allow_strong_signals=_parse_bool(os.getenv("ALLOW_STRONG_SIGNALS", "true"), True),
        aggressiveness_level=os.getenv("AGGRESSIVENESS_LEVEL", "BALANCED").upper(),
        max_daily_drawdown_pct=float(os.getenv("MAX_DAILY_DRAWDOWN_PCT", "0.05")),
        max_consecutive_losses=int(os.getenv("MAX_CONSECUTIVE_LOSSES", "5")),
        max_position_size_pct=float(os.getenv("MAX_POSITION_SIZE_PCT", "0.1")),
        max_symbol_exposure_pct=float(os.getenv("MAX_SYMBOL_EXPOSURE_PCT", "0.25")),
        max_strategy_exposure_pct=float(os.getenv("MAX_STRATEGY_EXPOSURE_PCT", "0.35")),
        min_cost_coverage_multiple_conservative=float(os.getenv("MIN_COST_COVERAGE_MULTIPLE_CONSERVATIVE", "3.0")),
        min_cost_coverage_multiple_balanced=float(os.getenv("MIN_COST_COVERAGE_MULTIPLE_BALANCED", "2.5")),
        min_cost_coverage_multiple_aggressive=float(os.getenv("MIN_COST_COVERAGE_MULTIPLE_AGGRESSIVE", "2.0")),
        paper_mode_auto=_parse_bool(os.getenv("PAPER_MODE_AUTO", "true"), True),
        exploration_max_trades_per_hour=int(os.getenv("EXPLORATION_MAX_TRADES_PER_HOUR", "3")),
        exploration_max_open_positions=int(os.getenv("EXPLORATION_MAX_OPEN_POSITIONS", "1")),
        exploration_risk_per_trade_pct=float(os.getenv("EXPLORATION_RISK_PER_TRADE_PCT", "0.10")),
        exploration_max_daily_drawdown_pct=float(os.getenv("EXPLORATION_MAX_DAILY_DRAWDOWN_PCT", "1.00")),
        exploration_min_rr=float(os.getenv("EXPLORATION_MIN_RR", "1.10")),
        selective_min_rr=float(os.getenv("SELECTIVE_MIN_RR", "1.50")),
        exploration_min_cost_coverage_multiple=float(os.getenv("EXPLORATION_MIN_COST_COVERAGE_MULTIPLE", "1.10")),
        selective_min_cost_coverage_multiple=float(os.getenv("SELECTIVE_MIN_COST_COVERAGE_MULTIPLE", "1.50")),
        min_sample_size_for_profitability_claim=int(os.getenv("MIN_SAMPLE_SIZE_FOR_PROFITABILITY_CLAIM", "50")),
        brain_min_final_score=float(os.getenv("BRAIN_MIN_FINAL_SCORE", "0.55")),
        autonomous_loop_seconds=int(os.getenv("AUTONOMOUS_LOOP_SECONDS", "60")),
        market_watch_loop_seconds=int(os.getenv("MARKET_WATCH_LOOP_SECONDS", "60")),
        feature_store_lookback=int(os.getenv("FEATURE_STORE_LOOKBACK", "60")),
        performance_learning_min_sample=int(os.getenv("PERFORMANCE_LEARNING_MIN_SAMPLE", "10")),
        backtest_min_trades=int(os.getenv("BACKTEST_MIN_TRADES", "100")),
    )
