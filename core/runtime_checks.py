from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from agents.market_data_agent import MarketDataAgent
from config.settings import Settings
from core.database import Database
from data.binance_market_data import BinanceConnectivityProbe


@dataclass(slots=True, frozen=True)
class SymbolHealth:
    symbol: str
    timeframe: str
    has_history: bool
    latest_open_time: str | None
    latest_close_time: str | None
    latest_provider: str | None
    age_seconds: int | None
    is_stale: bool
    gap_count: int
    duplicate_count: int
    corrupted_count: int
    is_valid: bool
    note: str


@dataclass(slots=True, frozen=True)
class ReadinessReport:
    ready_for_live_paper: bool
    binance_reachable: bool
    fresh_data_available: bool
    sqlite_ok: bool
    database_exists: bool
    symbols_with_history: tuple[str, ...]
    missing_symbols: tuple[str, ...]
    stale_symbols: tuple[str, ...]
    current_mode_recommended: str
    can_run_without_blocking: bool
    python_runtime_ok: bool
    api_keys_required: bool
    real_trading_enabled: bool
    reasons: tuple[str, ...]


def timeframe_to_seconds(timeframe: str) -> int:
    raw = timeframe.strip()
    lower = raw.lower()
    if raw.endswith("M"):
        return 2592000
    if lower.endswith("m"):
        return max(1, int(lower[:-1])) * 60
    if lower.endswith("h"):
        return max(1, int(lower[:-1])) * 3600
    if lower.endswith("d"):
        return max(1, int(lower[:-1])) * 86400
    if lower.endswith("w"):
        return max(1, int(lower[:-1])) * 604800
    return 60


def format_age_seconds(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "unknown"
    if age_seconds < 60:
        return f"{age_seconds}s"
    if age_seconds < 3600:
        minutes, seconds = divmod(age_seconds, 60)
        return f"{minutes}m{seconds:02d}s"
    hours, remainder = divmod(age_seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h{minutes:02d}m"


def inspect_symbol_health(
    *,
    database: Database,
    market_data_agent: MarketDataAgent,
    symbol: str,
    timeframe: str,
) -> SymbolHealth:
    candles = database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=20)
    if not candles:
        return SymbolHealth(
            symbol=symbol,
            timeframe=timeframe,
            has_history=False,
            latest_open_time=None,
            latest_close_time=None,
            latest_provider=None,
            age_seconds=None,
            is_stale=True,
            gap_count=0,
            duplicate_count=0,
            corrupted_count=0,
            is_valid=False,
            note="no local candles available",
        )

    assessment = market_data_agent.assess(
        symbol=symbol,
        timeframe=timeframe,
        candles=candles,
        provider_used=candles[-1].provider,
    )
    latest = candles[-1]
    latest_close_dt = datetime.fromisoformat(latest.close_time)
    age_seconds = max(0, int((datetime.now(timezone.utc) - latest_close_dt).total_seconds()))
    return SymbolHealth(
        symbol=symbol,
        timeframe=timeframe,
        has_history=True,
        latest_open_time=latest.open_time,
        latest_close_time=latest.close_time,
        latest_provider=latest.provider,
        age_seconds=age_seconds,
        is_stale=assessment.is_stale,
        gap_count=assessment.gap_count,
        duplicate_count=assessment.duplicate_count,
        corrupted_count=assessment.corrupted_count,
        is_valid=assessment.is_valid,
        note="; ".join(assessment.notes),
    )


def build_readiness_report(
    *,
    settings: Settings,
    database: Database,
    market_data_agent: MarketDataAgent,
    probes: Sequence[BinanceConnectivityProbe],
    symbols: Sequence[str],
    timeframe: str,
) -> ReadinessReport:
    sqlite_ok = True
    database_exists = settings.sqlite_path.exists()
    python_runtime_ok = True
    binance_reachable = all(probe.ok for probe in probes[:2]) if len(probes) >= 2 else all(probe.ok for probe in probes)

    symbol_health = [inspect_symbol_health(database=database, market_data_agent=market_data_agent, symbol=symbol, timeframe=timeframe) for symbol in symbols]
    required_symbols = {"BTCUSDT", "ETHUSDT"}
    required_health = [item for item in symbol_health if item.symbol in required_symbols]
    fresh_data_available = bool(required_health) and all(item.has_history and not item.is_stale for item in required_health)

    symbols_with_history = tuple(item.symbol for item in symbol_health if item.has_history)
    missing_symbols = tuple(item.symbol for item in symbol_health if not item.has_history)
    stale_symbols = tuple(item.symbol for item in symbol_health if item.has_history and item.is_stale)

    reasons: list[str] = []
    if not database_exists:
        reasons.append("SQLite database file does not exist yet")
    if not binance_reachable:
        reasons.append("Binance HTTP probes are failing in this environment")
    if not fresh_data_available:
        reasons.append("Fresh local BTCUSDT and ETHUSDT candles are not available")
    if missing_symbols:
        reasons.append(f"Configured symbols without local history: {', '.join(missing_symbols)}")
    if stale_symbols:
        reasons.append(f"Symbols with stale local data: {', '.join(stale_symbols)}")

    if binance_reachable and database_exists:
        current_mode = "LIVE_BINANCE"
    elif not binance_reachable and symbols_with_history and not stale_symbols:
        current_mode = "LOCAL_SQLITE_FALLBACK"
    else:
        current_mode = "DO_NOT_RUN_LONG"

    can_run_without_blocking = binance_reachable or bool(symbols_with_history)
    ready_for_live_paper = bool(
        python_runtime_ok
        and sqlite_ok
        and database_exists
        and binance_reachable
        and fresh_data_available
        and not missing_symbols
        and current_mode == "LIVE_BINANCE"
    )

    if ready_for_live_paper:
        reasons.append("Environment is ready for live paper with Binance primary data")
    elif current_mode == "LOCAL_SQLITE_FALLBACK":
        reasons.append("Only bounded fallback execution is recommended")
    else:
        reasons.append("Do not run long live paper until connectivity and data freshness improve")

    return ReadinessReport(
        ready_for_live_paper=ready_for_live_paper,
        binance_reachable=binance_reachable,
        fresh_data_available=fresh_data_available,
        sqlite_ok=sqlite_ok,
        database_exists=database_exists,
        symbols_with_history=symbols_with_history,
        missing_symbols=missing_symbols,
        stale_symbols=stale_symbols,
        current_mode_recommended=current_mode,
        can_run_without_blocking=can_run_without_blocking,
        python_runtime_ok=python_runtime_ok,
        api_keys_required=False,
        real_trading_enabled=False,
        reasons=tuple(reasons),
    )
