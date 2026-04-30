# Multi-Agent Trading System

Base evolutiva de un sistema de inteligencia de trading para cripto: ingesta de mercado, analisis Delta, evaluacion historica, paper trading, motor continuo de analisis y live paper intelligence engine con ledger simulado.

Nota: [PROJECT_STATE.md](C:\Users\chris\OneDrive\Documentos\New%20project\PROJECT_STATE.md) es la fuente de verdad del estado actual y la arquitectura operativa del proyecto.
Resumen de auditoria operativo: [AUDIT_PACKET.md](C:\Users\chris\OneDrive\Documentos\New%20project\AUDIT_PACKET.md).
Runbook para la computadora fija Windows: [RUNBOOK_LOCAL_WINDOWS.md](C:\Users\chris\OneDrive\Documentos\New%20project\RUNBOOK_LOCAL_WINDOWS.md).

Estado actual de investigacion:
- Senales Delta por tiers: `STRONG`, `MEDIUM`, `WEAK`, `REJECTED`.
- Backtest multi-timeframe sin fuga de datos.
- Control de calidad de velas antes del procesamiento.
- Persistencia de senales rechazadas, decisiones, contexto, errores y trades simulados.
- Live paper engine con comite multiagente, ledger de portfolio y costos netos simulados.

## Alcance actual

- Solo lectura de mercado.
- Binance como fuente publica de datos.
- Timeframes de investigacion: `1m`, `5m`, `15m`.
- Universo actual configurado: `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`.
- Sin ordenes reales.
- Paper trading y simulacion solamente.
- Sin dashboard ni LLMs.
- Sin trading real ni API keys privadas.

## Estructura relevante

```text
config/settings.py
core/logger.py
core/database.py
data/binance_market_data.py
agents/delta_agent.py
analytics/backtest_engine.py
analytics/performance_analyzer.py
data/market_data_provider.py
execution/simulated_trade_tracker.py
execution/live_paper_engine.py
agents/market_context_agent.py
main.py
.env.example
README.md
```

## Requisitos

- Python 3.11+

## Configuracion

1. Crea o activa tu entorno virtual.
2. Copia `.env.example` a `.env`.
3. Ajusta valores si lo necesitas.

Variables principales:

- `SQLITE_PATH`: ruta del archivo SQLite.
- `LOGS_DIR`: carpeta de logs.
- `MARKET_SYMBOLS`: lista separada por comas.
- `MARKET_TIMEFRAMES`: lista de timeframes para backtest, separada por comas.
- `MARKET_TIMEFRAME`: timeframe a consumir.
- `BINANCE_KLINES_LIMIT`: numero de velas a pedir por simbolo.
- `BINANCE_MAX_RETRIES`: reintentos ante errores de red/API.
- `CONTINUOUS_LOOP_SECONDS`: frecuencia del motor continuo.
- `BACKTEST_MIN_TRADES`: objetivo minimo de trades cerrados en backtest.
- `DELTA_WEAK_THRESHOLD_FACTOR`: factor para senales `WEAK`.
- `DELTA_STRONG_THRESHOLD_FACTOR`: factor para senales `STRONG`.
- `SIMULATED_TRADE_EXIT_CANDLES`: salida simulada despues de N velas.
- `SIMULATED_INITIAL_CAPITAL`: capital base para simulacion.
- `SIMULATED_POSITION_SIZE_USD`: tamano nominal por trade simulado.
- `SIMULATED_FEE_PCT`: fee asumido por lado.
- `SIMULATED_SLIPPAGE_PCT`: slippage asumido por ejecucion.
- `SIMULATED_STOP_LOSS_PCT`: stop loss porcentual.
- `SIMULATED_TAKE_PROFIT_PCT`: take profit porcentual.
- `SIMULATED_MAX_HOLD_CANDLES`: maximo de velas para expirar un trade.
- `SIMULATED_SPREAD_PCT`: spread estimado por trade.
- `MAX_POSITION_PCT_OF_CAPITAL`: exposicion maxima por posicion.
- `MAX_OPEN_POSITIONS`: numero maximo de posiciones abiertas.
- `MIN_REWARD_RISK_RATIO`: reward/risk minimo aceptable.
- `AGGRESSIVENESS_LEVEL`: `CONSERVATIVE`, `BALANCED` o `AGGRESSIVE`.

Ejemplo de `.env`:

```env
APP_NAME=multiagent-trading-system
APP_ENV=development
LOG_LEVEL=INFO
SQLITE_PATH=runtime/market_data.db
LOGS_DIR=logs
BINANCE_BASE_URL=https://api.binance.com
BINANCE_TIMEOUT_SECONDS=10
MARKET_SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT
MARKET_TIMEFRAMES=1m,5m,15m
MARKET_TIMEFRAME=1m
BINANCE_KLINES_LIMIT=5000
BACKTEST_MIN_TRADES=100
DELTA_WEAK_THRESHOLD_FACTOR=0.1
DELTA_STRONG_THRESHOLD_FACTOR=2.0
```

Nota: si trabajas dentro de una carpeta sincronizada y SQLite da problemas, cambia `SQLITE_PATH` a una ruta local estable fuera de esa carpeta.

## Ejecucion

Inicializar solo la base:

```bash
python main.py --init-only
```

Consumir y guardar velas:

```bash
python main.py
```

Cargar historico sin ejecutar agentes:

```bash
python main.py --load-history --limit 1000
```

Ejecutar solo el Agente Delta con datos ya guardados en SQLite:

```bash
python main.py --delta-only
```

Validar el Agente Delta sobre ventanas historicas usando solo SQLite:

```bash
python main.py --delta-test
```

Evaluar que pasa despues de cada senal Delta:

```bash
python main.py --evaluate-signals
```

