# E11: programador periódico y recuperación de ejecuciones abandonadas

## 1. Arquitectura

```
AgentScheduler (asyncio, en el proceso de la API)
   │  cada tick (DETECTAR_SCHEDULER_TICK_SECONDS)
   ├── 1. recover_abandoned_runs()       → agent_runs: pending/running abandonadas → failed "abandoned"
   └── 2. por cada agente programado y vencido:
          LocalAgentCoordinator.start(agent_id, data_mode, trigger=scheduled, params)
             → misma instancia que usa POST /agentes/{id}/ejecuciones
```

- `agents/scheduler.py`: el plan (qué se programa y por qué no), el tick, el bucle y el apagado.
- `agents/recovery.py`: la recuperación de ejecuciones abandonadas.
- `LocalAgentCoordinator` (E3/E10): ejecuta, persiste, controla las transiciones e impide
  ejecuciones simultáneas.

  **Único cambio:** ahora mantiene en memoria el conjunto de ejecuciones activas
  (`active_run_ids()`).
- No hay red adicional, colas, hilos ni dependencias nuevas.

## 2. Configuración

| Variable | Por defecto | Significado |
|---|---|---|
| `DETECTAR_SCHEDULER_ENABLED` | `false` | Interruptor general. Apagado: no se ejecuta ni se recupera nada automáticamente |
| `DETECTAR_AGENT_SCHEDULES` | `{}` | Frecuencias en minutos, validadas por `AgentRegistry.resolve_schedules` (de 15 minutos a 7 días). **No hay frecuencias por defecto** |
| `DETECTAR_SCHEDULER_AGENT_MODES` | `{}` | `data_mode` de cada agente programado (`real` o `simulated`). **Obligatorio**: sin él, el agente no se programa |
| `DETECTAR_SCHEDULER_TREND_HUNTER_SOURCES` | `[]` | Fuentes que `trend_hunter` recolecta en cada ejecución programada. Solo admite `google_trends_rss`, porque Wikimedia y GDELT requieren artículos o términos explícitos. Vacío: solo procesa los datos ya guardados |
| `DETECTAR_SCHEDULER_TICK_SECONDS` | `60` | Cada cuánto se revisa el plan (de 5 a 3600 s) |
| `DETECTAR_AGENT_ABANDON_AFTER_SECONDS` | `3600` | Antigüedad mínima para considerar abandonada una ejecución. Debe ser al menos el doble del tiempo máximo de la tarea (300 s) |

Ejemplo:

```
DETECTAR_SCHEDULER_ENABLED=true
DETECTAR_AGENT_SCHEDULES={"trend_hunter": 240, "supervisor": 480}
DETECTAR_SCHEDULER_AGENT_MODES={"trend_hunter": "real", "supervisor": "real"}
DETECTAR_SCHEDULER_TREND_HUNTER_SOURCES=["google_trends_rss"]
```

## 3. Plan: qué se programa

Un agente se programa solo si cumple las cuatro condiciones:

1. tiene una frecuencia en `DETECTAR_AGENT_SCHEDULES`;
2. está `implementation_status = available` (hoy, `trend_hunter` y `supervisor`);
3. tiene un `data_mode` configurado;
4. sus parámetros se pueden construir de forma segura.

Si no, queda **omitido con un motivo** (`sin_frecuencia`, `no_implementado`,
`sin_data_mode`, `recoleccion_no_permitida`, `fuente_no_habilitada`, `recoleccion_solo_real`).
El motivo se registra en el log y se expone en `GET /api/detectar/agentes/programador`.

- Una configuración de frecuencias inválida hace fallar la creación del programador. No se
  ignora en silencio.
- `trend_hunter` en modo `simulated` con fuentes de recolección queda omitido: los conectores
  solo producen datos reales.

## 4. Parámetros y fechas

- **`trend_hunter`:** `as_of` = último día cerrado en UTC (la fecha UTC del reloj menos un día);
  nunca se usa la hora local. Lleva `collection` solo si hay fuentes configuradas, con los
  países de `DETECTAR_COUNTRIES`.
- **`supervisor`:** `{"per_agent_limit": 20}`. Ya se excluye a sí mismo (E10) y no inicia a
  otros agentes, así que no hay recursión.

## 5. Ciclo de vida

