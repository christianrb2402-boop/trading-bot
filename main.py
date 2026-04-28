from __future__ import annotations

import argparse
import logging
import time

from agents.delta_agent import DeltaAgent
from agents.signal_evaluator import SignalEvaluator
from config.settings import Settings, load_settings
from core.database import Database, SignalLogRecord
from core.exceptions import TradingSystemError
from core.logger import configure_logging
from data.binance_market_data import Candle, BinanceMarketDataService
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
    parser.add_argument("--symbols", nargs="+", help="Lista de simbolos, ejemplo BTCUSDT ETHUSDT")
    parser.add_argument("--timeframe", help="Timeframe, ejemplo 1m")
    parser.add_argument("--limit", type=int, help="Cantidad de velas por simbolo")
    parser.add_argument("--delta-threshold", type=float, help="Threshold para la metrica k")
    parser.add_argument("--delta-windows", nargs="+", type=int, help="Ventanas para delta-test, ejemplo 10 20 50")
    parser.add_argument("--evaluation-windows", nargs="+", type=int, help="Horizontes post-senal, ejemplo 5 10 15")
    parser.add_argument("--optimization-thresholds", nargs="+", type=float, help="Thresholds a comparar, ejemplo 0.5 1.0 1.5 2.0")
    parser.add_argument("--paper-cycles", type=int, help="Cantidad de ciclos de paper trading para pruebas")
    parser.add_argument("--max-loops", type=int, help="Cantidad de iteraciones para pruebas del motor continuo")
    return parser


def resolve_runtime_settings(
    base: Settings,
    args: argparse.Namespace,
) -> tuple[tuple[str, ...], str, int, float, tuple[int, ...], tuple[int, ...], tuple[float, ...]]:
    symbols = tuple(symbol.upper() for symbol in args.symbols) if args.symbols else base.market_symbols
    timeframe = args.timeframe or base.market_timeframe
    limit = args.limit or base.binance_klines_limit
    delta_threshold = args.delta_threshold if args.delta_threshold is not None else base.delta_k_threshold
    delta_windows = tuple(args.delta_windows) if args.delta_windows else base.delta_test_windows
    evaluation_windows = tuple(args.evaluation_windows) if args.evaluation_windows else base.signal_evaluation_windows
    optimization_thresholds = (
        tuple(args.optimization_thresholds) if args.optimization_thresholds else base.delta_optimization_thresholds
    )
    return symbols, timeframe, limit, delta_threshold, delta_windows, evaluation_windows, optimization_thresholds


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
) -> None:
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
                "signal": result["signal"],
                "signal_type": result["signal_type"],
                "k_value": result["k_value"],
                "confidence": result["confidence"],
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


def run_continuous_engine(
    *,
    database: Database,
    market_data_service: BinanceMarketDataService,
    delta_agent: DeltaAgent,
    simulated_trade_tracker: SimulatedTradeTracker,
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
                        simulated_trade_tracker=simulated_trade_tracker,
                        symbol=symbol,
                        timeframe=timeframe,
                        last_processed_open_time=last_processed_open_time,
                    )
                except TradingSystemError as exc:
                    logger.exception(
                        "Continuous symbol processing failed",
                        extra={
                            "event": "continuous_symbol_error",
                            "context": {"symbol": symbol, "timeframe": timeframe, "error": str(exc)},
                        },
                    )
                except Exception as exc:
                    logger.exception(
                        "Unexpected continuous symbol failure",
                        extra={
                            "event": "continuous_symbol_error",
                            "context": {"symbol": symbol, "timeframe": timeframe, "error": str(exc)},
                        },
                    )
        except Exception as exc:
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
    simulated_trade_tracker: SimulatedTradeTracker,
    symbol: str,
    timeframe: str,
    last_processed_open_time: dict[str, str],
) -> None:
    closed_candles = market_data_service.fetch_latest_closed_candles(symbol=symbol, timeframe=timeframe, limit=2)
    if len(closed_candles) < 2:
        return

    latest_candle = closed_candles[-1]
    if last_processed_open_time.get(symbol) == latest_candle.open_time:
        return

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

    signal = delta_agent.evaluate(symbol=symbol, timeframe=timeframe)
    database.insert_signal_log(
        SignalLogRecord(
            symbol=symbol,
            timeframe=timeframe,
            signal=str(signal["signal_type"]),
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
            },
        },
    )

    latest_stored_candle = database.get_recent_candles(symbol=symbol, timeframe=timeframe, limit=1)[-1]
    simulated_trade_tracker.process_signal(
        symbol=symbol,
        timeframe=timeframe,
        signal=signal,
        latest_candle=latest_stored_candle,
    )
    stats = simulated_trade_tracker.build_stats(symbol)
    print(
        f"{symbol}: signal={signal['signal_type']} k={signal['k_value']} confidence={signal['confidence']} "
        f"trades={stats.total_trades} winrate={stats.winrate}% pnl={stats.cumulative_pnl}% drawdown={stats.drawdown}%"
    )
    last_processed_open_time[symbol] = latest_candle.open_time


def main() -> int:
    settings = load_settings()
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(settings)

    (
        symbols,
        timeframe,
        limit,
        delta_threshold,
        delta_windows,
        evaluation_windows,
        optimization_thresholds,
    ) = resolve_runtime_settings(settings, args)
    database = Database(settings.sqlite_path)
    service = BinanceMarketDataService(settings)
    delta_agent = DeltaAgent(database=database, threshold=delta_threshold)
    signal_evaluator = SignalEvaluator(database=database, delta_agent=delta_agent)
    paper_trader = PaperTrader(
        database=database,
        market_data_service=service,
        delta_agent=delta_agent,
        settings=settings,
    )
    simulated_trade_tracker = SimulatedTradeTracker(
        database=database,
        exit_after_candles=settings.simulated_trade_exit_candles,
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

        if args.load_history:
            for symbol in symbols:
                load_history_for_symbol(
                    database=database,
                    service=service,
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=limit,
                )
            logger.info(
                "Clean shutdown",
                extra={"event": "shutdown", "context": {"status": "load_history_success"}},
            )
            return 0

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
                simulated_trade_tracker=simulated_trade_tracker,
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
            except TradingSystemError:
                had_errors = True
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
    except TradingSystemError:
        logger.exception("Fatal application error", extra={"event": "fatal_error"})
        return 1
    except Exception:
        logger.exception("Unexpected fatal error", extra={"event": "fatal_error"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