Evaluar si la ventaja esta en LONG o en SHORT:

```bash
python main.py --evaluate-direction
```

Optimizar thresholds para Delta LONG-only:

```bash
python main.py --optimize-threshold
```

Ejecutar paper trading LONG-only con datos reales de Binance:

```bash
python main.py --paper-trade
```

Ejecutar el motor continuo de analisis de mercado:

```bash
python main.py --continuous-engine
```

Ejecutar el live paper trading intelligence engine:

```bash
python main.py --live-paper-engine
```

Diagnosticar conectividad HTTP real hacia Binance:

```bash
python main.py --diagnose-connectivity
```

Evaluar si el entorno actual esta listo para live paper largo:

```bash
python main.py --readiness-check
```

Prueba acotada del live paper engine:

```bash
python main.py --live-paper-engine --max-loops 5
```

Ejecucion por tiempo del live paper engine:

```bash
python main.py --live-paper-engine --run-minutes 60
```

Ejecutar backtest historico candle by candle sin fuga de datos:

```bash
python main.py --backtest --limit 2000
```

Ejecutar backtest multi-timeframe con objetivo minimo de trades:

```bash
python main.py --backtest --limit 5000 --timeframes 1m,5m,15m --min-trades 100
```

Ver reporte humano del estado persistido:

```bash
python main.py --status-report
```

Exportar un reporte auditable en JSON:

```bash
python main.py --export-report
```

Ejecutar una cantidad acotada de iteraciones para pruebas:

```bash
python main.py --continuous-engine --max-loops 1
```

Ejecutar un numero acotado de ciclos para pruebas:

```bash
python main.py --paper-trade --paper-cycles 1
```

Horizontes personalizados:

```bash
python main.py --evaluate-signals --evaluation-windows 5 10 15
```

Probar ventanas especificas:

```bash
python main.py --delta-test --delta-windows 10 20 50
```

Sobrescribir parametros por CLI:

```bash
python main.py --symbols BTCUSDT ETHUSDT --timeframe 1m --limit 10
```

## Que hace `main.py`

1. Carga configuracion centralizada.
2. Inicializa logging JSON en consola y archivo.
3. Crea la base SQLite y la tabla `candles`.
4. Consulta OHLCV desde Binance.
5. Inserta velas evitando duplicados por `UNIQUE(symbol, timeframe, open_time)`.
6. Calcula senales Delta estructuradas.
7. Registra senales, decisiones, rechazos, snapshots y trades simulados en SQLite.
8. Detecta gaps, duplicados y velas corruptas antes del procesamiento historico.
9. Ejecuta backtests historicos candle by candle reutilizando contexto, decisiones y aprendizaje.
10. Ejecuta un comite multiagente en modo live paper para evaluar contexto, riesgo/reward, costos, ejecucion simulada y aprendizaje.
11. Mantiene un ledger de portfolio simulado con equity, cash, exposicion y costos acumulados.
12. Registra inicio, fetch, inserciones, duplicados, rechazos, errores y cierre limpio.

## Esquema SQLite

Tabla `candles`:

- `id`
- `symbol`
- `timeframe`
- `open_time`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `close_time`
- `created_at`

Restriccion unica:

- `(symbol, timeframe, open_time)`

Tabla `signals_log`:

- `id`
- `symbol`
- `timeframe`
- `signal`
- `signal_tier`
- `k_value`
- `confidence`
- `timestamp`

Tabla `rejected_signals_log`:

- `id`
- `symbol`
- `timeframe`
- `signal_tier`
- `reason`
- `context_payload`
- `thresholds_failed`
- `timestamp`
- `created_at`

Tabla `agent_decisions`:

- `id`
- `timestamp`
- `agent_name`
- `symbol`
- `timeframe`
- `decision`
- `confidence`
- `inputs_used`
- `reasoning_summary`
- `linked_signal_id`
- `linked_trade_id`
- `created_at`

Tabla `simulated_trades`:

- `id`
- `symbol`
- `direction`
- `timeframe`
- `status`
- `entry_time`
- `entry_price`
- `exit_time`
- `exit_price`
- `stop_loss`
- `take_profit`
- `pnl`
- `pnl_pct`
- `fee_pct`
- `fees_paid`
- `slippage_pct`
- `signal_id`
- `reason_entry`
- `reason_exit`
- `created_at`
- `updated_at`

Tabla `error_events`:

- `id`
- `timestamp`
- `component`
- `symbol`
- `error_type`
- `error_message`
- `recoverable`
- `created_at`

Tabla `market_context`:

- `id`
- `timestamp`
- `source`
- `macro_regime`
- `risk_regime`
- `context_score`
- `reason`
- `raw_payload`
- `created_at`

## Logs

Los logs se escriben en consola y en `logs/system.log` con formato JSON.

Eventos principales:

- `startup`
- `database_initialized`
- `fetch_start`
- `fetch_success`
- `history_fetch_start`
- `history_fetch_batch`
- `history_fetch_success`
- `insert_summary`
- `history_load_summary`
- `duplicate_ignored`
- `signal_evaluation_summary`
- `direction_evaluation_summary`
- `threshold_optimization_summary`
- `paper_trade_start`
- `paper_trade_cycle`
- `paper_trade_open`
- `paper_trade_close`
- `signal`
- `trade_simulation_open`
- `trade_simulation_close`
- `trade_simulation_rejected`
- `market_context`
- `data_quality`
- `data_quality_anomaly`
- `continuous_cycle_start`
- `continuous_cycle_error`
- `continuous_symbol_error`
- `shutdown`
- `fatal_error`

## Validacion de duplicados

Si ejecutas el proceso dos veces, la restriccion unica evita insertar la misma vela otra vez. El sistema cuenta esos casos y los registra como `duplicate_ignored`.
