# Revisión del contrato DETECTAR → ENTENDER (`detectar.v0`)

**Estado: propuesta para discutir con el equipo de ENTENDER. Nada está acordado ni congelado.**
Este documento no impone cambios a ENTENDER ni crea endpoints nuevos.

## 1. Dónde estaba la propuesta

`detectar.v0` **no existía en el repositorio**. Solo se redactó en las conversaciones de diseño
(fase 3 y etapa 0) y nunca se guardó. Esta revisión la reconstruye y la contrasta con las
respuestas **reales** de la API, en los modelos de `api/classifications.py`, `api/topics.py` y
`api/metrics.py`, y con las pruebas que los verifican.

### Campos de la propuesta original

| Obligatorios | Opcionales |
|---|---|
| `contract_version`, `data_mode`, `topic_id`, `tema`, `pais`, `as_of`, `rules_version`, `fase`, `confianza{valor,nivel}`, `saturacion{valor,nivel,tipo,base,nota}`, `oportunidad{valor,nivel,motivo}`, `limitaciones[]`, `fuentes[]` | `alias`, `fase_motivos`, `componentes`, `senales`, `faltantes`, `explicacion`, `historial_url`, `youtube_en_vivo_url` |

## 2. Lo que la API proporciona realmente

Todos los endpoints exigen el token administrativo, que nunca debe ir en un navegador.

| Necesidad | Endpoint real | Campos reales |
|---|---|---|
| Etapa del tema | `GET /api/detectar/clasificaciones` | `id`, `tema_id`, `data_mode`, `etapa`, `motivo`, `fecha_referencia`, `calculado`, `version`, `version_metricas`, `calibrado`, `reemplazada`, `evidencia[]`, `metricas_consideradas[]`, `explicacion` |
| Evidencia por fuente | dentro de `evidencia[]` | `fuente`, `rol` (`primary` / `complementary` / `excluded`), `fuente_validada`, `etapa_propuesta`, `motivo`, `ambitos[]` (con regla y explicación) |
| Nombre del tema y alias | `GET /api/detectar/temas/{tema_id}` | `tema{id, nombre, clave_normalizada, ambiguo, ...}`, `alias[]`, `sujetos[]` |
| Métricas | `GET /api/detectar/metricas?tema_id=` | `fuente`, `ambito`, `metrica`, `unidad`, `valor`, `estado`, `motivo`, `periodo_*`, `version`, `fuente_validada`, `detalles` |
| Definiciones | `GET /metricas/definiciones`, `GET /clasificaciones/reglas` | Fórmulas, unidades y umbrales provisionales |

### Cómo se representan los límites

| Situación | Representación real |
|---|---|
| Datos insuficientes | `etapa = "datos_insuficientes"` con `motivo` (`sin_evidencia_temporal_suficiente`, `solo_fuente_no_validada`, `senales_contradictorias`). Cada métrica `insufficient` lleva `valor: null` y `motivo` |
| Fuente no validada (GDELT) | `fuente_validada: false` en la evidencia y en las métricas; `rol: "complementary"`; nunca determina la etapa |
| Reglas no calibradas | `calibrado: false` en cada clasificación y `explicacion.provisional: true` |
| País | **Solo** en métricas de Google Trends (`ambito` = país informado por Google) y de GDELT (`ambito` = consulta con país del medio). Wikimedia no tiene país |

## 3. Diferencias entre la propuesta y la API

| Campo propuesto | Realidad | Tipo |
|---|---|---|
| `contract_version` | No existe | Pendiente de decisión |
| `topic_id` / `tema` | `tema_id` en la clasificación; el nombre requiere `GET /temas/{id}` | Nombre distinto, dos consultas |
| `pais` (a nivel de tema) | **No existe**: las clasificaciones son por tema, no por país | Diferencia de diseño |
| `as_of` | `fecha_referencia` | Nombre distinto |
| `rules_version` | `version` (`stages-v1`) y `version_metricas` (`metrics-v1`) | Más preciso |
| `fase` | `etapa` (`emergente`, `acelerando`, `punto_maximo`, `saturada`, `datos_insuficientes`) | Nombre distinto. `saturada` **nunca se asigna** en v1 |
| `confianza{valor,nivel}` | **No existe**. Decisión deliberada: no hay porcentajes de confianza inventados | No disponible |
| `saturacion{...}` | **No existe**. No hay datos de oferta de contenido (RF-04 pendiente) | No disponible |
| `oportunidad{...}` | **No existe** (RF-04 pendiente) | No disponible |
| `limitaciones[]` | Dispersas: `motivo`, `explicacion.notes`, `evidencia[].motivo` y los `motivo` de cada métrica | Sin lista única |
| `fuentes[]` | `evidencia[]`, más rico: rol, validación y regla | Más preciso |
| `explicacion` | Existe, como objeto estructurado (no como texto) | Distinto formato |
| `alias` | `GET /temas/{id}` → `alias[]` | Otro endpoint |
| `senales` | `GET /metricas?tema_id=` | Otro endpoint |
| `historial_url`, `youtube_en_vivo_url` | No existen. YouTube no está implementado | No disponible |
| (no estaba) `calibrado`, `data_mode`, `reemplazada` | Existen | A favor de la API |

