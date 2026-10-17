# Datos simulados de demostración (cierre de DETECTAR)

## 1. Qué es

Un **cargador de conjuntos de datos sintéticos versionados** permite recorrer DETECTAR de extremo a
extremo en modo `simulated`, sin red y sin tocar datos reales. Es la única vía para crear
observaciones simuladas: los conectores siguen rechazando `simulated`.

```
conjunto JSON (sintético, versionado)
   └─ python -m app.modules.detectar.simulation cargar --db <base de demostración>
        └─ observaciones simulated con dataset_id = "<id>@<versión>"
   └─ endpoints existentes, sin cambios:
        POST /temas/normalizaciones → POST /metricas/calculos → POST /clasificaciones/calculos
        POST /agentes/{id}/ejecuciones
   └─ oficina (GET /api/oficina/* → GET /api/detectar/*)
```

- **Sin endpoint nuevo:** no hay ningún endpoint de escritura nuevo ni cambios de contrato.
- **Sin atajos:** las clasificaciones las calcula el servicio real con las reglas `stages-v1` sin modificar. No se insertan resultados a mano.

## 2. El conjunto `detectar_demo_sintetico` 1.0.0

Archivo: `simulation/datasets/detectar_demo_sintetico-1.0.0.json`. Se puede consultar con
`python -m app.modules.detectar.simulation describir`.

| Campo | Contenido |
|---|---|
| `naturaleza` | `sintetico_demostracion` (obligatorio: sin él no se carga) |
| `procedencia` | Redactado por el equipo DETECTAR con valores deterministas, no procede de ninguna fuente y no contiene datos personales |
| `periodo` | 2026-09-01 a 2026-09-30 (fechas fijas: reproducible) |
| `fechas_metricas` | 2026-09-21 a 2026-09-30 (diez fechas de referencia para las series) |
| `fecha_clasificacion` | 2026-09-30 |
| Unidades | Visitas diarias (`views`), artículos diarios (`articles`) y presencia en capturas (`presence`) |

**Escenarios** (temas inventados, todos llamados «Tema demo …») y resultado que producen las
reglas reales:

| Tema | Datos | Resultado de `stages-v1` |
|---|---|---|
| Alfa | Visitas con crecimiento acelerado, artículos en aumento y aparición reciente en Google Trends (MX) | `acelerando`: Wikimedia como evidencia principal, Google Trends `emergente` y GDELT complementaria (no validada) |
| Beta | Subida en la ventana anterior y meseta en la actual | `punto_maximo` |
| Gamma | Solo artículos (GDELT) | `datos_insuficientes` · `solo_fuente_no_validada` |
| Delta | Solo cinco días de visitas | `datos_insuficientes` · `sin_evidencia_temporal_suficiente`, con métricas `insufficient` y `valor: null` |
| Épsilon | Presencia constante en Google Trends | `datos_insuficientes` · `sin_evidencia_temporal_suficiente` |

**Limitaciones declaradas en el propio archivo:**
- las cifras son inventadas y no prueban ninguna tendencia;
- `fuente` indica qué formato de conector imita cada serie, no su origen;
- `fuente_validada` se refiere al conector real, no a estos datos;
- los artículos y términos no existen.

En la oficina, el modo simulado muestra una franja permanente: «conjunto sintético de demostración».

## 3. Protecciones del cargador

Antes de abrir la base, el cargador exige:
- una ruta **absoluta** a un `.db`;
- que la carpeta contenga la marca `.hack30x-demo-simulada` con `proposito = demo-simulada-hack30x`;
- que esté fuera de OneDrive, fuera del repositorio y fuera de la carpeta de la base real por
  defecto (`%LOCALAPPDATA%\hack30x\detectar`).

Después:
- **Datos reales:** si la base contiene **cualquier** registro `real` (observaciones,
  recolecciones, ejecuciones o temas), se niega y no escribe nada.
- **Idempotencia:** si el conjunto `id@versión` ya está cargado, responde `ya_cargado` sin
  escribir. Además, las observaciones tienen su propia clave de idempotencia.
- **Resultado:** una sola recolección `simulated` (`mode = "dataset"`) por conjunto, con
  `request_params.dataset`, `naturaleza` y `periodo`.

Con una ruta no apta, el comando sale con el código 2 y no crea ningún archivo.

## 4. Uso

Lo normal es usar el procedimiento de la oficina (`frontend/oficina`, `npm run demo:preparar`), que
crea la carpeta marcada, carga el conjunto y ejecuta el flujo. A mano, desde `backend/`:

```bash
.venv/Scripts/python.exe -m app.modules.detectar.simulation describir
.venv/Scripts/python.exe -m app.modules.detectar.simulation cargar --db C:\ruta\temporal\marcada\detectar.db
```

## 5. Pruebas

`tests/detectar/simulation/test_loader.py` (16 pruebas) cubre:
- **formato:** la naturaleza es obligatoria; se rechazan negativos, fechas fuera de periodo y campos extra;
- **protecciones:** rutas relativas, sin marca o con marca ajena, OneDrive, repositorio y base real;
- **seguridad de la escritura:** una base con datos reales se rechaza sin escribir, y una ruta no apta nunca se crea;
- **idempotencia:** cargar dos veces no duplica nada;
- **línea de comandos:** el comando `describir` y el código de salida con una ruta no apta;
- **recorrido real:** normalización, métricas y clasificación producen las etapas de la tabla, con la serie de Alfa ascendente, Delta `insufficient` con `null` y cero filas `real`.
