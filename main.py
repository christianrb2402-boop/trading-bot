from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from datetime import datetime, timezone

from analytics.backtest_engine import BacktestEngine
from analytics.benchmark_engine import BenchmarkEngine
from analytics.performance_analyzer import PerformanceAnalyzer
from analytics.walk_forward_engine import WalkForwardEngine
from agents.audit_agent import AuditAgent
from agents.cost_model_agent import CostModelAgent
from agents.decision_orchestrator import DecisionOrchestrator
from agents.delta_agent import DeltaAgent
from agents.execution_simulator_agent import ExecutionSimulatorAgent
from agents.market_data_agent import MarketDataAgent
from agents.market_context_agent import MarketContextAgent
from agents.performance_learning_agent import PerformanceLearningAgent
from agents.risk_reward_agent import RiskRewardAgent
from agents.signal_evaluator import SignalEvaluator
from agents.symbol_selection_agent import SymbolSelectionAgent
from config.settings import Settings, load_settings
from core.database import (
    AgentDecisionRecord,
    Database,
    ErrorEventRecord,
    MarketContextRecord,
    RejectedSignalRecord,
    SignalLogRecord,
)
from core.exceptions import TradingSystemError
from core.ledger_reconciler import LedgerConsistencyReport, LedgerReconciler
from core.logger import configure_logging
from core.runtime_checks import ReadinessReport, build_readiness_report, format_age_seconds, inspect_symbol_health, timeframe_to_seconds
from data.binance_market_data import BinanceConnectivityProbe, BinanceMarketDataService
from data.market_data_provider import BinanceProvider, FutureYahooProvider, LocalSQLiteProvider, ProviderRouter
from execution.live_paper_engine import LivePaperEngine, LivePaperEngineResult
from execution.paper_trader import PaperTrader
from execution.simulated_trade_tracker import SimulatedTradeTracker


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Market data reader for Binance")
    parser.add_argument("--init-only", action="store_true", help="Inicializa SQLite y termina")
    parser.add_argument("--load-history", action="store_true", help="Carga historico desde Binance sin ejecutar agentes")
    parser.add_argument("--delta-only", action="store_true", help="Ejecuta Delta usando solo SQLite local")
    parser.add_argument("--delta-test", action="store_true", help="Valida Delta sobre ventanas historicas en SQLite")
    parser.add_argument("--evaluate-signals", action="store_true", help="Evalua el resultado post-senal usando SQLite")
    parser.add_argument("--evaluate-direction", action="store_true", help="Evalua performance separada de LONG y SHORT")
    parser.add_argument("--optimize-threshold", action="store_true", help="Compara thresholds para Delta LONG-only")
    parser.add_argument("--paper-trade", action="store_true", help="Ejecuta paper trading LONG-only con datos reales de Binance")
    parser.add_argument("--continuous-engine", action="store_true", help="Ejecuta analisis continuo de mercado cada 60 segundos")
    parser.add_argument("--live-paper-engine", action="store_true", help="Ejecuta el motor live paper trading con comite y ledger simulado")
    parser.add_argument("--backtest", action="store_true", help="Ejecuta backtest historico candle by candle sin fuga de datos")
    parser.add_argument("--benchmark", action="store_true", help="Compara la estrategia contra benchmarks basicos")
    parser.add_argument("--walk-forward", action="store_true", help="Ejecuta validacion walk-forward sin fuga de datos")
    parser.add_argument("--reconcile-ledger", action="store_true", help="Revisa y reconcilia ledger, posiciones y exposicion")
    parser.add_argument("--status-report", action="store_true", help="Muestra el estado persistido del sistema")
    parser.add_argument("--export-report", action="store_true", help="Exporta un reporte auditable en JSON")
    parser.add_argument("--diagnose-connectivity", action="store_true", help="Prueba conectividad HTTP real hacia Binance")
    parser.add_argument("--readiness-check", action="store_true", help="Evalua si el sistema esta listo para correr live paper largo")
    parser.add_argument("--symbols", nargs="+", help="Lista de simbolos, ejemplo BTCUSDT ETHUSDT")
    parser.add_argument("--timeframes", help="Lista separada por comas, ejemplo 1m,5m,15m")
    parser.add_argument("--timeframe", help="Timeframe, ejemplo 1m")
    parser.add_argument("--limit", type=int, help="Cantidad de velas por simbolo")
    parser.add_argument("--min-trades", type=int, help="Minimo de trades cerrados para el backtest")
    parser.add_argument("--train-pct", type=int, help="Porcentaje del historico usado para entrenar en walk-forward")
    parser.add_argument("--format", choices=("json", "csv"), default="json", help="Formato de exportacion para reportes")
    parser.add_argument("--delta-threshold", type=float, help="Threshold para la metrica k")
    parser.add_argument("--delta-windows", nargs="+", type=int, help="Ventanas para delta-test, ejemplo 10 20 50")
    parser.add_argument("--evaluation-windows", nargs="+", type=int, help="Horizontes post-senal, ejemplo 5 10 15")
    parser.add_argument("--optimization-thresholds", nargs="+", type=float, help="Thresholds a comparar, ejemplo 0.5 1.0 1.5 2.0")
    parser.add_argument("--paper-cycles", type=int, help="Cantidad de ciclos de paper trading para pruebas")
    parser.add_argument("--max-loops", "--max_loops", dest="max_loops", type=int, help="Cantidad de iteraciones para pruebas del motor continuo")
    parser.add_argument("--run-minutes", type=int, help="Cantidad de minutos de ejecucion para el live paper engine")
    parser.add_argument("--allow-stale-fallback", action="store_true", help="Permite usar fallback local stale para abrir paper trades")
    return parser


def resolve_runtime_settings(
    base: Settings,
    args: argparse.Namespace,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    str,
    int,
    int,
    float,
    tuple[int, ...],
    tuple[int, ...],
    tuple[float, ...],
]:
    default_symbols = base.core_symbols + tuple(symbol for symbol in base.watchlist_symbols if base.enable_watchlist)
    symbols = tuple(symbol.upper() for symbol in args.symbols) if args.symbols else default_symbols
    timeframes = tuple(item.strip() for item in args.timeframes.split(",") if item.strip()) if args.timeframes else base.market_timeframes
    timeframe = args.timeframe or base.market_timeframe
    limit = args.limit or base.binance_klines_limit
    min_trades = args.min_trades or base.backtest_min_trades
    delta_threshold = args.delta_threshold if args.delta_threshold is not None else base.delta_k_threshold
    delta_windows = tuple(args.delta_windows) if args.delta_windows else base.delta_test_windows
    evaluation_windows = tuple(args.evaluation_windows) if args.evaluation_windows else base.signal_evaluation_windows
    optimization_thresholds = (
        tuple(args.optimization_thresholds) if args.optimization_thresholds else base.delta_optimization_thresholds
    )
    return symbols, timeframes, timeframe, limit, min_trades, delta_threshold, delta_windows, evaluation_windows, optimization_thresholds


def log_startup(
    settings: Settings,
    symbols: tuple[str, ...],
    timeframe: str,
    limit: int,
    delta_threshold: float,
    delta_windows: tuple[int, ...],
    evaluation_windows: tuple[int, ...],
    optimization_thresholds: tuple[float, ...],
) -> None:
    logger.info(
        "Application startup",
        extra={
            "event": "startup",
            "context": {
                "app_name": settings.app_name,
                "environment": settings.app_env,
                "sqlite_path": str(settings.sqlite_path),
                "symbols": list(symbols),
                "timeframe": timeframe,
                "limit": limit,
                "delta_threshold": delta_threshold,
                "delta_windows": list(delta_windows),
                "evaluation_windows": list(evaluation_windows),
                "optimization_thresholds": list(optimization_thresholds),
            },
        },
    )


def initialize_database(database: Database, sqlite_path: str) -> None:
    database.initialize()
    logger.info(
        "Database initialized",
        extra={
            "event": "database_initialized",
            "context": {"sqlite_path": sqlite_path},
        },
    )


def persist_error_event(
    database: Database,
    *,
    component: str,
    symbol: str | None,
    error: Exception,
    recoverable: bool,
) -> None:
    database.insert_error_event(
        ErrorEventRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            component=component,
            symbol=symbol,
            error_type=error.__class__.__name__,
            error_message=str(error),
            recoverable=recoverable,
        )
        )


def persist_rejected_signal(database: Database, signal: dict[str, object], reason: str) -> None:
    database.insert_rejected_signal(
        RejectedSignalRecord(
            symbol=str(signal["symbol"]),
            timeframe=str(signal["timeframe"]),
            signal_tier=str(signal["signal_tier"]),
            reason=reason,
            context_payload=json.dumps(
                {
                    "direction": signal["direction"],
                    "k_value": signal["k_value"],
                    "confidence": signal["confidence"],
                    "trend_direction": signal["trend_direction"],
                    "volatility_regime": signal["volatility_regime"],
                    "momentum_strength": signal["momentum_strength"],
                    "volume_regime": signal["volume_regime"],
                    "market_regime": signal["market_regime"],
                    "setup_signature": signal["setup_signature"],
                },
                ensure_ascii=True,
            ),
            thresholds_failed=json.dumps(list(signal["thresholds_failed"]), ensure_ascii=True),
            timestamp=str(signal["timestamp"]),
        )
    )


