# Project State

## Current Project Goal

- Build a crypto market intelligence and paper-trading research system.
- Keep everything simulated, auditable and SQLite-backed.
- Do not enable real-money trading.
- Do not require private API keys.
- Use public Binance HTTP market data when reachable.
- Use `LOCAL_SQLITE` only as safe fallback or bounded validation mode.
- Reject trades that do not show a clear expected net edge after costs.
- Calibrate the multi-agent brain so it can reject bad trades cleanly and allow controlled paper exploration only when conditions are reasonable.

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
- `agents/net_profitability_gate.py`
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
- `execution/market_watch_engine.py`
- `execution/autonomous_paper_engine.py`
- `features/feature_store.py`
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
- `NetProfitabilityGate`
- `PerformanceLearningAgent`
- `ExecutionSimulatorAgent`
- `DecisionOrchestrator`
- `AuditAgent`
- `MarketStateAgent`
- `StrategySelectionAgent`
- `TrendFollowingAgent`
- `BreakoutAgent`
- `MeanReversionAgent`
- `MomentumScalpAgent`
- `PullbackContinuationAgent`
- `StrategyCriticAgent`
- `RiskManagerAgent`
- `MetaLearningAgent`
- `TradingBrainOrchestrator`

## Implemented Commands

- `python main.py --init-only`
- `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000`
- `python main.py --diagnose-connectivity`
- `python main.py --readiness-check`
- `python main.py --quick-audit`
- `python main.py --preflight-live-paper`
- `python main.py --reconcile-ledger`
- `python main.py --market-watch-engine --max-loops 5`
- `python main.py --market-watch-engine --run-minutes 5`
- `python main.py --autonomous-paper-engine --max-loops 5`
- `python main.py --autonomous-paper-engine --run-minutes 5`
- `python main.py --brain-report`
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
- quote `--timeframes` values, for example `--timeframes "1m,5m,15m,30m,1h,4h,1d"`

## Active Symbol Universe

- Core active:
  - `BTCUSDT`
  - `ETHUSDT`
  - `BNBUSDT`
  - `SOLUSDT`
  - `XRPUSDT`
- Watchlist prepared but disabled:
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
- `strategy_votes`
- `strategy_evaluations`
- `agent_performance`
- `brain_decisions`
- `risk_events`
- `feature_snapshots`
- `provider_status`
- `websocket_events`
- `data_quality_events`
- `gap_repair_events`

## What Is Working

- SQLite initialization and safe migrations.
- Real HTTP connectivity diagnosis against Binance endpoints.
- Controlled paper brain persistence with live `provider_used`, `paper_mode`, rejection diagnostics and market snapshots.
- `market-watch-engine` and `autonomous-paper-engine` now support `--max-loops`.
- Provider persistence no longer falls back to `UNKNOWN` immediately after bounded live brain runs.
- Historical backtest with no future leakage.
- Benchmark mode against multiple baselines.
- Walk-forward split with out-of-sample evaluation.
- Ledger reconciliation with explicit `OK/WARNING/FAIL`.
- Multi-timeframe market context storage.
- Duplicate setup rejection using `symbol/timeframe/direction/entry_time/setup_signature`.
- Gross and net trade accounting separated.
- Net profitability gate before paper entries.
- Quick audit and preflight gates before longer live-paper runs.
- JSON and CSV export reports.

## What Is Not Working

- The brain is still too conservative in live autonomous validation and opened `0` trades in the latest bounded run.
- `strategy_evaluations` remains empty because there are still no newly closed trades under the new brain calibration.
- The strategy still has no current net-positive evidence after costs.
- Benchmark and walk-forward parity is improved conceptually, but live brain and research still diverge because research is historical replay while live brain consumes fresh provider state and rejection outcomes.

## Current Data Source Status

### Latest validated live-brain environment

- `python main.py --diagnose-connectivity` returned `BINANCE_HTTP_USABLE: YES`
- latest bounded live runs persisted `provider=BINANCE`
- latest `status-report` showed:
  - `Current live provider: BINANCE`
  - `Last successful provider: BINANCE`
  - `Provider used in latest brain decision: BINANCE`
  - `Provider used in latest market snapshot: BINANCE`

