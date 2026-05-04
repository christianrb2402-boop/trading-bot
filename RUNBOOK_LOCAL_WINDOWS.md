# Runbook Local Windows

Este runbook asume una computadora fija Windows, sin VPN, con conectividad HTTP real hacia Binance. Todo sigue en modo paper trading.

## 1. Actualizar repo

```bat
git pull
```

## 2. Crear y activar entorno virtual

```bat
python -m venv venv
venv\Scripts\activate
```

## 3. Instalar el proyecto

```bat
pip install .
```

## 4. Diagnostico HTTP real hacia Binance

```bat
python main.py --diagnose-connectivity
```

Interpretacion:
- Si `BINANCE_HTTP_USABLE: YES`, Binance es usable aunque `nslookup` falle.
- Si `BINANCE_HTTP_USABLE: NO`, no correr live paper largo todavia.

## 5. Inicializar SQLite

```bat
python main.py --init-only
```

## 6. Cargar historia fresca

```bat
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 5m --limit 1000
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 15m --limit 1000
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 30m --limit 1000
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1h --limit 1000
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 4h --limit 1000
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1d --limit 1000
```

## 7. Auditoria operativa corta

```bat
python main.py --quick-audit
python main.py --preflight-live-paper
python main.py --brain-report
```

Objetivo:
- confirmar conectividad Binance
- confirmar data fresca
- confirmar que el ledger este OK
- bloquear corridas largas si el edge neto no esta claro

## 8. Validar estado operativo

```bat
python main.py --readiness-check
python main.py --reconcile-ledger
python main.py --status-report
```

Revisar especialmente:
- `SAFE_TO_RUN_SHORT_PAPER`
- `SAFE_TO_RUN_LONG_PAPER`
- `Ledger Consistency Check: OK`
- `Current provider: BINANCE`
- `Latest candle status`

## 9. Benchmark de investigacion

```bat
python main.py --benchmark --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d"
python main.py --walk-forward --limit 10000 --train-pct 70 --timeframes "1m,5m,15m,30m,1h,4h,1d"
```

Nota:
- en PowerShell o CMD, dejar `--timeframes` entre comillas

## 10. Prueba corta de live paper

```bat
python main.py --market-watch-engine --max-loops 5
python main.py --autonomous-paper-engine --max-loops 5
```

Interpretacion:
- `market-watch-engine` observa y persiste decisiones sin abrir trades
- `autonomous-paper-engine` si puede abrir paper trades, pero solo si el brain sale de `OBSERVE_ONLY`
- si ambos pasan y el ledger sigue `OK`, la arquitectura viva esta sana aunque todavia no haya edge neto positivo

## 11. Prueba de 60 minutos

```bat
python main.py --live-paper-engine --run-minutes 60
```

Solo correr esto si:
- `python main.py --diagnose-connectivity` devuelve `BINANCE_HTTP_USABLE: YES`
- `python main.py --quick-audit` no marca bloqueo operativo grave
- `python main.py --preflight-live-paper` deja `SAFE_TO_RUN_LONG_PAPER: YES`
- `python main.py --reconcile-ledger` devuelve `result=OK`

## 12. Exportar auditoria

```bat
python main.py --export-report
python main.py --export-report --format csv
```

Archivos esperados:
- `runtime\report_export.json`
- `runtime\trades.csv`
- `runtime\decisions.csv`
- `runtime\signals.csv`
- `runtime\portfolio.csv`
- `runtime\errors.csv`
- `runtime\benchmark.csv`
- `runtime\rejected_trades.csv`
- `runtime\cost_analysis.csv`
- `runtime\readiness.csv`
- `runtime\net_profitability_summary.csv`
- `runtime\recent_agent_decisions.csv`

## 13. Politica de seguridad

- No activar trading real.
- No agregar API keys privadas.
- No conectar cuentas reales.
- No usar ordenes reales.
- No usar servicios pagos.
- No declarar rentable una estrategia que pierde despues de fees, slippage y spread.

## 14. Orden recomendado diario

1. `python main.py --diagnose-connectivity`
2. `python main.py --init-only`
3. cargar historia para `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`
4. `python main.py --quick-audit`
5. `python main.py --preflight-live-paper`
6. `python main.py --readiness-check`
7. `python main.py --reconcile-ledger`
8. `python main.py --status-report`
9. `python main.py --brain-report`
10. `python main.py --benchmark --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d"`
11. `python main.py --walk-forward --limit 10000 --train-pct 70 --timeframes "1m,5m,15m,30m,1h,4h,1d"`
12. `python main.py --market-watch-engine --max-loops 5`
13. `python main.py --autonomous-paper-engine --max-loops 5`
14. `python main.py --live-paper-engine --run-minutes 60`
15. `python main.py --export-report`