def process_symbol(
    database: Database,
    service: BinanceMarketDataService,
    delta_agent: DeltaAgent,
    symbol: str,
    timeframe: str,
    limit: int,
) -> dict[str, str | float | bool]:
    candles = service.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    insert_result = database.insert_candles(candles)

    logger.info(
        "Candles processed",
        extra={
            "event": "insert_summary",
            "context": {
                "symbol": symbol,
                "timeframe": timeframe,
                "requested": len(candles),
                "inserted": insert_result.inserted,
                "duplicates": insert_result.duplicates,
                "stored_total": database.count_candles(symbol, timeframe),
            },
        },
    )

    if insert_result.duplicates:
        logger.info(
            "Duplicate candles ignored",
            extra={
                "event": "duplicate_ignored",
                "context": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "duplicates": insert_result.duplicates,
                },
            },
        )

    print(
        f"{symbol} {timeframe}: fetched={len(candles)} "
        f"inserted={insert_result.inserted} duplicates={insert_result.duplicates}"
    )
    return run_delta_agent(delta_agent, symbol, timeframe)


def load_history_for_symbol(
    database: Database,
    service: BinanceMarketDataService,
    symbol: str,
    timeframe: str,
    limit: int,
) -> dict[str, int | str]:
    candles = service.fetch_ohlcv_history(symbol=symbol, timeframe=timeframe, total_limit=limit)
    insert_result = database.insert_candles(candles)
    stored_total = database.count_candles(symbol, timeframe)

    logger.info(
        "Historical candles loaded",
        extra={
            "event": "history_load_summary",
            "context": {
                "symbol": symbol,
                "timeframe": timeframe,
                "requested": limit,
                "fetched": len(candles),
                "inserted": insert_result.inserted,
                "duplicates": insert_result.duplicates,
                "stored_total": stored_total,
            },
        },
    )

    if insert_result.duplicates:
        logger.info(
            "Historical duplicate candles ignored",
            extra={
                "event": "history_duplicate_ignored",
                "context": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "duplicates": insert_result.duplicates,
                },
            },
        )

    print(
        f"History {symbol} {timeframe}: fetched={len(candles)} "
        f"inserted={insert_result.inserted} duplicates={insert_result.duplicates} total={stored_total}"
    )
    return {
        "symbol": symbol,
        "fetched": len(candles),
        "inserted": insert_result.inserted,
        "duplicates": insert_result.duplicates,
        "stored_total": stored_total,
    }


def run_delta_agent(
    delta_agent: DeltaAgent,
    symbol: str,
    timeframe: str,
) -> dict[str, str | float | bool]:
    result = delta_agent.evaluate(symbol=symbol, timeframe=timeframe)
    logger.info(
        "Delta agent evaluated",
        extra={
            "event": "delta_signal",
            "context": {
                "symbol": result["symbol"],
                "timeframe": timeframe,
                "signal_type": result["signal_type"],
                "k_value": result["k_value"],
                "confidence": result["confidence"],
                "reason": result["reason"],
            },
        },
    )
    print(f"Delta {symbol}: {result}")
    return result


def run_delta_test(
    delta_agent: DeltaAgent,
    symbol: str,
    timeframe: str,
    windows: tuple[int, ...],
) -> dict[str, str | float | int | list[dict[str, int | float | bool]]]:
    result = delta_agent.evaluate_windows(symbol=symbol, timeframe=timeframe, windows=windows)
    logger.info(
        "Delta test evaluated",
        extra={
            "event": "delta_test_summary",
            "context": {
                "symbol": result["symbol"],
                "timeframe": result["timeframe"],
                "threshold": result["threshold"],
                "total_signals": result["total_signals"],
                "total_points": result["total_points"],
                "signal_percentage": result["signal_percentage"],
                "windows": result["windows"],
            },
        },
    )

    print(
        f"Delta test {symbol}: total_signals={result['total_signals']} "
        f"total_points={result['total_points']} signal_percentage={result['signal_percentage']}%"
    )
    for window in result["windows"]:
        print(
            "  "
            f"window={window['requested_window']} candles_used={window['candles_used']} "
            f"complete={window['complete_window']} signals={window['signal_count']}/"
            f"{window['total_points']} percentage={window['signal_percentage']}% "
            f"last_k={window['last_k']}"
        )

    return result


def run_signal_evaluation(
    signal_evaluator: SignalEvaluator,
    symbol: str,
    timeframe: str,
    horizons: tuple[int, ...],
) -> dict[str, str | int | list[dict[str, str | int | float]]]:
    result = signal_evaluator.evaluate_symbol(symbol=symbol, timeframe=timeframe, horizons=horizons)
    logger.info(
        "Signal evaluation completed",
        extra={
            "event": "signal_evaluation_summary",
            "context": {
                "symbol": result["symbol"],
                "timeframe": result["timeframe"],
                "signal_count": result["signal_count"],
                "evaluations_saved": result["evaluations_saved"],
                "evaluations_updated": result["evaluations_updated"],
                "skipped_incomplete": result["skipped_incomplete"],
                "summaries": result["summaries"],
            },
        },
    )

    print(
        f"Signal evaluation {symbol}: signals={result['signal_count']} "
        f"saved={result['evaluations_saved']} updated={result['evaluations_updated']} "
        f"skipped_incomplete={result['skipped_incomplete']}"
    )
    for summary in result["summaries"]:
        print(
            "  "
            f"horizon={summary['horizon']} total={summary['total_signals']} "
            f"winrate={summary['winrate']}% avg_return={summary['average_return']}% "
            f"median_return={summary['median_return']}% avg_drawdown={summary['average_drawdown']}% "
            f"avg_mfe={summary['average_max_favorable_excursion']}%"
        )

    return result


def run_direction_evaluation(
    signal_evaluator: SignalEvaluator,
    symbol: str,
    timeframe: str,
    horizons: tuple[int, ...],
) -> dict[str, str | int | list[dict[str, str | int | float]]]:
    result = signal_evaluator.evaluate_symbol_by_direction(symbol=symbol, timeframe=timeframe, horizons=horizons)
    logger.info(
        "Directional evaluation completed",
        extra={
            "event": "direction_evaluation_summary",
            "context": {
                "symbol": result["symbol"],
                "timeframe": result["timeframe"],
                "signal_count": result["signal_count"],
                "evaluations_saved": result["evaluations_saved"],
                "evaluations_updated": result["evaluations_updated"],
                "skipped_incomplete": result["skipped_incomplete"],
                "directional_summaries": result["directional_summaries"],
            },
        },
    )

    print(
        f"{symbol}: signals={result['signal_count']} "
        f"saved={result['evaluations_saved']} updated={result['evaluations_updated']} "
        f"skipped_incomplete={result['skipped_incomplete']}"
    )
    for summary in result["directional_summaries"]:
        print(
            "  "
            f"horizon={summary['horizon']} {summary['direction']} -> "
            f"winrate={summary['winrate']}% avg_return={summary['average_return']}% "
            f"total={summary['total_signals']}"
        )

    return result


def run_threshold_optimization(
    signal_evaluator: SignalEvaluator,
    symbol: str,
    timeframe: str,
    thresholds: tuple[float, ...],
    horizons: tuple[int, ...],
) -> dict[str, str | list[dict[str, str | int | float]]]:
    result = signal_evaluator.optimize_thresholds(
        symbol=symbol,
        timeframe=timeframe,
        thresholds=thresholds,
        horizons=horizons,
    )
    logger.info(
        "Threshold optimization completed",
        extra={
            "event": "threshold_optimization_summary",
            "context": {
                "symbol": result["symbol"],
                "timeframe": result["timeframe"],
                "threshold_summaries": result["threshold_summaries"],
            },
        },
    )

    print(f"{symbol}: threshold optimization")
    for horizon in horizons:
        print(f"  horizon={horizon}")
        for summary in result["threshold_summaries"]:
            if summary["horizon"] != horizon:
                continue
            print(
                "    "
                f"threshold={summary['threshold']} total_signals={summary['total_signals']} "
                f"winrate={summary['winrate']}% avg_return={summary['average_return']}%"
            )

    return result


def run_paper_trading(
    paper_trader: PaperTrader,
    *,
    symbols: tuple[str, ...],
    timeframe: str,
    max_cycles: int | None,
) -> None:
    logger.info(
        "Paper trading started",
        extra={
            "event": "paper_trade_start",
            "context": {"symbols": list(symbols), "timeframe": timeframe, "max_cycles": max_cycles},
        },
    )
    paper_trader.run(symbols=symbols, timeframe=timeframe, max_cycles=max_cycles)


