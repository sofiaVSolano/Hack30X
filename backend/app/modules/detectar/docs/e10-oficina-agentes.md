# E10: oficina de agentes, ejecución real en el backend

## 1. Alcance

- Tareas deterministas, sin modelos de lenguaje, para `trend_hunter` y `supervisor`.
- `POST /api/detectar/agentes/{agent_id}/ejecuciones`, protegido con el token administrativo.
- No hay ejecución periódica (E11), ni frontend, ni modelos de lenguaje.
- Los otros cuatro roles siguen en `planned`: sus ejecuciones quedan `blocked` con el código
  `not_implemented`, igual que en E3.

## 2. Contratos reutilizados (sin cambios)

| Contrato | Origen | Uso en E10 |
|---|---|---|
| `LocalAgentCoordinator.start()` | E3 | Crea la ejecución (`pending`), la pasa a `running`, ejecuta la tarea y la cierra como `completed`, `failed` o `blocked`. **Es síncrono**: responde cuando la ejecución ya terminó |
| `agent_runs` con triggers | E3 | Transiciones válidas, `completed` con resultado, `failed` y `blocked` con código y detalle, filas terminadas inmutables. **No se cambia el esquema** |
| `CollectionService.collect()` | E4 a E6 | Recolección real con bloqueo contra recolecciones simultáneas. Se usa **la misma instancia** que `POST /recolecciones`, para compartir ese bloqueo |
| `TopicLinker.process()` | E7 | Normalización idempotente de observaciones sin vínculo |
| `MetricsService.compute()` | E8 | Métricas de la fecha de referencia |
| `ClassificationService.classify()` | E9 | Etapas `stages-v1` |
| `AgentRunRepository` | E3 | Lectura de ejecuciones para el supervisor |

## 3. `trend_hunter`

### Parámetros, validados antes de crear la ejecución y otra vez dentro de la tarea

```json
{
  "fecha_referencia": "2026-10-16",
  "recoleccion": {
    "fuentes": ["google_trends_rss"],
    "paises": ["MX"],
    "wikimedia": null,
    "gdelt": null
  }
}
```

- `fecha_referencia` es **obligatoria** y debe ser un día cerrado: es el `as_of` de las métricas
  y de la clasificación.
- `recoleccion` es opcional. Si falta, no se recolecta y solo se procesan los datos ya
  guardados. Sus reglas de validación son las mismas que las de `POST /recolecciones`.
- `data_mode` llega aparte y es obligatorio. Con `simulated`, **no se admite `recoleccion`**,
  porque los conectores solo producen datos reales.

### Flujo

Cada paso abre su propia transacción, así que un paso fallido no deshace los anteriores, que ya
quedaron registrados.

1. **Recolección** (opcional, solo `real`): `CollectionService.collect()`.
   - Estado `failed`: la tarea **falla** con el código `collection_failed`, porque no consiguió
     señales. La recolección queda registrada con su `run_id`.
   - Estado `partial`: se continúa y las fuentes fallidas se listan en `limitaciones`.
   - Fuente no habilitada o recolección en curso: la tarea falla, sin ocultar el motivo.
2. **Normalización:** `TopicLinker.process()`, por lotes de 5000 observaciones, hasta 20 lotes.
   Si quedan observaciones pendientes, se informa en `limitaciones`.
3. **Métricas:** `MetricsService.compute(as_of=fecha_referencia)`.
4. **Clasificación:** `ClassificationService.classify(as_of=fecha_referencia)`.

### Resultado (`agent_runs.result`)

Solo contiene lo que devolvieron los servicios: conteos e identificadores, nunca datos
inventados.

```json
{
  "agente": "trend_hunter", "version_resumen": "trend_hunter-v1", "data_mode": "real",
  "fecha_referencia": "2026-10-16",
  "estado_objetivo": "completo | con_limitaciones",
  "pasos": {
    "recoleccion": {"ejecutada": true, "run_id": "run_…", "estado": "partial", "fuentes": {...}},
    "normalizacion": {"procesadas": 20, "temas_creados": 10, "por_estado": {...}, "pendientes": false},
    "metricas": {"version": "metrics-v1", "valores_escritos": 54, "por_estado": {...}},
    "clasificacion": {"version": "stages-v1", "calibrada": false, "creadas": 10, "sin_cambios": 0, "por_etapa": {...}}
  },
  "limitaciones": ["..."]
}
```

