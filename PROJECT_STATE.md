# Project State

## Current Project Goal

- Build a crypto market intelligence and paper-trading research system.
- Keep everything simulated, auditable and SQLite-backed.
- Do not enable real-money trading.
- Do not require private API keys.
- Use public Binance HTTP market data when reachable.
- Use `LOCAL_SQLITE` only as safe fallback or bounded validation mode.
- Reject trades that do not show a clear expected net edge after costs.

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

## Implemented Commands

- `python main.py --init-only`
- `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000`
- `python main.py --diagnose-connectivity`
- `python main.py --readiness-check`
- `python main.py --quick-audit`
- `python main.py --preflight-live-paper`
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

## What Is Working

- SQLite initialization and safe migrations.
- Real HTTP connectivity diagnosis against Binance endpoints.
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

- Fresh Binance HTTP access is still failing in the current Codex environment.
- `--load-history` cannot fetch fresh candles from Binance in this environment.
- Local data here is stale and contains severe gaps.
- `BNBUSDT`, `SOLUSDT` and `XRPUSDT` have no local history here.
- The strategy has no current net-positive evidence after costs.

## Current Data Source Status

### Fixed Windows target machine

- Operator validation confirms Binance HTTP responds there.
- That machine is the intended live-paper runtime target.

### Current Codex environment

- Latest validated status:
  - `BINANCE_HTTP_USABLE: NO`
  - errors: `WinError 10061`
- Current provider for bounded validation:
  - `LOCAL_SQLITE`

## Current Runtime Reality

- Backtest, benchmark and walk-forward are running from local historical replay.
- Bounded `--live-paper-engine --max-loops 5` is running safely in fallback mode here.
- Current local candles for BTCUSDT and ETHUSDT are about `51h32m` old in the latest status snapshot.
- Higher timeframes are materialized only for BTCUSDT and ETHUSDT here.
- `BNBUSDT`, `SOLUSDT` and `XRPUSDT` are missing local history across configured timeframes.

## Current Readiness Level

- In the current Codex environment:
  - `READY_FOR_LIVE_PAPER: NO`
  - `SAFE_TO_RUN_SHORT_PAPER: NO`
  - `SAFE_TO_RUN_LONG_PAPER: NO`
  - recommended mode: `DO_NOT_RUN_LONG`
- Ledger status after final reconciliation:
  - `Ledger Consistency Check: OK`

## Latest Validation Snapshot

- `--init-only`: passed
- `--quick-audit`: passed
- `--preflight-live-paper`: blocked correctly, returned unsafe
- `--diagnose-connectivity`: passed as command, result `BINANCE_HTTP_USABLE: NO`
- `--reconcile-ledger`: passed, result `OK`
- `--status-report`: passed
- `--load-history` in this environment: still fails with `WinError 10061`
- `--benchmark --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d"`: passed
- `--walk-forward --limit 10000 --train-pct 70 --timeframes "1m,5m,15m,30m,1h,4h,1d"`: passed
- `--live-paper-engine --max-loops 5`: passed in bounded fallback mode
- `--export-report`: passed
- `--export-report --format csv`: passed

## Current Performance Reality

- The strategy cannot be considered profitable.
- With the latest strict cost-aware gate on this local stale dataset:
  - `benchmark BOT_STRATEGY trades: 0`
  - `benchmark BOT_STRATEGY net_pnl: 0.0`
  - `walk-forward train trades: 0`
  - `walk-forward test trades: 0`
- This is not a success signal.
- It means the gate is now strict enough to refuse low-quality setups under bad data conditions.

## Known Limitations

- No real trading.
- No API keys.
- No private order execution.
- No dashboard.
- No paid data sources.
- No macro/news feeds yet.
- Local history here is incomplete and stale.
- Current historical sample is too weak to justify a long run here.
- The strategy still lacks net-positive validation after costs on the current dataset.

## Next Recommended Step

1. Move to the fixed Windows machine without VPN.
2. Run `python main.py --diagnose-connectivity`.
3. Run `python main.py --quick-audit`.
4. Run `python main.py --preflight-live-paper`.
5. Load fresh history for `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`.
6. Run `python main.py --readiness-check`.
7. Run `python main.py --reconcile-ledger`.
8. Only if preflight and readiness both approve, run `python main.py --live-paper-engine --run-minutes 60`.

## Operating Principle

Every important candle, provider decision, signal, rejection, context snapshot, simulated trade, portfolio update, benchmark result, walk-forward result and error must be persisted in SQLite so the full paper system can be audited later.