def run_backtest(
    backtest_engine: BacktestEngine,
    *,
    symbols: tuple[str, ...],
    timeframes: tuple[str, ...],
    limit: int,
    min_trades: int,
) -> dict[str, object]:
    result = backtest_engine.run(symbols=symbols, timeframes=timeframes, limit=limit, min_trades=min_trades)
    trade_metrics = result["trade_metrics"]
    performance_report = result["performance_report"]

    print("Backtest Summary")
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Timeframes: {', '.join(result['timeframes'])}")
    print(f"Events processed: {result['events']}")
    print(f"Decisions persisted: {result['decisions']}")
    print(f"Trades opened: {result['trades_opened']}")
    print(f"Trades closed: {result['trades_closed']}")
    print(f"Closed trades: {trade_metrics['closed_trades']}")
    print(f"Relaxation factor used: {result['relaxation_factor']}")
    print(f"Minimum trades target reached: {result['min_trades_reached']}")
    print(f"Winrate: {trade_metrics['winrate']}%")
    print(f"Average pnl: {trade_metrics['average_pnl']}")
    print(f"Total pnl: {trade_metrics['total_pnl']}")

    best_setup = performance_report.get("best_setup")
    if best_setup:
        print(
            "Best setup: "
            f"{best_setup['setup_key']} trades={best_setup['trade_count']} "
            f"winrate={best_setup['winrate']}% avg_pnl={best_setup['average_pnl']}"
        )
    else:
        print("Best setup: none")

    worst_setup = performance_report.get("worst_setup")
    if worst_setup:
        print(
            "Worst setup: "
            f"{worst_setup['setup_key']} trades={worst_setup['trade_count']} "
            f"winrate={worst_setup['winrate']}% avg_pnl={worst_setup['average_pnl']}"
        )
    else:
        print("Worst setup: none")

    print("Trade distribution by trend:")
    trend_distribution = performance_report["trade_distribution_by_regime"]["trend"]
    if trend_distribution:
        for row in trend_distribution:
            print(
                f"  {row['regime']} trades={row['trade_count']} "
                f"winrate={row['winrate']}% avg_pnl={row['average_pnl']}"
            )
    else:
        print("  none")

    print("Trade distribution by volatility:")
    volatility_distribution = performance_report["trade_distribution_by_regime"]["volatility"]
    if volatility_distribution:
        for row in volatility_distribution:
            print(
                f"  {row['regime']} trades={row['trade_count']} "
                f"winrate={row['winrate']}% avg_pnl={row['average_pnl']}"
            )
    else:
        print("  none")

    print("Data quality summary:")
    for row in result["quality_summaries"]:
        print(
            f"  {row['symbol']} {row['timeframe']} valid={row['valid_candles']} "
            f"duplicates={row['duplicates']} gaps={row['gaps']} corrupted={row['corrupted']}"
        )
    if not result["quality_summaries"]:
        print("  none")

    return result


def run_benchmark(
    benchmark_engine: BenchmarkEngine,
    *,
    symbols: tuple[str, ...],
    timeframes: tuple[str, ...],
    limit: int,
    min_trades: int,
) -> dict[str, object]:
    result = benchmark_engine.run(
        symbols=symbols,
        timeframes=timeframes,
        limit=limit,
        min_trades=min_trades,
    )
    print("Benchmark Summary")
    for row in result["benchmarks"]:
        print(
            f"- {row['benchmark_name']} trades={row['trade_count']} "
            f"winrate={row['winrate']}% net_pnl={row['total_net_pnl']} "
            f"max_drawdown={row['max_drawdown']} profit_factor={row['profit_factor']} "
            f"average_trade={row['average_trade']} total_cost={row['total_cost']} "
            f"edge_vs_strategy={row['edge_vs_strategy']}"
        )
    return result


def run_walk_forward(
    walk_forward_engine: WalkForwardEngine,
    *,
    symbols: tuple[str, ...],
    timeframes: tuple[str, ...],
    limit: int,
    train_pct: int,
) -> dict[str, object]:
    result = walk_forward_engine.run(
        symbols=symbols,
        timeframes=timeframes,
        limit=limit,
        train_pct=train_pct,
    )
    summary = result["summary"]
    print("Walk Forward Summary")
    print(f"Selected relaxation: {summary['selected_relaxation']}")
    print(f"Train trades: {summary['train_trade_count']} net_pnl={summary['train_net_pnl']} winrate={summary['train_winrate']}%")
    print(f"Test trades: {summary['test_trade_count']} net_pnl={summary['test_net_pnl']} winrate={summary['test_winrate']}%")
    print(f"Survived out of sample: {summary['survived_out_of_sample']}")
    return result


def run_reconcile_ledger(ledger_reconciler: LedgerReconciler) -> LedgerConsistencyReport:
    report = ledger_reconciler.reconcile()
    print("Ledger Reconciliation Summary")
    print(f"open_positions_count={report.open_positions_count}")
    print(f"open_simulated_trades_count={report.open_simulated_trades_count}")
    print(f"orphan_positions={report.orphan_positions}")
    print(f"duplicated_positions={report.duplicated_positions}")
    print(f"gross_exposure={report.gross_exposure}")
    print(f"net_exposure={report.net_exposure}")
    print(f"unrealized_pnl={report.unrealized_pnl}")
    print(f"available_cash={report.available_cash}")
    print(f"realized_pnl={report.realized_pnl}")
    print(f"total_equity={report.total_equity}")
    print(f"cash_check={report.cash_check}")
    print(f"equity_check={report.equity_check}")
    print(f"reconciled_positions={report.reconciled_positions}")
    print(f"reconciled_duplicates={report.reconciled_duplicates}")
    print(f"result={report.result}")
    print("notes:")
    for note in report.notes:
        print(f"- {note}")
    return report


def run_diagnose_connectivity(service: BinanceMarketDataService) -> list[BinanceConnectivityProbe]:
    probes = service.diagnose_connectivity()
    print("Connectivity Diagnosis")
    for probe in probes:
        status = "OK" if probe.ok else "FAIL"
        print(f"- {probe.name}")
        print(f"  endpoint={probe.endpoint}")
        print(f"  status={status}")
        print(f"  latency_ms={probe.latency_ms}")
        print(f"  interpretation={probe.interpretation}")
        if probe.error_message:
            print(f"  error={probe.error_message}")
        elif probe.response_preview:
            print(f"  preview={probe.response_preview}")
    usable = all(probe.ok for probe in probes[:2]) if len(probes) >= 2 else all(probe.ok for probe in probes)
    print(f"BINANCE_HTTP_USABLE: {'YES' if usable else 'NO'}")
    return probes


def run_readiness_check(
    *,
    settings: Settings,
    database: Database,
    service: BinanceMarketDataService,
    market_data_agent: MarketDataAgent,
    symbols: tuple[str, ...],
    timeframe: str,
) -> ReadinessReport:
    probes = service.diagnose_connectivity()
    report = build_readiness_report(
        settings=settings,
        database=database,
        market_data_agent=market_data_agent,
        probes=probes,
        symbols=symbols,
        timeframe=timeframe,
    )

    print("Readiness Check")
    print(f"READY_FOR_LIVE_PAPER: {'YES' if report.ready_for_live_paper else 'NO'}")
    print("Reason:")
    for reason in report.reasons:
        print(f"- {reason}")
    print(f"- Binance reachable: {'YES' if report.binance_reachable else 'NO'}")
    print(f"- Fresh data available: {'YES' if report.fresh_data_available else 'NO'}")
    print(f"- SQLite OK: {'YES' if report.sqlite_ok else 'NO'}")
    print(f"- Database exists: {'YES' if report.database_exists else 'NO'}")
    print(f"- Can run without blocking: {'YES' if report.can_run_without_blocking else 'NO'}")
    print(f"- API keys required: {'YES' if report.api_keys_required else 'NO'}")
    print(f"- Real trading enabled: {'YES' if report.real_trading_enabled else 'NO'}")
    print(f"- Symbols with history: {list(report.symbols_with_history)}")
    print(f"- Missing symbols: {list(report.missing_symbols)}")
    print(f"- Stale symbols: {list(report.stale_symbols)}")
    print(f"- Current mode recommended: {report.current_mode_recommended}")

    print("Symbol health:")
    for symbol in symbols:
        health = inspect_symbol_health(
            database=database,
            market_data_agent=market_data_agent,
            symbol=symbol,
            timeframe=timeframe,
        )
        print(
            f"- {symbol} {timeframe}: has_history={health.has_history} "
            f"latest_close={health.latest_close_time} age={format_age_seconds(health.age_seconds)} "
            f"stale={health.is_stale} gaps={health.gap_count} provider={health.latest_provider} note={health.note}"
        )

    print("Connectivity probes:")
    for probe in probes:
        print(
            f"- {probe.name}: {'OK' if probe.ok else 'FAIL'} latency_ms={probe.latency_ms} "
            f"interpretation={probe.interpretation} error={probe.error_message or '-'}"
        )
    return report