- **Inicio:** con `start()`, solo si `DETECTAR_SCHEDULER_ENABLED=true`; se crea una única tarea de
  asyncio. Llamarlo dos veces no crea otra.
- **Espera:** `asyncio.wait_for(stop_event.wait(), tick)`. El apagado despierta la espera de
  inmediato.
- **Tick:** primero la recuperación, después los agentes vencidos, **en orden y de uno en uno**.
- **Errores:** `AgentBusyError` se cuenta como `ocupado`, **no como fallo**. Cualquier otra
  excepción de un agente se registra en `errores` y el tick continúa con el siguiente; el bucle
  no se detiene.
- **Apagado:** `stop(timeout)` activa el evento, espera a que termine el tick en curso y, si
  supera el tiempo, cancela la tarea. Una ejecución cancelada a mitad puede quedar en
  `running`: la recuperación la cerrará cuando supere el umbral.

## 6. Cuándo vence un agente

Se usa la última ejecución **persistida** del agente en su `data_mode`, sea manual o programada.
Vence si no hay ninguna, o si `ahora - requested_at >= frecuencia`. Al usar datos persistidos,
sobrevive a reinicios, y una ejecución manual reciente aplaza la programada.

## 7. Concurrencia: alcance real

| Mecanismo | Alcance | Garantía |
|---|---|---|
| `LocalAgentCoordinator.start` comprueba `pending`/`running` y crea la ejecución sin `await` intermedio | Un proceso, un event loop | No hay dos ejecuciones del mismo agente en el mismo proceso. El programador y la API comparten el coordinador |
| Ticks secuenciales con una sola tarea del programador | Un proceso | El programador no se solapa consigo mismo |
| `CollectionService` (bloqueo de asyncio + comprobación en SQLite) | Un proceso, más una comprobación no atómica entre procesos | Una recolección real a la vez por proceso |

**No hay exclusión garantizada entre varios procesos**, por ejemplo varios workers. La
comprobación en SQLite no es atómica. **Recomendación operativa:** un único proceso con el
programador activado.

## 8. Recuperación de ejecuciones abandonadas

**Candidata:** está en `pending` o `running`, en cualquiera de los dos modos.

**Se cierra como `failed` con el código `abandoned` solo si se cumplen TODAS estas condiciones:**

1. Su id **no** está entre las ejecuciones activas del coordinador de este proceso. Una tarea
   lenta de este proceso nunca se recupera, por mucho tiempo que lleve.
2. Su antigüedad persistida (`started_at` si está en `running`, `requested_at` si está en
   `pending`) es de al menos `DETECTAR_AGENT_ABANDON_AFTER_SECONDS`.
3. La transición es válida y la fila sigue en el mismo estado: actualización condicional, y
   además el trigger de SQLite lo verifica.

**Por qué 1 + 2 bastan:**
- En este proceso, el registro en memoria distingue una tarea lenta de una abandonada.
- Fuera de este proceso, por ejemplo tras una caída o reinicio, la ejecución ya no tiene quién la
  termine.

**Riesgo residual:** otro proceso vivo con una tarea que bloquee más tiempo que el umbral podría
recuperarse por error. Por eso el umbral por defecto es de 1 hora (12 veces el tiempo máximo de
la tarea) y se recomienda un único proceso.

**Detalle registrado:** "Ejecución abandonada: en estado X desde <fecha UTC>; superó N s sin
proceso activo que la ejecute." No incluye secretos.

**Propiedades:**
- Nunca se borra nada.
- Las ejecuciones terminadas no se tocan; los triggers lo impiden de todos modos.
- Es idempotente: una segunda pasada no encuentra candidatas.
- Un error de base de datos al cerrar una candidata se registra en `errores` del informe y **no
  cuenta como recuperada**.

## 9. Integración en la app (hecha en E12)

`backend/app/main.py` usa `detectar_scheduler_lifespan()` en su `lifespan` (ver
`e12-integracion-backend.md`). Con `DETECTAR_SCHEDULER_ENABLED=false` no se crea nada; con
`true`, el programador se inicia al arrancar la app y se detiene de forma ordenada al apagarla.
Se verificó con un servidor Uvicorn real.

## 10. Pruebas

- Reloj inyectado.
- Llamadas directas a `tick()`.
- `start()`/`stop()` reales pero sin esperas: el evento despierta la espera.
- Transporte HTTP simulado.
- Base SQLite temporal.
- Ninguna llamada de red.
