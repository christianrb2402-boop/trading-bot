# Multi-Agent Trading System

Sistema de investigacion para cripto en modo 100% paper trading. El proyecto consume datos publicos, analiza contexto multi-timeframe, genera decisiones multiagente, simula trades con costos y persiste todo en SQLite para auditoria.

Estado de referencia:
- Arquitectura y estado operativo: [PROJECT_STATE.md](C:\Users\chris\OneDrive\Documentos\New%20project\PROJECT_STATE.md)
- Resumen de auditoria: [AUDIT_PACKET.md](C:\Users\chris\OneDrive\Documentos\New%20project\AUDIT_PACKET.md)
- Runbook Windows: [RUNBOOK_LOCAL_WINDOWS.md](C:\Users\chris\OneDrive\Documentos\New%20project\RUNBOOK_LOCAL_WINDOWS.md)

## Alcance actual

- Paper trading solamente.
- Sin trading real.
- Sin API keys privadas.
- Sin ordenes reales.
- Sin servicios pagos.
- Binance publico como fuente primaria cuando HTTP responde.
- `LOCAL_SQLITE` como fallback de emergencia o validacion acotada.

## Timeframes soportados

- Mercado general: `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`
- Ejecucion paper: `1m`, `5m`, `15m`
- Contexto: `30m`, `1h`, `4h`, `1d`
- Estructural preparado: `1w`, `1M`

Nota para PowerShell en Windows:
- Cuando uses `--timeframes`, pasa el valor entre comillas.
- Ejemplo correcto: `python main.py --backtest --timeframes "1m,5m,15m,30m,1h,4h,1d" --limit 5000`
- Sin comillas, PowerShell puede interpretar `1d` de forma inesperada.

## Universo actual

- Core activo: `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`
- Watchlist preparada pero apagada por defecto:
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
- [agents/decision_orchestrator.py](C:\Users\chris\OneDrive\Documentos\New%20project\agents\decision_orchestrator.py)
- [analytics/backtest_engine.py](C:\Users\chris\OneDrive\Documentos\New%20project\analytics\backtest_engine.py)
- [analytics/benchmark_engine.py](C:\Users\chris\OneDrive\Documentos\New%20project\analytics\benchmark_engine.py)
- [analytics/walk_forward_engine.py](C:\Users\chris\OneDrive\Documentos\New%20project\analytics\walk_forward_engine.py)
- [execution/live_paper_engine.py](C:\Users\chris\OneDrive\Documentos\New%20project\execution\live_paper_engine.py)
- [execution/simulated_trade_tracker.py](C:\Users\chris\OneDrive\Documentos\New%20project\execution\simulated_trade_tracker.py)

## Configuracion

1. Crear o activar entorno virtual.
2. Copiar `.env.example` a `.env`.
3. Ajustar si hace falta.

Variables claves:
- `CORE_SYMBOLS`
- `WATCHLIST_SYMBOLS`
- `ENABLE_WATCHLIST`
- `MARKET_TIMEFRAMES`
- `EXECUTION_TIMEFRAMES`
- `CONTEXT_TIMEFRAMES`
- `STRUCTURAL_TIMEFRAMES`
- `MIN_NET_REWARD_RISK_RATIO`
- `MIN_EXPECTED_NET_EDGE_PCT`
- `MAX_COST_DRAG_PCT`
- `SIMULATED_MAKER_FEE_PCT`
- `SIMULATED_TAKER_FEE_PCT`
- `SIMULATED_SLIPPAGE_PCT`
- `SIMULATED_SPREAD_PCT`
- `AGGRESSIVENESS_LEVEL`

## Comandos principales

Inicializar SQLite:

```bash
python main.py --init-only
```

Diagnosticar Binance por HTTP real:

```bash
python main.py --diagnose-connectivity
```

Ver si el entorno actual esta listo para live paper:

```bash
python main.py --readiness-check
```

Reconciliar ledger y exposicion:

```bash
python main.py --reconcile-ledger
```

Cargar historia desde Binance:

```bash
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000
```

Backtest historico multi-timeframe:

```bash
python main.py --backtest --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d" --min-trades 100
```

Benchmark contra baselines:

```bash
python main.py --benchmark --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d"
```

Walk-forward:

```bash
python main.py --walk-forward --limit 10000 --train-pct 70 --timeframes "1m,5m,15m,30m,1h,4h,1d"
```

Live paper engine acotado:

```bash
python main.py --live-paper-engine --max-loops 5
```

Live paper largo:

```bash
python main.py --live-paper-engine --run-minutes 60
```

Estado operativo:

```bash
python main.py --status-report
```

Exportar reporte JSON:

```bash
python main.py --export-report
```

Exportar CSVs:

```bash
python main.py --export-report --format csv
```

## Que hace el sistema hoy

1. Consume o materializa velas multi-timeframe.
2. Detecta gaps, duplicados y velas corruptas.
3. Calcula contexto de mercado y clasifica regimen.
4. Genera senales Delta por tier: `STRONG`, `MEDIUM`, `WEAK`, `REJECTED`.
5. Evalua seleccion de simbolo, riesgo/recompensa y costos netos.
6. Usa un comite con orquestacion de decision.
7. Simula trades y costos en un ledger paper.
8. Reconcili­a cash, equity, exposicion y posiciones.
9. Aprende de resultados historicos y guarda insights.
10. Exporta reportes auditables.

## Estado real actual

- El sistema sigue siendo seguro para simulacion.
- En este entorno de trabajo actual Binance sigue fallando por HTTP con `WinError 10061`.
- Por eso aqui el proveedor actual recomendado es `LOCAL_SQLITE`.
- La data local esta incompleta y stale para varios timeframes y simbolos.
- La estrategia sigue perdiendo despues de fees, slippage y spread.

No se debe declarar rentable mientras el `net pnl` siga siendo negativo.

## Validacion de duplicados y ledger

- `candles` evita duplicados por `UNIQUE(symbol, timeframe, open_time)`.
- `simulated_trades` rechaza setups duplicados por `symbol`, `timeframe`, `direction`, `entry_time` y `setup_signature`.
- `--reconcile-ledger` revisa:
  - posiciones huerfanas
  - duplicados
  - exposure
  - available cash
  - realized pnl
  - unrealized pnl
  - equity

Si `Ledger Consistency Check` sale distinto de `OK`, no se debe dejar corriendo el motor live paper por tiempo largo.