def build_status_snapshot(
    database: Database,
    settings: Settings,
    performance_analyzer: PerformanceAnalyzer,
    ledger_reconciler: LedgerReconciler,
) -> dict[str, object]:
    performance_report = performance_analyzer.refresh()
    candle_counts = database.list_candle_counts()
    signal_counts = database.list_signal_counts()
    recent_signals = database.get_recent_signals(limit=10)
    recent_rejected_signals = database.get_recent_rejected_signals(limit=10)
    recent_market_context = database.get_recent_market_context(limit=10)
    recent_market_snapshots = database.get_recent_market_snapshots(limit=10)
    recent_decisions = database.get_recent_agent_decisions(limit=10)
    recent_insights = database.get_recent_strategy_insights(limit=10)
    open_trades = database.get_open_simulated_trades()
    trade_metrics = database.get_simulated_trade_metrics()
    recent_trades = database.get_recent_simulated_trades(limit=10)
    recent_errors = database.get_recent_error_events(limit=10)
    portfolio = database.get_paper_portfolio()
    open_positions = database.get_open_paper_positions()
    performance_by_symbol = database.get_performance_by_symbol()
    performance_by_timeframe = database.get_performance_by_timeframe()
    recent_orders = database.get_recent_paper_orders(limit=10)
    recent_benchmarks = database.get_recent_benchmark_results(limit=10)
    recent_walk_forward = database.get_recent_walk_forward_results(limit=10)
    latest_decisions_by_agent = database.get_latest_agent_decisions_by_agent()
    ledger_report = ledger_reconciler.inspect()
    current_provider = recent_market_snapshots[0]["provider_used"] if recent_market_snapshots else "UNKNOWN"
    market_data_agent = MarketDataAgent()
    symbol_health: list[dict[str, object]] = []
    for symbol in settings.market_symbols:
        for timeframe in settings.market_timeframes:
            health = inspect_symbol_health(
                database=database,
                market_data_agent=market_data_agent,
                symbol=symbol,
                timeframe=timeframe,
            )
            symbol_health.append(
                {
                    "symbol": health.symbol,
                    "timeframe": health.timeframe,
                    "has_history": health.has_history,
                    "latest_close_time": health.latest_close_time,
                    "latest_provider": health.latest_provider,
                    "age_seconds": health.age_seconds,
                    "age_human": format_age_seconds(health.age_seconds),
                    "is_stale": health.is_stale,
                    "gap_count": health.gap_count,
                    "is_valid": health.is_valid,
                    "note": health.note,
                }
            )
    return {
        "database_path": str(settings.sqlite_path),
        "current_provider": current_provider,
        "candle_counts": candle_counts,
        "signal_counts": signal_counts,
        "recent_signals": recent_signals,
        "recent_rejected_signals": recent_rejected_signals,
        "recent_market_context": recent_market_context,
        "recent_market_snapshots": recent_market_snapshots,
        "recent_decisions": recent_decisions,
        "recent_insights": recent_insights,
        "open_trades": open_trades,
        "trade_metrics": trade_metrics,
        "recent_trades": recent_trades,
        "recent_errors": recent_errors,
        "performance_report": performance_report,
        "portfolio": portfolio,
        "open_positions": open_positions,
        "performance_by_symbol": performance_by_symbol,
        "performance_by_timeframe": performance_by_timeframe,
        "recent_orders": recent_orders,
        "recent_benchmarks": recent_benchmarks,
        "recent_walk_forward": recent_walk_forward,
        "total_agent_decisions": database.count_agent_decisions(),
        "total_paper_orders": database.count_paper_orders(),
        "open_paper_positions_count": database.count_open_paper_positions(),
        "symbol_health": symbol_health,
        "latest_decisions_by_agent": latest_decisions_by_agent,
        "ledger_report": ledger_report.as_dict(),
    }


