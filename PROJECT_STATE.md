# Project State

## Current Project Goal

- Build a crypto market intelligence and live paper-trading research system.
- Keep everything simulated, auditable and SQLite-backed.
- Do not enable real-money trading.
- Do not require private API keys.
- Use public Binance HTTP market data when reachable.
- Fall back to local SQLite only as an emergency or bounded validation path.

## Implemented Modules

- `main.py`
- `config/settings.py`
- `core/database.py`
- `core/logger.py`
- `core/runtime_checks.py`
- `data/binance_market_data.py`
- `data/market_data_provider.py`
- `agents/delta_agent.py`
- `agents/market_data_agent.py`
- `agents/market_context_agent.py`
- `agents/risk_reward_agent.py`
- `agents/cost_model_agent.py`
- `agents/performance_learning_agent.py`
- `agents/execution_simulator_agent.py`
- `agents/decision_orchestrator.py`
- `agents/audit_agent.py`
- `analytics/backtest_engine.py`
- `analytics/performance_analyzer.py`
- `execution/simulated_trade_tracker.py`
- `execution/live_paper_engine.py`
- `RUNBOOK_LOCAL_WINDOWS.md`

## Implemented Agents

- `MarketDataAgent`
- `MarketContextAgent`
- `DeltaAgent`
- `RiskRewardAgent`
- `CostModelAgent`
- `PerformanceLearningAgent`
- `ExecutionSimulatorAgent`
- `DecisionOrchestrator`
- `AuditAgent`

## Implemented Commands

- `python main.py --init-only`
- `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000`
- `python main.py --delta-only`
- `python main.py --delta-test`
- `python main.py --evaluate-signals`
- `python main.py --evaluate-direction`
- `python main.py --optimize-threshold`
- `python main.py --paper-trade`
- `python main.py --continuous-engine`
- `python main.py --backtest --limit 5000 --timeframes 1m,5m,15m --min-trades 100`
- `python main.py --diagnose-connectivity`
- `python main.py --readiness-check`
- `python main.py --live-paper-engine`
- `python main.py --live-paper-engine --max-loops 5`
- `python main.py --live-paper-engine --run-minutes 60`
- `python main.py --live-paper-engine --allow-stale-fallback`
- `python main.py --status-report`
- `python main.py --export-report`

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

## What Is Working

- SQLite initialization and safe schema migration.
- Historical backtest with no future leakage.
- Cost-aware simulated trades with gross and net PnL.
- Connectivity diagnosis based on real HTTP requests, not `nslookup`.
- Readiness evaluation for long live-paper execution.
- Safe bounded live-paper execution with fallback logic.
- Structured status report with provider, freshness, stale age, counters, fees, spread and recent errors.
- JSON export report.
- Windows runbook and `.bat` launchers for local operation.

## What Is Not Working

- Fresh Binance HTTP access is still failing in the current Codex environment.
- `--load-history` cannot fetch fresh candles from Binance in the current Codex environment.
- Current local data is stale and gap-prone.
- `BNBUSDT`, `SOLUSDT` and `XRPUSDT` still have no local history in SQLite here.
- Strategy performance remains negative after costs.

## Data Source Status

### Fixed Windows target machine

- External validation provided by the operator confirms:
  - `https://api.binance.com/api/v3/time` responds correctly
  - `https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=5` responds correctly
- Interpretation:
  - Binance is usable on the fixed machine
  - `nslookup` failure alone must not be treated as a fatal Binance blockage

### Current Codex environment

- Latest validated status:
  - `--diagnose-connectivity` returned `BINANCE_HTTP_FAIL`
  - HTTP calls failed with `WinError 10061`
- Interpretation:
  - This environment is not currently suitable for fresh Binance ingestion
  - Bounded validation uses `LOCAL_SQLITE` fallback

## Current Runtime Reality

- Backtest mode is using historical replay from SQLite.
- Current live-paper bounded validation is using `LOCAL_SQLITE`.
- Current latest market snapshots are `stale=True`.
- Current latest market snapshots are `valid=False`.
- Fallback is safe and auditable, but not suitable for long fresh live-paper execution.

## Current Readiness Level

- In the current Codex environment:
  - `READY_FOR_LIVE_PAPER: NO`
  - recommended mode: `DO_NOT_RUN_LONG`
- On the fixed Windows machine:
  - expected next step is to run `--diagnose-connectivity`, `--load-history`, then `--readiness-check`
  - readiness is not assumed until those commands pass on that machine

## Known Limitations

- No real trading.
- No API keys.
- No private order execution.
- No dashboard.
- No paid data sources.
- No external macro/news feeds yet.
- Only `BTCUSDT` and `ETHUSDT` have local history here.
- Current local history contains gaps and is stale.
- The strategy is losing after fees, slippage and spread.
- Long unattended live paper should not be started in the current Codex environment.

## Latest Validation Snapshot

- `--diagnose-connectivity`: passed as a command, result `BINANCE_HTTP_USABLE: NO` in this environment
- `--init-only`: passed
- `--load-history --symbols BTCUSDT ETHUSDT --timeframe 1m --limit 100`: partial/failing due Binance HTTP refusal in this environment
- `--readiness-check`: passed as a command, result `READY_FOR_LIVE_PAPER: NO`
- `--live-paper-engine --max-loops 5`: passed in bounded fallback mode
- `--status-report`: passed
- `--export-report`: passed

## Next Recommended Step

1. Move to the fixed Windows machine without VPN.
2. Run `python main.py --diagnose-connectivity`.
3. If HTTP is OK, run `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000`.
4. Run `python main.py --readiness-check`.
5. Only if readiness recommends `LIVE_BINANCE`, run `python main.py --live-paper-engine --run-minutes 60`.

## Operating Principle

Every important candle, provider decision, signal, rejection, context snapshot, simulated trade, portfolio update and error must be persisted in SQLite so the full paper system can be audited later.
