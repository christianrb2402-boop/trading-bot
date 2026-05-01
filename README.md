# Multi-Agent Trading System

Sistema de investigacion cripto en modo 100% paper trading. Consume datos publicos, genera contexto multi-timeframe, decide con varios agentes, filtra por costos netos y persiste todo en SQLite para auditoria.

Estado de referencia:
- Arquitectura y estado operativo: [PROJECT_STATE.md](C:\Users\chris\OneDrive\Documentos\New%20project\PROJECT_STATE.md)
- Resumen de auditoria: [AUDIT_PACKET.md](C:\Users\chris\OneDrive\Documentos\New%20project\AUDIT_PACKET.md)
- Runbook Windows: [RUNBOOK_LOCAL_WINDOWS.md](C:\Users\chris\OneDrive\Documentos\New%20project\RUNBOOK_LOCAL_WINDOWS.md)

## Alcance actual

- Paper trading solamente
- Sin trading real
- Sin API keys privadas
- Sin ordenes reales
- Sin servicios pagos
- Binance publico como fuente primaria cuando HTTP responde
- `LOCAL_SQLITE` como fallback seguro y auditable

## Timeframes soportados

- Mercado: `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`
- Ejecucion: `1m`, `5m`, `15m`
- Contexto: `30m`, `1h`, `4h`, `1d`
- Estructural preparado: `1w`, `1M`

Nota para PowerShell:
- usar `--timeframes "1m,5m,15m,30m,1h,4h,1d"`

## Universo actual

- Core: `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`
- Watchlist preparada pero desactivada:
  `DOGEUSDT`, `ADAUSDT`, `AVAXUSDT`, `LINKUSDT`, `LTCUSDT`, `DOTUSDT`, `MATICUSDT`, `TRXUSDT`, `BCHUSDT`, `NEARUSDT`, `ARBUSDT`, `OPUSDT`

## Modulos principales

- [main.py](C:\Users\chris\OneDrive\Documentos\New%20project\main.py)
- [config/settings.py](C:\Users\chris\OneDrive\Documentos\New%20project\config\settings.py)
- [core/database.py](C:\Users\chris\OneDrive\Documentos\New%20project\core\database.py)
- [core/runtime_checks.py](C:\Users\chris\OneDrive\Documentos\New%20project\core\runtime_checks.py)
- [core/ledger_reconciler.py](C:\Users\chris\OneDrive\Documentos\New%20project\core\ledger_reconciler.py)
- [data/binance_market_data.py](C:\Users\chris\OneDrive\Documentos\New%20project\data\binance_market_data.py)
- [data/market_data_provider.py](C:\Users\chris\OneDrive\Documentos\New%20project\data\market_data_provider.py)
- [agents/delta_agent.py](C:\Users\chris\OneDrive\Documentos\New%20project\agents\delta_agent.py)
- [agents/market_context_agent.py](C:\Users\chris\OneDrive\Documentos\New%20project\agents\market_context_agent.py)
- [agents/symbol_selection_agent.py](C:\Users\chris\OneDrive\Documentos\New%20project\agents\symbol_selection_agent.py)
- [agents/risk_reward_agent.py](C:\Users\chris\OneDrive\Documentos\New%20project\agents\risk_reward_agent.py)
- [agents/cost_model_agent.py](C:\Users\chris\OneDrive\Documentos\New%20project\agents\cost_model_agent.py)
- [agents/net_profitability_gate.py](C:\Users\chris\OneDrive\Documentos\New%20project\agents\net_profitability_gate.py)
- [agents/decision_orchestrator.py](C:\Users\chris\OneDrive\Documentos\New%20project\agents\decision_orchestrator.py)
- [analytics/backtest_engine.py](C:\Users\chris\OneDrive\Documentos\New%20project\analytics\backtest_engine.py)
- [analytics/benchmark_engine.py](C:\Users\chris\OneDrive\Documentos\New%20project\analytics\benchmark_engine.py)
- [analytics/walk_forward_engine.py](C:\Users\chris\OneDrive\Documentos\New%20project\analytics\walk_forward_engine.py)
- [execution/live_paper_engine.py](C:\Users\chris\OneDrive\Documentos\New%20project\execution\live_paper_engine.py)
- [execution/simulated_trade_tracker.py](C:\Users\chris\OneDrive\Documentos\New%20project\execution\simulated_trade_tracker.py)