def run_status_report(
    database: Database,
    settings: Settings,
    performance_analyzer: PerformanceAnalyzer,
    ledger_reconciler: LedgerReconciler,
) -> None:
    snapshot = build_status_snapshot(database, settings, performance_analyzer, ledger_reconciler)
    performance_report = snapshot["performance_report"]
    candle_counts = snapshot["candle_counts"]
    signal_counts = snapshot["signal_counts"]
    recent_signals = snapshot["recent_signals"]
    recent_rejected_signals = snapshot["recent_rejected_signals"]
    recent_market_context = snapshot["recent_market_context"]
    recent_market_snapshots = snapshot["recent_market_snapshots"]
    recent_decisions = snapshot["recent_decisions"]
    recent_insights = snapshot["recent_insights"]
    open_trades = snapshot["open_trades"]
    trade_metrics = snapshot["trade_metrics"]
    recent_trades = snapshot["recent_trades"]
    recent_errors = snapshot["recent_errors"]
    portfolio = snapshot["portfolio"]
    open_positions = snapshot["open_positions"]
    performance_by_symbol = snapshot["performance_by_symbol"]
    performance_by_timeframe = snapshot["performance_by_timeframe"]
    recent_orders = snapshot["recent_orders"]
    recent_benchmarks = snapshot["recent_benchmarks"]
    recent_walk_forward = snapshot["recent_walk_forward"]
    symbol_health = snapshot["symbol_health"]
    latest_decisions_by_agent = snapshot["latest_decisions_by_agent"]
    ledger_report = snapshot["ledger_report"]

    print("Status Report")
    print(f"Database path: {snapshot['database_path']}")
    print(f"Current provider: {snapshot['current_provider']}")
    print("")

    print("Candles by symbol/timeframe:")
    if candle_counts:
        for row in candle_counts:
            print(f"- {row['symbol']} {row['timeframe']}: {row['total']}")
    else:
        print("- none")
    print("")

    print("Latest candle status by symbol/timeframe:")
    if symbol_health:
        for row in symbol_health:
            print(
                f"- {row['symbol']} {row['timeframe']} history={row['has_history']} "
                f"latest_close={row['latest_close_time']} age={row['age_human']} "
                f"stale={row['is_stale']} valid={row['is_valid']} gaps={row['gap_count']} "
                f"provider={row['latest_provider']} note={row['note']}"
            )
    else:
        print("- none")
    print("")

    print("Signals by symbol:")
    if signal_counts:
        for row in signal_counts:
            print(f"- {row['symbol']}: {row['total']}")
    else:
        print("- none")
    print("")

    print("Last 10 signals:")
    if recent_signals:
        for row in recent_signals:
            print(
                f"- [{row['id']}] {row['timestamp']} {row['symbol']} {row['timeframe']} "
                f"{row['signal']} tier={row['signal_tier']} k={row['k_value']} confidence={row['confidence']} "
                f"provider={row['provider_used']}"
            )
    else:
        print("- none")
    print("")

    print("Last 10 rejected signals:")
    if recent_rejected_signals:
        for row in recent_rejected_signals:
            print(
                f"- [{row['id']}] {row['timestamp']} {row['symbol']} {row['timeframe']} "
                f"tier={row['signal_tier']} reason={row['reason']} thresholds_failed={row['thresholds_failed']}"
            )
    else:
        print("- none")
    print("")

    print("Current market snapshots:")
    if recent_market_snapshots:
        for row in recent_market_snapshots[:10]:
            print(
                f"- [{row['id']}] {row['timestamp']} {row['symbol']} {row['timeframe']} "
                f"provider={row['provider_used']} close={row['close_price']} volume={row['volume']} "
                f"valid={bool(row['is_valid'])} stale={bool(row['is_stale'])} notes={row['notes']}"
            )
    else:
        print("- none")
    print("")

    print("Last 10 market context entries:")
    if recent_market_context:
        for row in recent_market_context:
            print(
                f"- [{row['id']}] {row['timestamp']} source={row['source']} "
                f"macro={row['macro_regime']} risk={row['risk_regime']} score={row['context_score']} "
                f"provider={row.get('provider_used', 'UNKNOWN')} reason={row['reason']}"
            )
    else:
        print("- none")
    print("")

    print("Last 10 agent decisions:")
    if recent_decisions:
        for row in recent_decisions:
            print(
                f"- [{row['id']}] {row['timestamp']} {row['agent_name']} {row['symbol']} {row['timeframe']} "
                f"decision={row['decision']} confidence={row['confidence']} provider={row.get('provider_used', 'UNKNOWN')} "
                f"outcome_label={row.get('outcome_label')} reason={row['reasoning_summary']}"
            )
    else:
        print("- none")
    print("")

    print("Paper portfolio:")
    if portfolio:
        print(f"- starting capital: {portfolio['starting_capital']}")
        print(f"- available simulated cash: {portfolio['available_cash']}")
        print(f"- realized pnl: {portfolio['realized_pnl']}")
        print(f"- unrealized pnl: {portfolio['unrealized_pnl']}")
        print(f"- portfolio simulated equity: {portfolio['total_equity']}")
        print(f"- drawdown: {portfolio['drawdown']}")
        print(f"- max drawdown: {portfolio['max_drawdown']}")
        print(f"- gross exposure: {portfolio['gross_exposure']}")
        print(f"- net exposure: {portfolio['net_exposure']}")
        print(f"- total fees paid: {portfolio['total_fees_paid']}")
        print(f"- total slippage paid: {portfolio['total_slippage_paid']}")
    else:
        print("- none")
    print("")

    print("Ledger Consistency Check:")
    print(f"- open_positions_count: {ledger_report['open_positions_count']}")
    print(f"- open_simulated_trades_count: {ledger_report['open_simulated_trades_count']}")
    print(f"- orphan_positions: {ledger_report['orphan_positions']}")
    print(f"- duplicated_positions: {ledger_report['duplicated_positions']}")
    print(f"- gross_exposure: {ledger_report['gross_exposure']}")
    print(f"- net_exposure: {ledger_report['net_exposure']}")
    print(f"- unrealized_pnl: {ledger_report['unrealized_pnl']}")
    print(f"- cash_check: {ledger_report['cash_check']}")
    print(f"- equity_check: {ledger_report['equity_check']}")
    print(f"- result: {ledger_report['result']}")
    print("- notes:")
    for note in ledger_report["notes"]:
        print(f"  {note}")
    print("")

    print("Operational counters:")
    print(f"- total agent decisions: {snapshot['total_agent_decisions']}")
    print(f"- total paper orders: {snapshot['total_paper_orders']}")
    print(f"- open paper positions: {snapshot['open_paper_positions_count']}")
    print(f"- open simulated trades: {len(open_trades)}")
    print(f"- closed simulated trades: {trade_metrics['closed_trades']}")
    print("")

    print("Open paper positions:")
    if open_positions:
        for row in open_positions:
            print(
                f"- trade_id={row['trade_id']} {row['symbol']} {row['timeframe']} {row['direction']} "
                f"entry={row['entry_price']} current={row['current_price']} unrealized_pnl={row['unrealized_pnl']} "
                f"provider={row['provider_used']}"
            )
    else:
        print("- none")
    print("")

    print("Open simulated trades:")
    if open_trades:
        for trade in open_trades:
            print(
                f"- [{trade.id}] {trade.symbol} {trade.timeframe} {trade.status} {trade.direction} "
                f"entry_time={trade.entry_time} entry_price={trade.entry_price} "
                f"stop_loss={trade.stop_loss} take_profit={trade.take_profit}"
            )
    else:
        print("- none")
    print("")

    print("Closed simulated trades summary:")
    print(f"- closed trades: {trade_metrics['closed_trades']}")
    print(f"- gross winrate: {trade_metrics['gross_winrate']}%")
    print(f"- net winrate: {trade_metrics['winrate']}%")
    print(f"- gross pnl total: {trade_metrics['total_gross_pnl']}")
    print(f"- average net pnl: {trade_metrics['average_pnl']}")
    print(f"- average net pnl pct: {trade_metrics['average_pnl_pct']}%")
    print(f"- total net pnl: {trade_metrics['total_pnl']}")
    print(f"- total fees paid: {trade_metrics['total_fees_paid']}")
    print(f"- total slippage paid: {trade_metrics['total_slippage_paid']}")
    print(f"- total spread paid: {trade_metrics['total_spread_paid']}")
    print(f"- total funding estimate: {trade_metrics['total_funding_cost']}")
    print(f"- gross_win_net_loss: {trade_metrics['gross_win_net_loss']}")
    print(f"- average cost per trade: {trade_metrics['average_cost_per_trade']}")
    print("")

    print("Performance learning summary:")
    print(f"- analyzer total trades: {performance_report['total_trades']}")
    print(f"- analyzer winrate: {performance_report['winrate']}%")
    print(f"- analyzer average pnl: {performance_report['average_pnl']}")
    pnl_distribution = performance_report["pnl_distribution"]
    print(
        "- pnl distribution: "
        f"wins={pnl_distribution['wins']} losses={pnl_distribution['losses']} "
        f"breakeven={pnl_distribution['breakeven']} gross_win_net_loss={pnl_distribution.get('gross_win_net_loss', 0)}"
    )
    best_setup = performance_report.get("best_setup")
    if best_setup:
        print(
            "- best setup: "
            f"{best_setup['setup_key']} trades={best_setup['trade_count']} "
            f"winrate={best_setup['winrate']}% avg_pnl={best_setup['average_pnl']}"
        )
    else:
        print("- best setup: none")
    worst_setup = performance_report.get("worst_setup")
    if worst_setup:
        print(
            "- worst setup: "
            f"{worst_setup['setup_key']} trades={worst_setup['trade_count']} "
            f"winrate={worst_setup['winrate']}% avg_pnl={worst_setup['average_pnl']}"
        )
    else:
        print("- worst setup: none")
    print("- top 3 best setups:")
    for item in performance_report["best_setups"][:3]:
        print(
            f"  {item['setup_key']} trades={item['trade_count']} "
            f"winrate={item['winrate']}% avg_pnl={item['average_pnl']}"
        )
    if not performance_report["best_setups"]:
        print("  none")
    print("- top 3 worst setups:")
    for item in performance_report["worst_setups"][:3]:
        print(
            f"  {item['setup_key']} trades={item['trade_count']} "
            f"winrate={item['winrate']}% avg_pnl={item['average_pnl']}"
        )
    if not performance_report["worst_setups"]:
        print("  none")
    print("")

    print("Performance by trend regime:")
    trend_rows = performance_report["trade_distribution_by_regime"]["trend"]
    if trend_rows:
        for item in trend_rows:
            print(
                f"- {item['regime']} trades={item['trade_count']} "
                f"winrate={item['winrate']}% avg_pnl={item['average_pnl']}"
            )
    else:
        print("- none")
    print("")

    print("Recent benchmark results:")
    if recent_benchmarks:
        for row in recent_benchmarks[:10]:
            print(
                f"- {row['benchmark_name']} trades={row['trade_count']} winrate={row['winrate']}% "
                f"net_pnl={row['total_net_pnl']} max_drawdown={row['max_drawdown']} edge_vs_strategy={row['edge_vs_strategy']}"
            )
    else:
        print("- none")
    print("")

    print("Recent walk-forward results:")
    if recent_walk_forward:
        for row in recent_walk_forward[:10]:
            print(
                f"- train_pct={row['train_pct']} relaxation={row['selected_relaxation']} "
                f"train_net_pnl={row['train_net_pnl']} test_net_pnl={row['test_net_pnl']} "
                f"survived={bool(row['survived_out_of_sample'])}"
            )
    else:
        print("- none")
    print("")

    print("Performance by volatility regime:")
    volatility_rows = performance_report["trade_distribution_by_regime"]["volatility"]
    if volatility_rows:
        for item in volatility_rows:
            print(
                f"- {item['regime']} trades={item['trade_count']} "
                f"winrate={item['winrate']}% avg_pnl={item['average_pnl']}"
            )
    else:
        print("- none")
    print("")

    print("Performance by timeframe:")
    if performance_by_timeframe:
        for row in performance_by_timeframe:
            trade_count = int(row["trade_count"] or 0)
            wins = int(row["wins"] or 0)
            winrate = round((wins / trade_count) * 100, 2) if trade_count else 0.0
            print(
                f"- {row['timeframe']} trades={trade_count} winrate={winrate}% "
                f"avg_net_pnl={round(float(row['average_net_pnl'] or 0.0), 6)} total_net_pnl={round(float(row['total_net_pnl'] or 0.0), 6)}"
            )
    else:
        print("- none")
    print("")

    print("Performance by symbol:")
    if performance_by_symbol:
        best_symbol = performance_by_symbol[0]
        worst_symbol = performance_by_symbol[-1]
        print(
            f"- best symbol: {best_symbol['symbol']} total_net_pnl={round(float(best_symbol['total_net_pnl'] or 0.0), 6)}"
        )
        print(
            f"- worst symbol: {worst_symbol['symbol']} total_net_pnl={round(float(worst_symbol['total_net_pnl'] or 0.0), 6)}"
        )
        for row in performance_by_symbol:
            trade_count = int(row["trade_count"] or 0)
            wins = int(row["wins"] or 0)
            winrate = round((wins / trade_count) * 100, 2) if trade_count else 0.0
            print(
                f"- {row['symbol']} trades={trade_count} winrate={winrate}% "
                f"avg_net_pnl={round(float(row['average_net_pnl'] or 0.0), 6)} total_net_pnl={round(float(row['total_net_pnl'] or 0.0), 6)}"
            )
    else:
        print("- none")
    print("")

    print("Last 10 simulated trades with outcome:")
    if recent_trades:
        for trade in recent_trades:
            print(
                f"- [{trade.id}] {trade.symbol} {trade.timeframe} {trade.status} {trade.direction} "
                f"outcome={trade.outcome} entry={trade.entry_price} exit={trade.exit_price} gross_pnl={trade.gross_pnl} "
                f"net_pnl={trade.net_pnl or trade.pnl} net_pnl_pct={trade.net_pnl_pct or trade.pnl_pct} "
                f"fees={trade.total_fees} slippage={trade.slippage_cost} spread={trade.spread_cost} "
                f"provider={trade.provider_used} market_type={trade.market_type} "
                f"duration_seconds={trade.duration_seconds} "
                f"mfe={trade.max_favorable_excursion} mae={trade.max_adverse_excursion} "
                f"entry_time={trade.entry_time} exit_time={trade.exit_time}"
            )
    else:
        print("- none")
    print("")

    print("Recent paper orders:")
    if recent_orders:
        for row in recent_orders:
            print(
                f"- [{row['id']}] {row['timestamp']} {row['symbol']} {row['timeframe']} "
                f"{row['side']} requested={row['requested_price']} filled={row['filled_price']} "
                f"fees={row['fees']} slippage={row['slippage_cost']} spread={row['spread_cost']} provider={row['provider_used']}"
            )
    else:
        print("- none")
    print("")

    print("Latest decision by agent:")
    if latest_decisions_by_agent:
        for row in latest_decisions_by_agent:
            print(
                f"- {row['agent_name']}: {row['timestamp']} {row['symbol']} {row['timeframe']} "
                f"decision={row['decision']} confidence={row['confidence']} provider={row.get('provider_used', 'UNKNOWN')}"
            )
    else:
        print("- none")
    print("")

    print("Last 10 errors:")
    if recent_errors:
        for error in recent_errors:
            recoverable = bool(error["recoverable"])
            symbol = error["symbol"] or "-"
            print(
                f"- [{error['id']}] {error['timestamp']} component={error['component']} symbol={symbol} "
                f"recoverable={recoverable} {error['error_type']}: {error['error_message']}"
            )
    else:
        print("- none")
    print("")

    print("Last 10 strategy insights:")
    if recent_insights:
        for insight in recent_insights:
            print(
                f"- [{insight['id']}] {insight['insight_type']} setup={insight['setup_key']} "
                f"trades={insight['trade_count']} winrate={insight['winrate']}% "
                f"avg_pnl={insight['average_pnl']} summary={insight['summary']}"
            )
    else:
        print("- none")


