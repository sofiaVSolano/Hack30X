# DETECTAR: clasificación por etapas `stages-v1` (PROVISIONAL)

**Estado: reglas provisionales y NO calibradas.** Las etapas son hipótesis operativas; los
umbrales son valores iniciales elegidos a priori, sin datos reales que los respalden. Ningún
resultado de esta versión debe presentarse como calibrado ni como validado científicamente.

## 1. Entradas

Solo se usan métricas persistidas por E8 con todas estas condiciones:

- versión de métricas `metrics-v1`;
- el mismo `data_mode`;
- la misma `fecha_referencia` (`as_of`);
- `window_days` = 7.

Las métricas `insufficient` no aportan valores, solo motivos. Nunca se leen `raw_observations` ni
`topic_links` directamente, y la clasificación no los modifica.

## 2. Qué puede indicar cada fuente

| Fuente | Validada | Etapas que puede sostener | Métricas usadas | Qué NO puede indicar |
|---|---|---|---|---|
| Wikimedia (por artículo) | Sí | emergente, acelerando, punto_maximo | `wiki_views_growth`, `wiki_views_acceleration` (con `recent_growth` y `earlier_growth`) | interés social general, búsquedas, país, saturación |
| GDELT (por consulta) | **No** | las mismas, pero **solo como evidencia complementaria** | `gdelt_articles_growth`, `gdelt_articles_acceleration` | búsquedas, redes sociales, saturación; nunca es evidencia única |
| Google Trends RSS (por país) | Sí | solo **emergente** (aparición o aumento de presencia en capturas) | `gtr_presence_share_change` (con `current` y `previous`) | crecimiento de búsquedas, aceleración, máximo, saturación |

Las métricas de nivel o tamaño (`*_total`, `*_daily_mean`, `gtr_max_traffic_lower_bound`,
`gtr_presence_captures` y las de países) **no** se usan para inferir una etapa. Un nivel alto
no indica en qué fase está un tema.

## 3. Umbrales provisionales (`stages-v1`)

| Parámetro | Valor | Significado |
|---|---|---|
| `growth_min` | 0.20 | Crecimiento de la ventana actual frente a la anterior de al menos +20 % |
| `acceleration_min` | 0.10 | La tasa de crecimiento aumentó al menos 0.10 entre ventanas |
| `flat_band` | 0.10 | \|crecimiento\| < 0.10 se considera estable |
| `gtr_share_rise_min` | 0.30 | La presencia en capturas aumentó al menos 0.30 (30 puntos porcentuales) |
| `calibrated` | false | Ningún umbral está calibrado con datos reales |

## 4. Reglas por ámbito: Wikimedia y GDELT

En cada artículo o consulta, con `g` como crecimiento reciente, `a` como aceleración y `g_prev`
como crecimiento de la ventana anterior respecto de la previa. Se aplica la primera regla que
corresponda:

| # | Condición | Etapa propuesta |
|---|---|---|
| W0 | `g` insuficiente | sin señal (se registra el motivo de E8) |
| W1 | `g >= 0.20` y `a >= 0.10` | **acelerando** |
| W2 | `g >= 0.20` y `a` insuficiente | **emergente** (crece; la aceleración no se puede evaluar) |
| W3 | `g >= 0.20` y \|`a`\| < 0.10 | **emergente** (crece sin aceleración demostrada) |
| W4 | `g >= 0.20` y `a <= -0.10` | sin señal: crece pero desacelera; no se distingue de la cercanía a un máximo |
| W5 | \|`g`\| < 0.10 y `g_prev >= 0.20` | **punto_maximo** (subió en la ventana anterior y se estabilizó a un nivel superior al previo) |
| W6 | \|`g`\| < 0.10 sin `g_prev >= 0.20` (o `g_prev` insuficiente) | sin señal: estable sin aumento previo demostrado, o sin la historia necesaria para inferir un máximo |
| W7 | `g <= -0.10` | sin señal: el descenso no es una etapa definida en v1 |
| W8 | 0.10 <= `g` < 0.20 | sin señal: crecimiento moderado por debajo del umbral |