## Variables clave

- `MIN_NET_REWARD_RISK_RATIO`
- `MIN_EXPECTED_NET_EDGE_PCT`
- `MIN_COST_COVERAGE_MULTIPLE`
- `MAX_COST_DRAG_PCT`
- `SIMULATED_MAKER_FEE_PCT`
- `SIMULATED_TAKER_FEE_PCT`
- `SIMULATED_SLIPPAGE_PCT`
- `SIMULATED_SPREAD_PCT`
- `MARKET_TIMEFRAMES`
- `EXECUTION_TIMEFRAMES`
- `CONTEXT_TIMEFRAMES`
- `STRUCTURAL_TIMEFRAMES`
- `AGGRESSIVENESS_LEVEL`

## Comandos principales

```bash
python main.py --init-only
python main.py --diagnose-connectivity
python main.py --readiness-check
python main.py --quick-audit
python main.py --preflight-live-paper
python main.py --reconcile-ledger
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000
python main.py --backtest --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d" --min-trades 100
python main.py --benchmark --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d"
python main.py --walk-forward --limit 10000 --train-pct 70 --timeframes "1m,5m,15m,30m,1h,4h,1d"
python main.py --live-paper-engine --max-loops 5
python main.py --live-paper-engine --run-minutes 60
python main.py --status-report
python main.py --export-report
python main.py --export-report --format csv
```

## Que hace el sistema hoy

1. Consume o materializa velas multi-timeframe.
2. Detecta gaps, duplicados y velas corruptas.
3. Calcula contexto de mercado y regimen.
4. Genera decisiones Delta por tier.
5. Filtra por seleccion de simbolo, riesgo/recompensa y costos.
6. Aplica `NetProfitabilityGate` antes de abrir cualquier paper trade.
7. Usa un comite multiagente para aprobar o rechazar.
8. Simula trades y costos en un ledger paper.
9. Reconcili­a cash, equity, exposicion y posiciones.
10. Exporta reportes JSON y CSV auditables.

## Estado real actual

- El sistema sigue siendo seguro para simulacion.
- En este entorno actual Binance falla por HTTP con `WinError 10061`.
- Aqui el proveedor actual es `LOCAL_SQLITE`.
- La data local esta stale y con gaps severos en varios timeframes.
- `BNBUSDT`, `SOLUSDT` y `XRPUSDT` no tienen historia local util aqui.
- El ledger final queda `OK` despues de `--reconcile-ledger`.
- El filtro neto nuevo esta bloqueando trades cuya expectativa no cubre claramente los costos.
- Con el snapshot final local, el sistema termina en `NO_TRADE` casi total, lo cual es correcto dadas estas condiciones.

No se debe declarar rentable mientras el `final net pnl after all costs` siga sin evidencia positiva.

## Politica operativa

- No correr largo si `--preflight-live-paper` devuelve `SAFE_TO_RUN_LONG_PAPER: NO`.
- No abrir paper trades si el edge neto esperado no cubre costos.
- No mezclar gross profit con net profit.
- No permitir ledger inconsistente antes de una corrida larga.

## Recomendacion para manana en la PC fija

```bash
python main.py --quick-audit
python main.py --preflight-live-paper
python main.py --live-paper-engine --run-minutes 60
```

Solo correr la ultima linea si las dos primeras dejan claro:
- Binance reachable: `YES`
- Fresh data available: `YES`
- Ledger result: `OK`
- `SAFE_TO_RUN_LONG_PAPER: YES`
