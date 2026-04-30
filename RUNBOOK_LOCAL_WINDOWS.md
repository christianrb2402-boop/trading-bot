# Runbook Local Windows

Este runbook asume que el bot se ejecutara en una computadora fija Windows, sin VPN, con conectividad HTTP real hacia Binance y siempre en modo simulado.

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

Ejecutar por timeframe:

```bat
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 5m --limit 1000
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 15m --limit 1000
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 30m --limit 1000
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1h --limit 1000
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 4h --limit 1000
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1d --limit 1000
```

## 7. Validar estado operativo

```bat
python main.py --readiness-check
python main.py --reconcile-ledger
python main.py --status-report
```

Objetivo:
- Confirmar `READY_FOR_LIVE_PAPER`
- Confirmar `Ledger Consistency Check: OK`
- Ver si la data esta fresca o stale
- Ver simbolos faltantes o con gaps

## 8. Ejecutar benchmark de investigacion

Importante para PowerShell o CMD:
- cuando uses `--timeframes`, pasa la lista entre comillas

```bat
python main.py --benchmark --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d"
python main.py --walk-forward --limit 10000 --train-pct 70 --timeframes "1m,5m,15m,30m,1h,4h,1d"
```

## 9. Ejecutar prueba corta de live paper

```bat
python main.py --live-paper-engine --max-loops 5
```

## 10. Ejecutar prueba por tiempo

```bat
python main.py --live-paper-engine --run-minutes 60
```

Solo correr esto si:
- `--diagnose-connectivity` dice `BINANCE_HTTP_USABLE: YES`
- `--readiness-check` recomienda `LIVE_BINANCE`
- `--reconcile-ledger` devuelve `result=OK`

## 11. Exportar reporte auditable

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

## 12. Politica de seguridad

- No activar trading real.
- No agregar API keys privadas.
- No conectar cuentas reales.
- No usar ordenes reales.
- No usar servicios pagos.
- Si Binance falla, usar fallback local solo como emergencia o validacion acotada.
- No declarar rentable una estrategia que no cubre fees, slippage y spread.

## 13. Orden recomendado de uso diario

1. `python main.py --diagnose-connectivity`
2. `python main.py --init-only`
3. `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000`
4. `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 5m --limit 1000`
5. `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 15m --limit 1000`
6. `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 30m --limit 1000`
7. `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1h --limit 1000`
8. `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 4h --limit 1000`
9. `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1d --limit 1000`
10. `python main.py --readiness-check`
11. `python main.py --reconcile-ledger`
12. `python main.py --status-report`
13. `python main.py --benchmark --limit 5000 --timeframes "1m,5m,15m,30m,1h,4h,1d"`
14. `python main.py --walk-forward --limit 10000 --train-pct 70 --timeframes "1m,5m,15m,30m,1h,4h,1d"`
15. `python main.py --live-paper-engine --max-loops 5`
16. `python main.py --live-paper-engine --run-minutes 60`
17. `python main.py --export-report`