- `estado_objetivo = con_limitaciones` cuando hay fuentes fallidas, lotes pendientes, ninguna
  métrica `ok` o ninguna etapa distinta de `datos_insuficientes`.
- Se añaden siempre estas limitaciones fijas: reglas provisionales y no calibradas, GDELT no
  validada (cuando interviene) y que "saturada" no se asigna.
- No hay porcentajes de confianza ni puntuaciones.

### Límite temporal conocido

Las observaciones recolectadas hoy no entran en las ventanas de una `fecha_referencia`
anterior, por ejemplo ayer. Se procesan, pero sus métricas aparecerán cuando ese día esté
cerrado y se use como fecha de referencia.

## 4. `supervisor`

- **Parámetros:** `{"limite_por_agente": 20}`, opcional, entre 1 y 100.
- Lee **solo** `agent_runs` del `data_mode` indicado, mediante `AgentRunRepository.list_runs`.
  No ejecuta a nadie ni modifica nada.
- **Se excluye a sí mismo**, para evitar recursión y para no contar su propia ejecución, que en
  ese momento está en `running`.
- **Resultado** (`supervisor-v1`), por agente:
  - `definido`, `implementado`;
  - `ultima_ejecucion` (id, estado, fechas, código de error) o `null`;
  - `conteo_por_estado` sobre las últimas N ejecuciones;
  - `ejecuciones_consideradas`.

  Además informa `agentes_sin_ejecuciones`, `totales_por_estado` y `limitaciones`.
- **Sin ejecuciones previas:** `sin_actividad_registrada = true` y conteos en 0. No se simula
  actividad.
- **Determinista:** con el mismo estado de la base devuelve el mismo resultado.

## 5. Endpoint

`POST /api/detectar/agentes/{agent_id}/ejecuciones`. El prefijo `/api/detectar` lo pone el
router principal del módulo.

```json
{"data_mode": "real", "parametros": {"fecha_referencia": "2026-10-16"}}
```

| Situación | HTTP | Cuerpo |
|---|---|---|
| Ejecución realizada, con cualquier estado final (`completed`, `failed` o `blocked`) | 201 | La ejecución registrada; hay que leer `estado` |
| Agente desconocido | 404 | `not_found` |
| `data_mode` ausente o inválido, o parámetros inválidos para ese agente | 422 | `validation_error` o `invalid_parameters` |
| `recoleccion` inválida en `trend_hunter` | 422 | Mismos códigos que `POST /recolecciones` (`source_not_enabled`, `country_not_allowed`, etc.) |
| El agente ya tiene una ejecución activa | 409 | `agent_busy` |
| Error de persistencia o error inesperado | 500 | `internal_error`, sin detalles internos |
| Sin token o token inválido | 401 / 403 | Igual que el resto de la API |

- Solo se ejecutan tareas del mapa fijo `TASKS` (`agents/tasks.py`). El cliente envía un
  identificador validado con `^[a-z][a-z0-9_]{2,63}$`, nunca nombres de funciones.
- Los agentes sin tarea solo admiten `parametros = {}` y producen una ejecución `blocked`, que
  es real y queda registrada.

## 6. Cambios fuera del código nuevo

- `api/collections.py`: la validación de `POST /recolecciones` se extrajo, sin cambios de
  comportamiento, a `validate_collection_request()`, para reutilizarla en `trend_hunter`.
- `api/dependencies.py`: `get_agent_coordinator()`, que se crea de forma perezosa y reutiliza el
  servicio de recolección compartido.
- `agents/tasks.py` (nuevo): las tareas y el mapa fijo `build_tasks()`.
- `agents/registry.py`: `trend_hunter` y `supervisor` pasan a
  `implementation_status = available`. Los demás siguen en `planned`.
- `api/agents.py`: añade el `POST`, y `agente` y `data_mode` en la salida de una ejecución
  (cambio aditivo).
- No hay cambios de esquema ni de archivos compartidos.

## 7. Riesgos conocidos (para E11)

- Si la base de datos falla después de crear la ejecución, esta puede quedar en
  `pending`/`running`, y el agente quedaría "ocupado" (409) hasta una recuperación manual. E11
  debe añadir la detección de ejecuciones abandonadas.
- Ejecución síncrona: `trend_hunter` con recolección puede tardar decenas de segundos. El tiempo
  máximo de la tarea es de 300 s; al superarlo, la ejecución queda `failed` con
  `task_timeout`.