**Limitación de "punto_maximo":** con tres ventanas de 7 días solo se detecta una meseta
después de una subida. No se puede afirmar un máximo absoluto ni anticipar el descenso.

## 5. Reglas por ámbito: Google Trends (por país)

| # | Condición | Etapa propuesta |
|---|---|---|
| G0 | `gtr_presence_share_change` insuficiente | sin señal (por ejemplo, menos de 3 capturas por ventana) |
| G1 | `previous` = 0 y `current` > 0 | **emergente** (apareció en las capturas recientes) |
| G2 | cambio >= 0.30 | **emergente** (presencia en aumento) |
| G3 | otro caso | sin señal |

Google Trends nunca propone acelerando, punto_maximo ni saturada.

## 6. Combinación (sin puntuación agregada)

1. **Dentro de una fuente:** si los ámbitos con señal proponen etapas distintas, la fuente se
   declara contradictoria y no aporta etapa. Los ámbitos sin señal no contradicen.
2. **Fuentes primarias:** las validadas (Wikimedia y Google Trends). GDELT es **complementaria**.
3. **Etapa del tema:**
   - Sin etapa de ninguna fuente primaria: `datos_insuficientes`. Si solo GDELT tenía señal, el
     motivo es `solo_fuente_no_validada`.
   - Una sola etapa entre las primarias: esa etapa.
   - Varias etapas: el único par compatible es {emergente, acelerando}, que da **acelerando**
     (Google Trends solo informa la aparición, y Wikimedia aporta la evidencia temporal más
     específica). Cualquier otra combinación da `datos_insuficientes` con el motivo
     `senales_contradictorias`.
4. GDELT nunca cambia la etapa. Su coincidencia o discrepancia se registra como nota.

## 7. Saturada

**No se asigna en v1.** E8 no tiene ninguna métrica de oferta de contenido de creadores ni de
competencia. La cobertura de GDELT no es oferta de creadores y además no está validada. Una
popularidad alta (muchas visitas, mucho tráfico) no demuestra saturación. La etapa existe en el
modelo para versiones futuras.

## 8. Persistencia y reproducibilidad

- `rules_versions`: se registra `stages-v1` con sus parámetros y su sha256, igual que en E8.
  Es inmutable: si los parámetros cambian, se rechaza; hay que crear `stages-v2`.
- `trend_classifications`: un resultado por tema, fecha de referencia, versión de reglas,
  versión de métricas y huella de las métricas usadas.
  - **Misma huella:** no cambia nada (idempotente).
  - **Métricas recalculadas** (otra huella): se crea un resultado nuevo y el anterior queda como
    reemplazado (`superseded_at`). No se borra.
  - **Otra versión de reglas:** son filas independientes. Nunca se sobrescriben resultados de
    otra versión.
- `classification_evidence`: la contribución de cada fuente (primaria, complementaria o
  excluida), con la etapa propuesta, el motivo y las reglas que se cumplieron.
  - `source_validated` (`fuente_validada` en la API) es el estado de validación del conector de
    esa fuente. **Corrección del cierre:** antes, una fuente excluida *sin métricas* se guardaba
    con `false` aunque estuviera validada (p. ej. Wikimedia). Ahora toma el mismo valor que llevan
    sus métricas (`SOURCE_VALIDATED`). No cambia roles, etapas, umbrales ni la versión
    `stages-v1`. Las filas guardadas antes son inmutables y conservan el valor anterior.

## 9. Qué falta para calibrar

- Historial real de al menos varias semanas: hoy hay 1 captura de Google Trends y 3 días de
  Wikimedia.
- Casos de referencia etiquetados por personas, por ejemplo temas que fueron tendencia y cuándo
  alcanzaron su máximo, para estimar `growth_min`, `acceleration_min` y `flat_band`.
- La validación real de GDELT antes de darle cualquier peso.
- Una fuente de oferta de contenido (YouTube o Instagram autorizados) para definir "saturada".