def run_export_report(
    database: Database,
    settings: Settings,
    performance_analyzer: PerformanceAnalyzer,
    ledger_reconciler: LedgerReconciler,
    export_format: str,
) -> str:
    snapshot = build_status_snapshot(database, settings, performance_analyzer, ledger_reconciler)
    output_dir = settings.sqlite_path.parent
    if export_format == "csv":
        csv_targets = {
            "trades.csv": snapshot["recent_trades"],
            "decisions.csv": snapshot["recent_decisions"],
            "signals.csv": snapshot["recent_signals"],
            "portfolio.csv": [snapshot["portfolio"]] if snapshot["portfolio"] else [],
            "errors.csv": snapshot["recent_errors"],
            "benchmark.csv": snapshot["recent_benchmarks"],
        }
        for filename, rows in csv_targets.items():
            path = output_dir / filename
            if not rows:
                path.write_text("", encoding="utf-8")
                continue
            fieldnames = sorted({key for row in rows for key in row.keys()})
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: row.get(key) for key in fieldnames})
        print(f"Exported CSV report bundle to {output_dir}")
        return str(output_dir)

    output_path = output_dir / "report_export.json"
    enriched_snapshot = {
        "summary": {
            "portfolio": snapshot["portfolio"],
            "ledger_consistency": snapshot["ledger_report"],
            "provider_used": snapshot["current_provider"],
            "symbols": list(settings.market_symbols),
            "timeframes": list(settings.market_timeframes),
            "supported_execution_timeframes": list(settings.execution_timeframes),
            "supported_context_timeframes": list(settings.context_timeframes),
            "supported_structural_timeframes": list(settings.structural_timeframes),
            "gross_vs_net": snapshot["trade_metrics"],
            "best_setups": snapshot["performance_report"].get("best_setups", []),
            "worst_setups": snapshot["performance_report"].get("worst_setups", []),
            "best_symbols": snapshot["performance_by_symbol"][:3],
            "worst_symbols": list(reversed(snapshot["performance_by_symbol"][-3:])) if snapshot["performance_by_symbol"] else [],
            "best_timeframes": snapshot["performance_by_timeframe"][:3],
            "worst_timeframes": list(reversed(snapshot["performance_by_timeframe"][-3:])) if snapshot["performance_by_timeframe"] else [],
            "readiness": {
                "ledger_result": snapshot["ledger_report"]["result"],
                "current_provider": snapshot["current_provider"],
                "stale_rows": [row for row in snapshot["symbol_health"] if row["is_stale"]],
            },
        },
        "details": snapshot,
    }
    output_path.write_text(json.dumps(enriched_snapshot, ensure_ascii=True, indent=2, default=str), encoding="utf-8")
    print(f"Exported report to {output_path}")
    return str(output_path)


def run_live_paper_engine(
    live_paper_engine: LivePaperEngine,
    *,
    symbols: tuple[str, ...],
    timeframes: tuple[str, ...],
    max_loops: int | None,
    run_minutes: int | None,
    binance_http_ok: bool,
    allow_stale_fallback: bool,
) -> LivePaperEngineResult:
    result = live_paper_engine.run(
        symbols=symbols,
        timeframes=timeframes,
        max_loops=max_loops,
        run_minutes=run_minutes,
        binance_http_ok=binance_http_ok,
        allow_stale_fallback=allow_stale_fallback,
    )
    print("Live Paper Engine Summary")
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Timeframes: {', '.join(timeframes)}")
    print(f"Loops completed: {result.loops_completed}")
    print(f"Decisions persisted: {result.decisions_persisted}")
    print(f"Trades opened: {result.trades_opened}")
    print(f"Trades closed: {result.trades_closed}")
    return result


def run_continuous_engine(
    *,
    database: Database,
    market_data_service: BinanceMarketDataService,
    delta_agent: DeltaAgent,
    market_context_agent: MarketContextAgent,
    simulated_trade_tracker: SimulatedTradeTracker,
    performance_analyzer: PerformanceAnalyzer,
    symbols: tuple[str, ...],
    timeframe: str,
    loop_seconds: int,
    max_loops: int | None,
) -> None:
    last_processed_open_time: dict[str, str] = {}
    loop_count = 0

    while True:
        try:
            loop_count += 1
            logger.info(
                "Continuous engine cycle started",
                extra={
                    "event": "continuous_cycle_start",
                    "context": {
                        "loop_count": loop_count,
                        "symbols": list(symbols),
                        "timeframe": timeframe,
                    },
                },
            )

            for symbol in symbols:
                try:
                    _process_continuous_symbol(
                        database=database,
                        market_data_service=market_data_service,
                        delta_agent=delta_agent,
                        market_context_agent=market_context_agent,
                        simulated_trade_tracker=simulated_trade_tracker,
                        symbol=symbol,
                        timeframe=timeframe,
                        last_processed_open_time=last_processed_open_time,
                    )
                except TradingSystemError as exc:
                    persist_error_event(
                        database,
                        component="continuous_engine",
                        symbol=symbol,
                        error=exc,
                        recoverable=True,
                    )
                    logger.exception(
                        "Continuous symbol processing failed",
                        extra={
                            "event": "continuous_symbol_error",
                            "context": {"symbol": symbol, "timeframe": timeframe, "error": str(exc)},
                        },
                    )
                except Exception as exc:
                    persist_error_event(
                        database,
                        component="continuous_engine",
                        symbol=symbol,
                        error=exc,
                        recoverable=True,
                    )
                    logger.exception(
                        "Unexpected continuous symbol failure",
                        extra={
                            "event": "continuous_symbol_error",
                            "context": {"symbol": symbol, "timeframe": timeframe, "error": str(exc)},
                        },
                    )

            performance_analyzer.refresh()
        except Exception as exc:
            persist_error_event(
                database,
                component="continuous_cycle",
                symbol=None,
                error=exc,
                recoverable=True,
            )
            logger.exception(
                "Continuous engine cycle failed",
                extra={
                    "event": "continuous_cycle_error",
                    "context": {"loop_count": loop_count, "timeframe": timeframe, "error": str(exc)},
                },
            )

        if max_loops is not None and loop_count >= max_loops:
            logger.info(
                "Continuous engine stopped by max loops",
                extra={"event": "continuous_cycle_stop", "context": {"loop_count": loop_count}},
            )
            return

        time.sleep(loop_seconds)


