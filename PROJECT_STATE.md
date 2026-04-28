# Project State

## Current Project Goal

- Build a crypto market intelligence and paper-trading system.
- No real-money trading yet.
- Use public Binance market data only for now.
- Prioritize free/open data sources.

## Current Implemented Modules

- `main.py`
- `config/settings.py`
- `core/database.py`
- `data/binance_market_data.py`
- `agents/delta_agent.py`
- `execution/simulated_trade_tracker.py`
- `README.md`

## Current Implemented Features

- Binance public OHLCV fetching.
- SQLite persistence.
- Candles table with duplicate protection.
- Delta Agent with structured signal output.
- Continuous engine command:
  `python main.py --continuous-engine`
- Bounded test command:
  `python main.py --continuous-engine --max-loops 1`
- Basic signal logging.
- Basic simulated trade tracking.
- JSON logs.

## Current SQLite Tables

- `candles`
- `signals_log`
- `simulated_trades`

## Known Limitations

- No real trading.
- No API keys.
- No dashboard.
- No macro/context agent yet.
- No full audit/report command yet.
- Simulated trade memory still needs stronger fields.
- Need better status reporting.
- Need `error_events` table.
- Need `agent_decisions` table.
- Need `market_context` table and `MarketContextAgent` skeleton.

## Near-Term Roadmap

1. Step 1: strengthen memory and audit tables.
2. Step 2: add `--status-report`.
3. Step 3: improve simulated trade lifecycle.
4. Step 4: add `error_events`.
5. Step 5: add `MarketContextAgent` skeleton.
6. Step 6: test with `--continuous-engine --max-loops 3`.
7. Step 7: run for several hours collecting real Binance data.
8. Step 8: later move to cloud 24/7.
9. Step 9: only much later connect real-money trading.

## Operating Principle

Every important decision, signal, simulated trade, error and market context must be persisted in SQLite so the system can be audited later.
