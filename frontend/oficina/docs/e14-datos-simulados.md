# E14: datos simulados trazables para la oficina

> **Actualización (cierre de DETECTAR):** la limitación de este documento está **resuelta**. El cargador de conjuntos sintéticos propuesto en la sección 3 ya existe (`backend/app/modules/detectar/simulation/`, ver `backend/app/modules/detectar/docs/datos-simulados.md`) y `npm run demo:preparar` ya produce temas, métricas, series y clasificaciones. Este documento se conserva como registro de E14.

## 1. Conclusión

**Con las capacidades actuales de DETECTAR no se pueden producir de forma legítima temas,
métricas, series ni clasificaciones simuladas.** El primer eslabón del flujo, la incorporación de
observaciones en modo `simulated`, no tiene ninguna operación de aplicación. No se ha forzado: no
se escribieron observaciones a mano ni se insertó nada directamente en las tablas.

Lo que **sí** existe y se ha convertido en un procedimiento reproducible es todo el flujo
posterior en modo `simulated`: normalización, métricas, clasificación y ejecución de agentes.
Sobre una base sin observaciones produce resultados reales pero vacíos (0 temas, 0 valores,
0 clasificaciones) y ejecuciones de agentes persistidas y etiquetadas como simuladas.

## 2. Flujo real de extremo a extremo (inspeccionado en el código)

| # | Paso | Operación existente | ¿Admite `simulated`? |
|---|---|---|---|
| 1 | Registro de temas | No hay alta manual: los temas nacen al normalizar observaciones (`TopicLinker`) | Sí, pero necesita observaciones |
| 3 | **Incorporación de observaciones** | `POST /recolecciones` → conectores → `record_connector_result` | **No.** `record_connector_result` rechaza cualquier modo distinto de `real` («Los conectores solo producen datos reales»), y `POST /recolecciones` es solo real |
| 3b | (almacenamiento) | `DetectarRepository.add_observations(..., data_mode="simulated", dataset_id=...)` | Lo admite el **repositorio**, con `dataset_id` obligatorio (restricción `ck_raw_observations_dataset_id`), pero **ningún endpoint, servicio ni cargador lo usa**. Solo lo usan las pruebas del backend, con valores escritos a mano |
| 2 | Normalización y resolución | `POST /temas/normalizaciones {data_mode}` | Sí |
| 4 | Métricas | `POST /metricas/calculos {data_mode, fecha_referencia}` | Sí |
| 5 | Clasificación | `POST /clasificaciones/calculos {data_mode, fecha_referencia}` | Sí |
| 6 | Agentes | `POST /agentes/{id}/ejecuciones {data_mode, parametros}` (`trend_hunter` sin `recoleccion`, `supervisor`; los demás quedan `blocked`) | Sí |
| 7 | Consulta | `GET /api/oficina/*` (intermediario) → `GET /api/detectar/*` | Sí, un modo por consulta |
| 8 | Visualización | Vistas de la oficina | Sí |

### Por qué no se forzó el paso 3

Crear observaciones simuladas exigiría:
- **inventar sus valores** (visitas de Wikimedia, artículos de GDELT, presencias de Google Trends);
- **saltarse el flujo de ingesta**, escribiendo con el repositorio desde un script.

Ambas cosas están excluidas en E14: no inventar datos ni insertar directamente en tablas. Los
únicos datos simulados que existen en el proyecto son los de las pruebas automatizadas, escritos a
mano, y no son un conjunto de demostración aprobado.

## 3. Modificación mínima propuesta (etapa posterior, requiere aprobación)

**Cargador de conjuntos de datos simulados versionados**, dentro de DETECTAR:

1. **Formato:** un archivo de conjunto de datos declarado y revisado por el equipo, por ejemplo
   `backend/app/modules/detectar/simulation/datasets/<id>.json`, con `dataset_id`, descripción,
   origen de cada valor (sintético y documentado, o derivado de una respuesta real archivada con
   su fecha y licencia) y observaciones con el mismo esquema que `ObservationIn`.
2. **Operación:** un comando local, por ejemplo `python -m app.modules.detectar.simulation.cargar
   <id>`, o un endpoint administrativo `POST /api/detectar/simulaciones/{dataset_id}`, que:
   - crea una recolección y ejecuciones por fuente en modo `simulated`, con `mode="dataset"`;
   - inserta con `add_observations(..., data_mode="simulated", dataset_id=<id>)`, que es
     idempotente por clave;
   - se niega a ejecutarse contra una base que no sea explícitamente de demostración.
3. **Pruebas:** idempotencia (cargar dos veces no duplica), aislamiento (cero filas reales),
   `dataset_id` en todas las filas y que los conectores reales siguen rechazando `simulated`.

