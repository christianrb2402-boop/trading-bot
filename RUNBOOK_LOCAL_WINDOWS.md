# Runbook Local Windows

Este runbook asume que el bot se ejecutará en una computadora fija Windows, sin VPN, con conectividad HTTP real hacia Binance y siempre en modo simulado.

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

## 4. Diagnóstico HTTP real hacia Binance

```bat
python main.py --diagnose-connectivity
```

Interpretación:

- Si `BINANCE_HTTP_USABLE: YES`, Binance es usable aunque `nslookup` falle.
- Si `BINANCE_HTTP_USABLE: NO`, no correr live paper largo todavía.

## 5. Inicializar SQLite

```bat
python main.py --init-only
```

## 6. Cargar historia fresca

```bat
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000
```

## 7. Validar estado operativo

```bat
python main.py --readiness-check
python main.py --status-report
```

Objetivo:

- Confirmar `READY_FOR_LIVE_PAPER`
- Ver si la data está fresca o stale
- Ver símbolos faltantes o con gaps

## 8. Ejecutar prueba corta

```bat
python main.py --live-paper-engine --max-loops 5
```

## 9. Ejecutar prueba por tiempo

```bat
python main.py --live-paper-engine --run-minutes 60
```

Solo correr esto si:

- `--diagnose-connectivity` dice `BINANCE_HTTP_USABLE: YES`
- `--readiness-check` recomienda `LIVE_BINANCE`

## 10. Exportar reporte auditable

```bat
python main.py --export-report
```

Archivo esperado:

- `runtime\report_export.json`

## 11. Política de seguridad

- No activar trading real.
- No agregar API keys privadas.
- No conectar cuentas reales.
- No usar órdenes reales.
- No usar servicios pagos.
- Si Binance falla, usar fallback local solo como emergencia o validación acotada.

## 12. Orden recomendado de uso diario

1. `python main.py --diagnose-connectivity`
2. `python main.py --init-only`
3. `python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000`
4. `python main.py --readiness-check`
5. `python main.py --status-report`
6. `python main.py --live-paper-engine --max-loops 5`
7. `python main.py --live-paper-engine --run-minutes 60`
8. `python main.py --export-report`