### Research / audit caveat

- `brain-report` may still show `Connectivity status: BINANCE_HTTP_FAIL` if the report itself is executed in a context where the runtime probe cannot re-hit Binance live.
- This does not invalidate persisted live provider evidence already stored in SQLite.

## Current Runtime Reality

- `market-watch-engine --max-loops 5` passed with:
  - `Loops completed: 5`
  - `Observations recorded: 175`
- `autonomous-paper-engine --max-loops 5` passed with:
  - `Loops completed: 5`
  - `Decisions processed: 175`
  - `Trades opened: 0`
  - `Trades closed: 0`
- Fresh market snapshots exist for:
  - `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`
  - across `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`
- The brain currently ends up in `OBSERVE_ONLY` most of the time because cost, contradiction and hostile-state filters still dominate.

## Current Readiness Level

- Latest quick-audit:
  - `SAFE_TO_RUN_SHORT_PAPER: YES`
  - `SAFE_TO_RUN_LONG_PAPER: NO`
  - `PAPER_MODE: PAPER_EXPLORATION`
- Latest preflight:
  - `SAFE_TO_RUN_SHORT_PAPER: YES`
  - `SAFE_TO_RUN_LONG_PAPER: NO`
  - `PAPER_MODE: PAPER_EXPLORATION`
- Ledger status after final reconciliation:
  - `Ledger Consistency Check: OK`

## Latest Validation Snapshot

- `--init-only`: passed
- `--help`: passed
- `--diagnose-connectivity`: passed, result `BINANCE_HTTP_USABLE: YES`
- `--quick-audit`: passed
- `--preflight-live-paper`: passed, short paper allowed, long paper still blocked
- `--reconcile-ledger`: passed, result `OK`
- `--market-watch-engine --max-loops 5`: passed
- `--autonomous-paper-engine --max-loops 5`: passed
- `--brain-report`: passed
- `--status-report`: passed
- `--benchmark --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d"`: passed
- `--walk-forward --limit 10000 --train-pct 70 --timeframes "1m,5m,15m,30m,1h,4h,1d"`: passed
- `--export-report`: passed
- `--export-report --format csv`: passed

## Current Performance Reality

- The strategy cannot be considered profitable.
- With the latest strict cost-aware calibration:
  - `benchmark BOT_STRATEGY trades: 0`
  - `benchmark BOT_STRATEGY net_pnl: 0.0`
  - `benchmark BUY_AND_HOLD net_pnl: 32.180331`
- `walk-forward train trades: 0`
- `walk-forward test trades: 0`
- `missed_opportunities: 2`
- `good_avoidances: 0`
- This is not a success signal.
- It means the gate is now strict enough to reject almost all setups, and the next work item is calibration rather than more architecture.

## Known Limitations

- No real trading.
- No API keys.
- No private order execution.
- No dashboard.
- No paid data sources.
- No macro/news feeds yet.
- The brain remains too conservative and still opened zero exploratory or selective trades in the latest bounded autonomous run.
- `strategy_evaluations` still has no useful sample because there are no newly closed trades.
- Brain report can disagree with the last successful provider probe if the current runtime cannot re-probe Binance live at report time.
- The strategy still lacks net-positive validation after costs.

## Next Recommended Step

1. Keep the system paper-only.
2. Calibrate why the brain is collapsing back to `OBSERVE_ONLY` so often even when live provider and freshness are good.
3. Focus first on rejection concentration:
   - `rejected by cost`
   - `rejected by contradiction`
   - `rejected by insufficient data/paper mode`
4. Use `python main.py --market-watch-engine --max-loops 5` and `python main.py --brain-report` to inspect missed opportunities before relaxing entries.
5. Only after a bounded exploratory sample exists should `strategy_evaluations` and stronger meta-learning be expected to become useful.

## Operating Principle

Every important candle, provider decision, signal, rejection, context snapshot, simulated trade, portfolio update, benchmark result, walk-forward result and error must be persisted in SQLite so the full paper system can be audited later.
