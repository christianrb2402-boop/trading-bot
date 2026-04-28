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
    market_timeframe: str
    binance_klines_limit: int
    delta_k_threshold: float
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
        return ("BTCUSDT", "ETHUSDT")
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

    return Settings(
        app_name=os.getenv("APP_NAME", "multiagent-trading-system"),
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        sqlite_path=sqlite_path,
        logs_dir=logs_dir,
        binance_base_url=os.getenv("BINANCE_BASE_URL", "https://api.binance.com").rstrip("/"),
        binance_timeout_seconds=int(os.getenv("BINANCE_TIMEOUT_SECONDS", "10")),
        market_symbols=_parse_symbols(os.getenv("MARKET_SYMBOLS", "BTCUSDT,ETHUSDT")),
        market_timeframe=os.getenv("MARKET_TIMEFRAME", "1m"),
        binance_klines_limit=int(os.getenv("BINANCE_KLINES_LIMIT", "5")),
        delta_k_threshold=float(os.getenv("DELTA_K_THRESHOLD", "0.5")),
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
    )