def _process_continuous_symbol(
    *,
    database: Database,
    market_data_service: BinanceMarketDataService,
    delta_agent: DeltaAgent,
    market_context_agent: MarketContextAgent,
    simulated_trade_tracker: SimulatedTradeTracker,
    symbol: str,
    timeframe: str,
    last_processed_open_time: dict[str, str],
) -> None:
    analysis_timestamp = datetime.now(timezone.utc).isoformat()
    used_fallback = False

    try:
        closed_candles = market_data_service.fetch_latest_closed_candles(symbol=symbol, timeframe=timeframe, limit=2)
    except TradingSystemError as exc:
        used_fallback = True
        persist_error_event(
            database,
            component="market_data_fetch",
            symbol=symbol,
            error=exc,
            recoverable=True,
        )
        logger.warning(
            "Market data fetch failed, using SQLite fallback",
            extra={
                "event": "fetch_fallback",
                "context": {"symbol": symbol, "timeframe": timeframe, "error": str(exc)},
            },
        )
        closed_candles = database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=20)

    if not closed_candles:
        decision_timestamp = datetime.now(timezone.utc).isoformat()
        database.insert_agent_decision(
            AgentDecisionRecord(
                timestamp=decision_timestamp,
                agent_name="DeltaAgent",
                symbol=symbol,
                timeframe=timeframe,
                decision="NO_DATA",
                confidence=0.0,
                inputs_used=json.dumps({"source": "none"}, ensure_ascii=True),
                reasoning_summary="NO_DATA because no candles are available in SQLite for analysis",
                linked_signal_id=None,
                linked_trade_id=None,
            )
        )
        logger.info(
            "No data available for market analysis",
            extra={
                "event": "decision",
                "context": {"symbol": symbol, "timeframe": timeframe, "decision": "NO_DATA"},
            },
        )
        print(f"{symbol}: decision=NO_DATA confidence=0.0 reason=no candles available")
        return

    latest_candle = closed_candles[-1]
    if not used_fallback and last_processed_open_time.get(symbol) != latest_candle.open_time:
        insert_result = database.insert_candles(closed_candles)
        logger.info(
            "Continuous market data synced",
            extra={
                "event": "fetch",
                "context": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "inserted": insert_result.inserted,
                    "duplicates": insert_result.duplicates,
                    "open_time": latest_candle.open_time,
                },
            },
        )

    recent_candles = database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=20)
    latest_stored_candle = recent_candles[-1]
    market_context = market_context_agent.evaluate(symbol=symbol, timeframe=timeframe, candles=recent_candles)
    database.insert_market_context(
        MarketContextRecord(
            timestamp=analysis_timestamp,
            source="MarketContextAgent",
            macro_regime=str(market_context["macro_regime"]),
            risk_regime=str(market_context["risk_regime"]),
            context_score=float(market_context["context_score"]),
            reason=str(market_context["reason"]),
            raw_payload=json.dumps(market_context, ensure_ascii=True),
        )
    )
    logger.info(
        "Market context evaluated",
        extra={
            "event": "market_context",
            "context": {
                "symbol": symbol,
                "timeframe": timeframe,
                "trend_direction": market_context["trend_direction"],
                "volatility_regime": market_context["volatility_regime"],
                "market_regime": market_context["market_regime"],
                "momentum_strength": market_context["momentum_strength"],
                "volatility_pct": market_context["volatility_pct"],
                "volume_spike": market_context["volume_spike"],
                "volume_regime": market_context["volume_regime"],
                "source": "sqlite_fallback" if used_fallback else "binance_and_sqlite",
            },
        },
    )

    signal = delta_agent.evaluate(symbol=symbol, timeframe=timeframe, market_context=market_context)
    signal_id: int | None = None
    if not used_fallback and last_processed_open_time.get(symbol) != latest_candle.open_time:
        signal_id = database.insert_signal_log(
            SignalLogRecord(
                symbol=symbol,
                timeframe=timeframe,
                signal=str(signal["signal_type"]),
                signal_tier=str(signal["signal_tier"]),
                k_value=float(signal["k_value"]),
                confidence=float(signal["confidence"]),
                timestamp=str(signal["timestamp"]),
            )
        )
        logger.info(
            "Structured signal logged",
            extra={
                "event": "signal",
                "context": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "signal": signal["signal_type"],
                    "k_value": signal["k_value"],
                    "confidence": signal["confidence"],
                    "timestamp": signal["timestamp"],
                    "reason": signal["reason"],
                },
            },
        )

    trade_result = simulated_trade_tracker.process_cycle(
        symbol=symbol,
        timeframe=timeframe,
        signal=signal,
        latest_candle=latest_stored_candle,
        signal_id=signal_id,
    )
    if str(signal["signal_type"]) == "NONE":
        persist_rejected_signal(database, signal, str(signal["reason"]))
    elif not trade_result.opened and trade_result.active_trade_id is not None:
        persist_rejected_signal(database, signal, "existing_open_trade")

    decision_id = database.insert_agent_decision(
        AgentDecisionRecord(
            timestamp=analysis_timestamp,
            agent_name="DeltaAgent",
            symbol=symbol,
            timeframe=timeframe,
            decision=str(signal["signal_type"]),
            confidence=float(signal["confidence"]),
            inputs_used=json.dumps(
                {
                    "k_value": signal["k_value"],
                    "signal_strength": signal["signal_strength"],
                    "signal_tier": signal["signal_tier"],
                    "roc_price": signal["roc_price"],
                    "roc_volume": signal["roc_volume"],
                    "price": signal["price"],
                    "volume": signal["volume"],
                    "trend_direction": signal["trend_direction"],
                    "volatility_regime": signal["volatility_regime"],
                    "momentum_strength": signal["momentum_strength"],
                    "volatility_pct": signal["volatility_pct"],
                    "volume_regime": signal["volume_regime"],
                    "market_regime": signal["market_regime"],
                    "decision_type": signal["decision_type"],
                    "setup_signature": signal["setup_signature"],
                    "thresholds_failed": list(signal["thresholds_failed"]),
                },
                ensure_ascii=True,
            ),
            reasoning_summary=str(signal["explanation"]),
            linked_signal_id=signal_id,
            linked_trade_id=trade_result.opened_trade_id or trade_result.active_trade_id or trade_result.closed_trade_id,
        )
    )
    logger.info(
        "Agent decision persisted",
        extra={
            "event": "decision",
            "context": {
                "decision_id": decision_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "decision": signal["signal_type"],
                "confidence": signal["confidence"],
                "reason": signal["reason"],
                "risks_detected": list(signal["risks_detected"]),
            },
        },
    )

    stats = simulated_trade_tracker.build_stats(symbol)
    print(
        f"{symbol}: signal={signal['signal_type']} confidence={signal['confidence']} trend={signal['trend_direction']} "
        f"regime={signal['market_regime']} open_trades={stats.open_trades} closed_trades={stats.closed_trades} "
        f"winrate={stats.winrate}% avg_pnl={stats.average_pnl} total_pnl={stats.cumulative_pnl}"
    )
    last_processed_open_time[symbol] = latest_candle.open_time


