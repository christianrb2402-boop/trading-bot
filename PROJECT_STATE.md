# Project State

## Current Project Goal

- Build a crypto market intelligence and paper-trading research system.
- Keep everything simulated, auditable and SQLite-backed.
- Do not enable real-money trading.
- Do not require private API keys.
- Use public Binance HTTP market data when reachable.
- Fall back to local SQLite only as an emergency or bounded validation path.
- Force every paper trade to justify costs before opening.

## Implemented Modules

- `main.py`
- `config/settings.py`
- `core/database.py`
- `core/logger.py`
- `core/runtime_checks.py`
- `core/ledger_reconciler.py`
- `data/binance_market_data.py`
- `data/market_data_provider.py`
- `agents/delta_agent.py`
- `agents/market_data_agent.py`
- `agents/market_context_agent.py`
- `agents/symbol_selection_agent.py`
- `agents/risk_reward_agent.py`
- `agents/cost_model_agent.py`
- `agents/performance_learning_agent.py`
- `agents/execution_simulator_agent.py`
- `agents/decision_orchestrator.py`
- `agents/audit_agent.py`
- `analytics/backtest_engine.py`
- `analytics/benchmark_engine.py`
- `analytics/performance_analyzer.py`
- `analytics/walk_forward_engine.py`
- `execution/simulated_trade_tracker.py`
- `execution/live_paper_engine.py`
- `README.md`
- `RUNBOOK_LOCAL_WINDOWS.md`
- `AUDIT_PACKET.md`

## Implemented Agents

- `MarketDataAgent`
- `MarketContextAgent`
- `DeltaAgent`
- `SymbolSelectionAgent`
- `RiskRewardAgent`
- `CostModelAgent`
- `PerformanceLearningAgent`
- `ExecutionSimulatorAgent`
- `DecisionOrchestrator`
- `AuditAgent`

## Implemented Commands

- `python main.py --init-only`
- `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000`
- `python main.py --diagnose-connectivity`
- `python main.py --readiness-check`
- `python main.py --reconcile-ledger`
- `python main.py --backtest --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d" --min-trades 100`
- `python main.py --benchmark --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d"`
- `python main.py --walk-forward --limit 10000 --train-pct 70 --timeframes "1m,5m,15m,30m,1h,4h,1d"`
- `python main.py --live-paper-engine`
- `python main.py --live-paper-engine --max-loops 5`
- `python main.py --live-paper-engine --run-minutes 60`
- `python main.py --live-paper-engine --allow-stale-fallback`
- `python main.py --status-report`
- `python main.py --export-report`
- `python main.py --export-report --format csv`

## Supported Timeframes

- `MARKET_TIMEFRAMES=1m,5m,15m,30m,1h,4h,1d`
- `EXECUTION_TIMEFRAMES=1m,5m,15m`
- `CONTEXT_TIMEFRAMES=30m,1h,4h,1d`
- `STRUCTURAL_TIMEFRAMES=1w,1M`

PowerShell note:
- For CLI runs using `--timeframes`, quote the value.
- Example: `--timeframes "1m,5m,15m,30m,1h,4h,1d"`

## Active Symbol Universe

- Core active:
  - `BTCUSDT`
  - `ETHUSDT`
  - `BNBUSDT`
  - `SOLUSDT`
  - `XRPUSDT`
- Watchlist prepared but disabled by default:
  - `DOGEUSDT`
  - `ADAUSDT`
  - `AVAXUSDT`
  - `LINKUSDT`
  - `LTCUSDT`
  - `DOTUSDT`
  - `MATICUSDT`
  - `TRXUSDT`
  - `BCHUSDT`
  - `NEARUSDT`
  - `ARBUSDT`
  - `OPUSDT`

## SQLite Tables Currently Used

- `candles`
- `signals_log`
- `rejected_signals_log`
- `simulated_trades`
- `agent_decisions`
- `error_events`
- `market_context`
- `market_snapshots`
- `strategy_insights`
- `paper_portfolio`
- `paper_positions`
- `paper_orders`
- `paper_trade_ledger`
- `paper_equity_curve`
- `benchmark_results`
- `walk_forward_results`

## What Is Working

- SQLite initialization and safe schema migration.
- Historical backtest with no future leakage.
- Benchmark mode against multiple baselines.
- Walk-forward split with out-of-sample evaluation.
- Cost-aware simulated trades with gross and net PnL separated.
- Ledger reconciliation and consistency reporting.
- Duplicate setup rejection by `symbol/timeframe/direction/entry_time/setup_signature`.
- Multi-timeframe context storage and reporting.
- Connectivity diagnosis based on real HTTP requests, not `nslookup`.
- Readiness evaluation for long live-paper execution.
- Safe bounded live-paper execution with fallback logic.
- JSON and CSV export reports.
- Windows runbook and `.bat` launchers for local operation.

