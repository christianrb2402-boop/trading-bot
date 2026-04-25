# Multi-Agent Trading System

Capa fundacional minima para consumir OHLCV de Binance en modo lectura, guardarlo en SQLite y registrar todo con logging estructurado.

## Alcance del sprint

- Solo lectura de mercado.
- Binance como fuente publica de datos.
- Timeframe inicial: `1m`.
- Simbolos iniciales: `BTCUSDT` y `ETHUSDT`.
- Sin ordenes reales.
- Sin paper trading todavia.
- Sin dashboard ni LLMs.

## Estructura relevante

```text
config/settings.py
core/logger.py
core/database.py
data/binance_market_data.py
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
- `MARKET_TIMEFRAME`: timeframe a consumir.
- `BINANCE_KLINES_LIMIT`: numero de velas a pedir por simbolo.

Ejemplo de `.env`:

```env
APP_NAME=multiagent-trading-system
APP_ENV=development
LOG_LEVEL=INFO
SQLITE_PATH=runtime/market_data.db
LOGS_DIR=logs
BINANCE_BASE_URL=https://api.binance.com
BINANCE_TIMEOUT_SECONDS=10
MARKET_SYMBOLS=BTCUSDT,ETHUSDT
MARKET_TIMEFRAME=1m
BINANCE_KLINES_LIMIT=5
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
6. Registra inicio, fetch, inserciones, duplicados, errores y cierre limpio.

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
- `shutdown`
- `fatal_error`

## Validacion de duplicados

Si ejecutas el proceso dos veces, la restriccion unica evita insertar la misma vela otra vez. El sistema cuenta esos casos y los registra como `duplicate_ignored`.