## 4. Propuesta revisada `detectar.v0.1`

Se compone **solo de campos que ya existen**. Ningún endpoint los agrega hoy en una sola
respuesta; ENTENDER tendría que combinar tres consultas o pedir un endpoint de agregación
(decisión pendiente, sección 5).

```json
{
  "tema_id": "tpc_3f9a1c2b7d4e8a01",
  "tema": "México",
  "data_mode": "real",
  "fecha_referencia": "2026-10-16",
  "etapa": "acelerando",
  "motivo": null,
  "version": "stages-v1",
  "version_metricas": "metrics-v1",
  "calibrado": false,
  "evidencia": [
    {"fuente": "wikimedia", "rol": "primary", "fuente_validada": true, "etapa_propuesta": "acelerando", "motivo": "señal consistente entre ámbitos"},
    {"fuente": "gdelt", "rol": "complementary", "fuente_validada": false, "etapa_propuesta": "emergente", "motivo": "señal consistente entre ámbitos"}
  ],
  "metricas_consideradas": ["…tal como las devuelve GET /clasificaciones…"],
  "explicacion": {"provisional": true, "notes": ["…"], "sources": {"…": "…"}}
}
```

Los valores de ejemplo son ilustrativos y no provienen de datos reales.

**Campos que DETECTAR puede comprometerse a mantener** (si el equipo los acepta): `tema_id`,
`data_mode`, `fecha_referencia`, `etapa`, `motivo`, `version`, `version_metricas`, `calibrado`,
y en `evidencia[]` los campos `fuente`, `rol`, `fuente_validada` y `etapa_propuesta`.

**Campos sin compromiso de estabilidad:** el contenido interno de `explicacion`,
`metricas_consideradas[]` y `ambitos[]`, que siguen evolucionando.

## 5. Preguntas pendientes para el equipo de ENTENDER

1. ¿Qué necesita realmente: solo la etapa y la evidencia, o también las métricas detalladas?
2. ¿Le sirven tres consultas, o hace falta un endpoint de agregación (por ejemplo,
   `GET /api/detectar/temas/{id}/resumen`)? Requiere acuerdo antes de implementarlo.
3. ¿Consulta por petición (pull) o espera notificaciones (webhook o cola)?
4. ¿Cómo se autenticará entre módulos, si el token administrativo no debe compartirse?
5. ¿Acepta que no haya `confianza`, `saturacion` ni `oportunidad` hasta resolver RF-04?
6. ¿Necesita el país a nivel de tema? Hoy no existe con honestidad; solo hay país por métrica.
7. ¿Usará `data_mode=simulated` en la demostración y cómo lo distinguirá en su interfaz?
8. ¿Cómo maneja la fusión de temas, cuando exista, y los temas `ambiguo`?
9. ¿Qué política de versiones (por ejemplo, `contract_version`) y de cambios incompatibles
   quiere?
10. ¿Idioma y formato de las explicaciones: estructuradas, como ahora, o texto?

## 6. Estado de implementación al cierre de DETECTAR (E15)

**El contrato sigue sin acordarse con ENTENDER.** Esta tabla no lo modifica: solo separa lo que la
API ya ofrece de lo que sigue siendo una propuesta.

| Capacidad de `detectar.v0.1` | Estado |
|---|---|
| Etapa por tema (`GET /clasificaciones`: `etapa`, `motivo`, `fecha_referencia`, `version`, `version_metricas`, `calibrado`) | **Implementada y probada** |
| Evidencia por fuente (`evidencia[]`: `fuente`, `rol`, `fuente_validada`, `etapa_propuesta`, `motivo`) | **Implementada y probada.** Al cierre, `fuente_validada` de una fuente excluida sin métricas refleja el estado real del conector (ver `clasificacion-etapas-v1.md`) |
| Nombre, alias y sujetos del tema (`GET /temas/{id}`) | **Implementada y probada** |
| Métricas por tema, fuente y ámbito (`GET /metricas`), con `valor: null` y `motivo` cuando son insuficientes | **Implementada y probada** |
| `data_mode` separado (`real` o `simulated`) en todas las respuestas | **Implementada y probada.** Los datos `simulated` proceden solo de conjuntos sintéticos declarados (`datos-simulados.md`) |
| Respuesta única agregada (`GET /temas/{id}/resumen` u otra) | **Propuesta**: no existe. ENTENDER tendría que combinar tres consultas |
| `contract_version` y política de versiones | **Propuesta**: no existe |
| Autenticación entre módulos (ENTENDER → DETECTAR) | **Pendiente de decisión del equipo.** Hoy solo existe el token administrativo, que no debe compartirse |
| País a nivel de tema | **No disponible**: solo por métrica |
| `confianza`, `saturacion`, `oportunidad` | **No disponibles** y no se calculan (RF-04 pendiente). La etapa `saturada` no se asigna |
| Notificaciones (webhook o cola) | **No existen**: solo consulta por petición |

**Limitaciones que afectan al contrato:**
- GDELT no está validada con la fuente real (`fuente_validada: false`);
- `stages-v1` no está calibrada (`calibrado: false`);
- el programador solo coordina dentro de un proceso.