## What Is Not Working

- Fresh Binance HTTP access is still failing in the current Codex environment.
- `--load-history` cannot fetch fresh candles from Binance in the current Codex environment.
- Current local data is stale and gap-prone.
- `BNBUSDT`, `SOLUSDT` and `XRPUSDT` still have no local history in SQLite here.
- The strategy remains clearly negative after costs.

## Current Data Source Status

### Fixed Windows target machine

- Operator validation confirms:
  - `https://api.binance.com/api/v3/time` responds correctly
  - `https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=5` responds correctly
- Interpretation:
  - Binance is usable there by HTTP
  - `nslookup` failure alone is not a fatal signal

### Current Codex environment

- Latest validated status:
  - `--diagnose-connectivity` returned `BINANCE_HTTP_USABLE: NO`
  - HTTP calls failed with `WinError 10061`
- Interpretation:
  - This environment is not suitable for fresh Binance ingestion right now
  - Bounded validation is using `LOCAL_SQLITE`

## Current Runtime Reality

- Backtest is running from historical SQLite replay.
- Current live-paper bounded validation is using `LOCAL_SQLITE`.
- Current latest market snapshots are stale for `1m`, `5m`, `15m`, `30m`, `1h`, `4h`.
- `1d` materialized context can appear valid structurally, but the underlying local dataset is still stale overall.
- Fallback is safe and auditable, but not suitable for a long fresh live-paper run here.

## Current Readiness Level

- In the current Codex environment:
  - `READY_FOR_LIVE_PAPER: NO`
  - recommended mode: `DO_NOT_RUN_LONG`
- Ledger status after final reconciliation:
  - `Ledger Consistency Check: OK`
- On the fixed Windows machine:
  - readiness is still not assumed until `--diagnose-connectivity`, `--load-history` and `--readiness-check` pass there

## Latest Validation Snapshot

- `--init-only`: passed
- `--diagnose-connectivity`: passed as command, result `BINANCE_HTTP_USABLE: NO` here
- `--reconcile-ledger`: passed, final result `OK`
- `--status-report`: passed
- `--load-history` for `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`: all failed here with `WinError 10061`
- `--readiness-check`: passed as command, result `READY_FOR_LIVE_PAPER: NO`
- `--backtest --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d" --min-trades 100`: passed
- `--benchmark --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d"`: passed
- `--walk-forward --limit 10000 --train-pct 70`: passed
- `--live-paper-engine --max-loops 5`: passed in bounded fallback mode
- `--export-report`: passed
- `--export-report --format csv`: passed

## Current Performance Reality

- The strategy is losing after costs.
- Latest reconciled backtest state:
  - `closed trades: 159`
  - `gross winrate: 7.55%`
  - `net winrate: 5.03%`
  - `gross pnl total: -16.388537`
  - `total net pnl: -59.309828`
  - `fees: 31.791287`
  - `slippage: 7.95`
  - `spread: 3.18`
- Benchmark result:
  - `BOT_STRATEGY total_net_pnl: -59.431848`
  - `BUY_AND_HOLD total_net_pnl: -12.278755`
  - `RANDOM_ENTRY total_net_pnl: -50.544552`
  - `NO_TRADE total_net_pnl: 0.0`
- Walk-forward result:
  - `selected_relaxation: 0.3`
  - `test_net_pnl: -7.17661`
  - `survived_out_of_sample: False`

## Known Limitations

- No real trading.
- No API keys.
- No private order execution.
- No dashboard.
- No paid data sources.
- No macro/news feeds yet.
- Local history is incomplete here.
- Current local history contains gaps and stale segments.
- Strategy quality is still poor after costs.
- Backtest and benchmark currently use the enhanced Delta engine and cost filters, but the full live committee hierarchy is still strongest in `live_paper_engine`.
- On PowerShell, unquoted `--timeframes` can distort values like `1d`; commands should quote the timeframe list.

## Next Recommended Step

1. Move to the fixed Windows machine without VPN.
2. Run `python main.py --diagnose-connectivity`.
3. Load fresh history for `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`.
4. Run `python main.py --readiness-check`.
5. Run `python main.py --reconcile-ledger`.
6. Only if readiness recommends `LIVE_BINANCE`, run `python main.py --live-paper-engine --run-minutes 60`.

## Operating Principle

Every important candle, provider decision, signal, rejection, context snapshot, simulated trade, portfolio update, benchmark result, walk-forward result and error must be persisted in SQLite so the full paper system can be audited later.