Con eso, el procedimiento de la sección 4 solo necesitaría un paso más («cargar el conjunto»)
antes de normalizar. El resto no cambia.

**Decisiones del equipo:**
- si se aprueba un conjunto sintético, quién lo redacta y lo revisa;
- si se permite usar respuestas reales archivadas como base (licencias de las fuentes);
- si el cargador es un comando local o un endpoint administrativo.

## 4. Procedimiento reproducible (lo que sí es posible hoy)

Requisitos:
- `backend/.venv` con las dependencias de E12;
- `frontend/oficina` con `npm ci` y `npm run build`;
- Edge instalado, solo para la verificación visual.

Desde `frontend/oficina/`:

```bash
npm run demo:preparar            # crea la base aislada y ejecuta el flujo en modo simulated
npm run demo:servir              # backend y oficina sobre esa base: http://127.0.0.1:<puerto>/?modo=simulated
npm run demo:verificar -- --salida <carpeta>   # separación de modos, barrido visual, teclado y recuperación
npm run demo:limpiar             # borra SOLO la carpeta creada por el procedimiento
```

**Qué hace `demo:preparar`:**
1. Usa `%TEMP%\hack30x-demo-simulada` (aquí: `C:\Users\sofia\AppData\Local\Temp\hack30x-demo-simulada`),
   o la ruta de `--dir`, y comprueba que:
   - es absoluta;
   - no está en OneDrive;
   - no está en el repositorio;
   - no coincide con la carpeta de la base real (`%LOCALAPPDATA%\hack30x\detectar`).
2. Si la carpeta existe y **no** tiene la marca `.hack30x-demo-simulada`, se niega a tocarla. Si
   tiene la marca, exige `--reiniciar` y la recrea desde cero, así que nunca acumula datos
   duplicados.
3. Arranca uvicorn en `127.0.0.1`:
   - con `DETECTAR_DB_PATH` apuntando a esa carpeta;
   - con un token aleatorio que solo vive en la memoria de los procesos;
   - con el programador apagado;
   - sin heredar ninguna variable `DETECTAR_*` del entorno.
4. Ejecuta, **solo con endpoints existentes y solo en `simulated`**:
   - normalización;
   - métricas y clasificación del último día cerrado en UTC;
   - `trend_hunter` (sin recolección: no hay red), `format_hunter` y `supervisor`.
5. Comprueba que el modo real sigue vacío y que el token no aparece en el log, detiene el backend
   y guarda `registro.json`, con cada solicitud, cuerpo y resultado.

**Resultado obtenido el 2026-10-17** (`registro.json`, fecha de referencia 2026-10-16):

| Paso | Resultado |
|---|---|
| Normalización | `procesadas: 0, temas_creados: 0` |
| Métricas | `valores_escritos: 0` |
| Clasificación | `creadas: 0` |
| `trend_hunter` | `completed`, `estado_objetivo: con_limitaciones`, con estas limitaciones: «Ninguna métrica pudo calcularse con datos suficientes…», «Ningún tema tiene una etapa sostenida por evidencia suficiente», reglas no calibradas, «saturada» no se asigna |
| `format_hunter` | `blocked`, `not_implemented` |
| `supervisor` | `completed` |
| Aislamiento | 0 agentes con ejecuciones reales |

**Comprobaciones de seguridad del procedimiento (ejecutadas):**
- una segunda ejecución sin `--reiniciar` se niega;
- `limpiar` y `preparar --reiniciar` se niegan con una carpeta ajena, que queda intacta;
- una ruta dentro de OneDrive o del repositorio se rechaza;
- la base real por defecto no se creó.

## 5. Qué se puede y qué no se puede verificar visualmente hoy

| Vista o estado | ¿Con datos simulados reales? |
|---|---|
| Oficina, 6 agentes, indicadores | Sí: 3 con ejecuciones (2 `completed`, 1 `blocked`), 3 sin ejecuciones |
| Historial y detalle de ejecución | Sí |
| Programador | Sí (apagado, con motivos de omisión) |
| Separación real/simulado | Sí |
| Error y recuperación con el backend caído | Sí |
| Temas: lista y detalle | **Solo el estado vacío**: sin observaciones no hay temas |
| Métricas: catálogo | Sí (no depende de datos) |
| Métricas: valores y **gráfica** | **No**: 0 valores |
| Clasificaciones con evidencias, «datos insuficientes» | **No**: 0 clasificaciones (solo el panel de reglas y el estado vacío) |

Las vistas de la última fila solo están cubiertas por pruebas automatizadas con datos de prueba.
