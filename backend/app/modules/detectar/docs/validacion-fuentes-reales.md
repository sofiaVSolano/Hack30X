# DETECTAR: guía de validación con fuentes reales

Para quien tenga acceso autorizado a Internet. Comandos en PowerShell, desde `backend/`,
con el entorno virtual `backend/.venv`.

## Tres niveles de validación (no son equivalentes)

| Nivel | Qué demuestra | Red real |
|---|---|---|
| 1. Pruebas automatizadas (`pytest tests/detectar`) | La lógica con respuestas simuladas | No (está bloqueada) |
| 2. Validación manual del conector | Que la fuente real responde en el formato esperado | Sí |
| 3. Extremo a extremo con persistencia | Conector + servicio de recolección + SQLite | Sí |

Que el nivel 1 pase **no** valida las fuentes reales.

## Estado al 17/10/2026

| Fuente | Nivel 2 | Nivel 3 |
|---|---|---|
| Google Trends RSS (MX) | Hecho | Hecho (1 solicitud, 10 tendencias, 20 observaciones, estado `ok`) |
| Wikimedia Pageviews | Hecho | Hecho (1 solicitud, "México", 3 días, 3 observaciones, estado `ok`) |
| GDELT DOC 2.0 | **Pendiente**: la API devolvió `{}` y luego HTTP 429. El 17/10 la raíz respondió HTTP 200, pero las consultas reales agotaron el tiempo de espera (15 s y luego 60 s) | **Pendiente** |

## Preparación común

```powershell
# Base temporal fuera de OneDrive (no usar la base de producción para validar)
$env:DETECTAR_DB_PATH = "$env:TEMP\hack30x-validacion\detectar.db"
```

## 1. Google Trends RSS para México (nivel 3)

```powershell
.\.venv\Scripts\python.exe -c "import asyncio; from app.modules.detectar.config import DetectarSettings; from app.modules.detectar.ingestion.collection import CollectionService; from app.modules.detectar.storage.db import create_sqlite_engine, init_db, create_session_factory; from app.modules.detectar.storage.models import Source; s = DetectarSettings(); e = create_sqlite_engine(s.db_path); init_db(e); r = asyncio.run(CollectionService(create_session_factory(e), s).collect([Source.GOOGLE_TRENDS_RSS], ['MX'])); print(r.run_id, r.status.value, [(x.status.value, x.inserted, x.error_code) for x in r.sources])"
```

**Resultado esperado:** estado `ok`, alrededor de 10 tendencias, es decir unas 20
observaciones (presencia y tráfico aproximado), y `error_code` en `None`. Si el estado es
`failed` o `partial`, el código de error indica la causa (`rate_limited`,
`invalid_response`, etc.).

## 2. Wikimedia Pageviews: un artículo, tres días cerrados (nivel 3)

El contacto debe ser **real y proporcionado por el equipo**: un correo o una URL del proyecto.
La política de Wikimedia exige un User-Agent identificable.

```powershell
$env:DETECTAR_WIKIMEDIA_MODE = "on"
$env:DETECTAR_HTTP_CONTACT = "<contacto real del equipo>"
.\.venv\Scripts\python.exe -c "import asyncio, datetime as d; from app.modules.detectar.config import DetectarSettings; from app.modules.detectar.connectors.params import WikimediaParams; from app.modules.detectar.ingestion.collection import CollectionService; from app.modules.detectar.storage.db import create_sqlite_engine, init_db, create_session_factory; from app.modules.detectar.storage.models import Source; s = DetectarSettings(); e = create_sqlite_engine(s.db_path); init_db(e); fin = d.date.today() - d.timedelta(days=2); p = WikimediaParams(articles=('México',), start=fin - d.timedelta(days=2), end=fin); r = asyncio.run(CollectionService(create_session_factory(e), s).collect([Source.WIKIMEDIA], [], wikimedia=p)); print(r.run_id, r.status.value, [(x.status.value, x.inserted, x.error_code) for x in r.sources])"
```

**Resultado esperado:** estado `ok` y 3 observaciones `wiki_pageviews`, una por día, con
`country` nulo e idioma `es`. Un 404 se registra como `article_not_found`, nunca como cero.

## 3. GDELT DOC 2.0 (nivel 3)

GDELT limita la frecuencia de solicitudes. El conector espera
`DETECTAR_GDELT_MIN_INTERVAL_SECONDS` (5 s por defecto) entre consultas. Conviene ejecutar
una sola consulta y no repetirla seguido.

```powershell
$env:DETECTAR_GDELT_MODE = "on"
.\.venv\Scripts\python.exe -c "import asyncio, datetime as d; from app.modules.detectar.config import DetectarSettings; from app.modules.detectar.connectors.params import GdeltParams; from app.modules.detectar.ingestion.collection import CollectionService; from app.modules.detectar.storage.db import create_sqlite_engine, init_db, create_session_factory; from app.modules.detectar.storage.models import Source; s = DetectarSettings(); e = create_sqlite_engine(s.db_path); init_db(e); fin = d.date.today() - d.timedelta(days=1); p = GdeltParams(terms=('inteligencia artificial',), start=fin - d.timedelta(days=9), end=fin, source_language='spanish'); r = asyncio.run(CollectionService(create_session_factory(e), s).collect([Source.GDELT], [], gdelt=p)); print(r.run_id, r.status.value, [(x.status.value, x.inserted, x.error_code, x.error_detail) for x in r.sources])"
```

**Resultado esperado:** estado `ok` con hasta 10 observaciones `gdelt_article_count`, una por
día. **Atención:** el formato JSON de GDELT no está verificado. Si llega
`invalid_response`, compartir `error_detail` para ajustar el parser. Un `rate_limited`
significa esperar y reintentar más tarde.

## Verificar lo persistido

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3, os; c = sqlite3.connect(os.environ['DETECTAR_DB_PATH']); print(c.execute('select id, data_mode, status, started_at, finished_at from collection_runs order by created_at desc limit 5').fetchall()); print(c.execute('select source, status, items, http_calls, error_code from source_runs').fetchall()); print(c.execute('select source, metric_key, count(*), min(period_start), max(period_start) from raw_observations group by 1, 2').fetchall()); print(c.execute('select count(*) from raw_observations where data_mode <> ''real''').fetchone())"
```

**Resultado esperado:** recolecciones en `real`, ninguna observación con `data_mode`
distinto de `real` y cantidades coherentes con lo que informó la recolección.

## Nivel API (opcional)

Para validar `POST /api/detectar/recolecciones` hace falta `uvicorn`. Es una dependencia
aprobada, pero no está instalada en `backend/.venv` y su instalación requiere autorización.
Mientras no exista el `main.py` compartido, el router se monta en una app temporal (ver el
informe de E4).