def main() -> int:
    settings = load_settings()
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(settings)

    (
        symbols,
        timeframes,
        timeframe,
        limit,
        min_trades,
        delta_threshold,
        delta_windows,
        evaluation_windows,
        optimization_thresholds,
    ) = resolve_runtime_settings(settings, args)
    database = Database(settings.sqlite_path)
    service = BinanceMarketDataService(settings)
    delta_agent = DeltaAgent(database=database, threshold=delta_threshold, settings=settings)
    market_context_agent = MarketContextAgent(database=database)
    signal_evaluator = SignalEvaluator(database=database, delta_agent=delta_agent)
    performance_analyzer = PerformanceAnalyzer(database=database)
    paper_trader = PaperTrader(
        database=database,
        market_data_service=service,
        delta_agent=delta_agent,
        settings=settings,
    )
    simulated_trade_tracker = SimulatedTradeTracker(database=database, settings=settings)
    provider_router = ProviderRouter(
        primary=BinanceProvider(service),
        fallbacks=(LocalSQLiteProvider(database), FutureYahooProvider()),
    )
    market_data_agent = MarketDataAgent()
    risk_reward_agent = RiskRewardAgent(settings)
    cost_model_agent = CostModelAgent(settings)
    performance_learning_agent = PerformanceLearningAgent(database, settings)
    symbol_selection_agent = SymbolSelectionAgent(settings)
    execution_simulator_agent = ExecutionSimulatorAgent(database, simulated_trade_tracker)
    audit_agent = AuditAgent()
    decision_orchestrator = DecisionOrchestrator(settings)
    ledger_reconciler = LedgerReconciler(database, settings)
    live_paper_engine = LivePaperEngine(
        database=database,
        settings=settings,
        provider_router=provider_router,
        market_data_agent=market_data_agent,
        market_context_agent=market_context_agent,
        delta_agent=delta_agent,
        risk_reward_agent=risk_reward_agent,
        cost_model_agent=cost_model_agent,
        performance_learning_agent=performance_learning_agent,
        symbol_selection_agent=symbol_selection_agent,
        execution_simulator_agent=execution_simulator_agent,
        audit_agent=audit_agent,
        decision_orchestrator=decision_orchestrator,
        performance_analyzer=performance_analyzer,
    )
    backtest_engine = BacktestEngine(
        database=database,
        delta_agent=delta_agent,
        market_context_agent=market_context_agent,
        simulated_trade_tracker=simulated_trade_tracker,
        performance_analyzer=performance_analyzer,
    )
    benchmark_engine = BenchmarkEngine(
        database=database,
        settings=settings,
        backtest_engine=backtest_engine,
    )
    walk_forward_engine = WalkForwardEngine(
        database=database,
        settings=settings,
        delta_agent=delta_agent,
        market_context_agent=market_context_agent,
        cost_model_agent=cost_model_agent,
    )
    had_errors = False

    try:
        log_startup(
            settings,
            symbols,
            timeframe,
            limit,
            delta_threshold,
            delta_windows,
            evaluation_windows,
            optimization_thresholds,
        )
        initialize_database(database, str(settings.sqlite_path))

        if args.init_only:
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "init_only"}},
            )
            print(f"SQLite inicializada en {settings.sqlite_path}")
            return 0

        if args.diagnose_connectivity:
            run_diagnose_connectivity(service)
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "diagnose_connectivity_success"}},
            )
            return 0

        if args.readiness_check:
            run_readiness_check(
                settings=settings,
                database=database,
                service=service,
                market_data_agent=market_data_agent,
                symbols=symbols,
                timeframe=timeframe,
            )
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "readiness_check_success"}},
            )
            return 0

        if args.status_report:
            run_status_report(database, settings, performance_analyzer, ledger_reconciler)
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "status_report_success"}},
            )
            return 0

        if args.export_report:
            run_export_report(database, settings, performance_analyzer, ledger_reconciler, args.format)
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "export_report_success"}},
            )
            return 0

        if args.reconcile_ledger:
            report = run_reconcile_ledger(ledger_reconciler)
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": f"reconcile_ledger_{report.result.lower()}" }},
            )
            return 0 if report.result == "OK" else 1

        if args.backtest:
            run_backtest(
                backtest_engine,
                symbols=symbols,
                timeframes=timeframes,
                limit=limit,
                min_trades=min_trades,
            )
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "backtest_success"}},
            )
            return 0

        if args.benchmark:
            run_benchmark(
                benchmark_engine,
                symbols=symbols,
                timeframes=timeframes,
                limit=limit,
                min_trades=min_trades,
            )
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "benchmark_success"}},
            )
            return 0

        if args.walk_forward:
            run_walk_forward(
                walk_forward_engine,
                symbols=symbols,
                timeframes=timeframes,
                limit=limit,
                train_pct=args.train_pct or 70,
            )
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "walk_forward_success"}},
            )
            return 0

        if args.load_history:
            successful_symbols: list[str] = []
            failed_symbols: list[str] = []
            total_inserted = 0
            total_duplicates = 0
            for symbol in symbols:
                try:
                    result = load_history_for_symbol(
                        database=database,
                        service=service,
                        symbol=symbol,
                        timeframe=timeframe,
                        limit=limit,
                    )
                    successful_symbols.append(symbol)
                    total_inserted += int(result["inserted"])
                    total_duplicates += int(result["duplicates"])
                except TradingSystemError as exc:
                    had_errors = True
                    failed_symbols.append(symbol)
                    persist_error_event(
                        database,
                        component="load_history",
                        symbol=symbol,
                        error=exc,
                        recoverable=True,
                    )
                    logger.exception(
                        "History loading failed",
                        extra={"event": "history_load_error", "context": {"symbol": symbol, "timeframe": timeframe}},
                    )
            print("Load History Summary")
            print(f"successful_symbols={successful_symbols}")
            print(f"failed_symbols={failed_symbols}")
            print(f"candles_inserted={total_inserted}")
            print(f"duplicates={total_duplicates}")
            logger.info(
                "Clean shutdown",
                extra={
                    "event": "shutdown",
                    "context": {"status": "load_history_success" if not had_errors else "load_history_partial"},
                },
            )
            return 1 if had_errors else 0

        if args.delta_test:
            for symbol in symbols:
                run_delta_test(delta_agent, symbol, timeframe, delta_windows)
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "delta_test_success"}},
            )
            return 0

        if args.evaluate_signals:
            for symbol in symbols:
                run_signal_evaluation(signal_evaluator, symbol, timeframe, evaluation_windows)
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "evaluate_signals_success"}},
            )
            return 0

        if args.evaluate_direction:
            for symbol in symbols:
                run_direction_evaluation(signal_evaluator, symbol, timeframe, evaluation_windows)
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "evaluate_direction_success"}},
            )
            return 0

        if args.optimize_threshold:
            for symbol in symbols:
                run_threshold_optimization(
                    signal_evaluator,
                    symbol,
                    timeframe,
                    optimization_thresholds,
                    evaluation_windows,
                )
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "optimize_threshold_success"}},
            )
            return 0

        if args.paper_trade:
            run_paper_trading(
                paper_trader,
                symbols=symbols,
                timeframe=timeframe,
                max_cycles=args.paper_cycles,
            )
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "paper_trade_success"}},
            )
            return 0

        if args.continuous_engine:
            run_continuous_engine(
                database=database,
                market_data_service=service,
                delta_agent=delta_agent,
                market_context_agent=market_context_agent,
                simulated_trade_tracker=simulated_trade_tracker,
                performance_analyzer=performance_analyzer,
                symbols=symbols,
                timeframe=timeframe,
                loop_seconds=settings.continuous_loop_seconds,
                max_loops=args.max_loops,
            )
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "continuous_engine_success"}},
            )
            return 0

        if args.live_paper_engine:
            probes = service.diagnose_connectivity()
            binance_http_ok = all(probe.ok for probe in probes[:2]) if len(probes) >= 2 else all(probe.ok for probe in probes)
            ledger_report = ledger_reconciler.inspect()
            logger.info(
                "Live paper provider policy evaluated",
                extra={
                    "event": "live_paper_provider_policy",
                    "context": {
                        "binance_http_ok": binance_http_ok,
                        "ledger_result": ledger_report.result,
                        "allow_stale_fallback": args.allow_stale_fallback,
                        "max_loops": args.max_loops,
                        "run_minutes": args.run_minutes,
                    },
                },
            )
            if ledger_report.result != "OK" and args.max_loops is None:
                print("Live paper engine blocked for long run because ledger consistency is not OK.")
                print(f"Ledger result: {ledger_report.result}")
                for note in ledger_report.notes:
                    print(f"- {note}")
                return 1
            run_live_paper_engine(
                live_paper_engine,
                symbols=symbols,
                timeframes=timeframes,
                max_loops=args.max_loops,
                run_minutes=args.run_minutes,
                binance_http_ok=binance_http_ok,
                allow_stale_fallback=args.allow_stale_fallback,
            )
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "live_paper_engine_success"}},
            )
            return 0

        if args.delta_only:
            for symbol in symbols:
                run_delta_agent(delta_agent, symbol, timeframe)
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "delta_only_success"}},
            )
            return 0

        for symbol in symbols:
            try:
                process_symbol(
                    database=database,
                    service=service,
                    delta_agent=delta_agent,
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=limit,
                )
            except TradingSystemError as exc:
                had_errors = True
                persist_error_event(
                    database,
                    component="process_symbol",
                    symbol=symbol,
                    error=exc,
                    recoverable=True,
                )
                logger.exception(
                    "Symbol processing failed",
                    extra={
                        "event": "symbol_error",
                        "context": {"symbol": symbol, "timeframe": timeframe},
                    },
                )

        logger.info(
            "Clean shutdown",
            extra={
                "event": "shutdown",
                "context": {"status": "completed_with_errors" if had_errors else "success"},
            },
        )
        return 1 if had_errors else 0
    except TradingSystemError as exc:
        persist_error_event(
            database,
            component="main",
            symbol=None,
            error=exc,
            recoverable=False,
        )
        logger.exception("Fatal application error", extra={"event": "fatal_error"})
        return 1
    except Exception as exc:
        persist_error_event(
            database,
            component="main",
            symbol=None,
            error=exc,
            recoverable=False,
        )
        logger.exception("Unexpected fatal error", extra={"event": "fatal_error"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
