# DETECTAR: métricas `metrics-v1`

La fuente de verdad es el código (`metrics/definitions.py`). `GET /api/detectar/metricas/definiciones`
devuelve esta misma información, incluidos los parámetros exactos.

## Principios

- **Cada fuente por separado y en su propia unidad.** No existe ninguna puntuación combinada:
  visitas de Wikipedia, artículos de GDELT y capturas de Google Trends no se suman ni se comparan.
- **Ventanas de 7 días UTC cerrados.** La ventana actual termina en `fecha_referencia`
  (`as_of`), incluida; la anterior y la previa son las inmediatamente anteriores.
- **Un dato ausente no es cero.** Si falta un día, la métrica queda `insufficient`, con el
  motivo `missing_days:n`.
- **Las tasas exigen una base mínima.** Si no se alcanza, la métrica queda `insufficient` con
  `base_below_minimum`. Nunca hay divisiones por cero, infinitos ni porcentajes engañosos.
- **Diferencia no es tasa.** `*_abs_change` y `gtr_presence_share_change` son diferencias;
  `*_growth` es una tasa (fracción: 0.5 = +50 %); `*_acceleration` es una diferencia de tasas.
- Solo se usan vínculos de E7 **vigentes** y con estado `linked`, del mismo `data_mode`.

## Parámetros

| Parámetro | Valor |
|---|---|
| `window_days` | 7 |
| `gtr_min_known_captures` | 3 capturas conocidas del país por ventana |
| `wiki_min_base_views` | 70 visitas en la ventana base (10 por día) |
| `gdelt_min_base_articles` | 7 artículos en la ventana base (1 por día) |

## Métricas

| Métrica | Fuente | Unidad | Ámbito | Fórmula | Insuficiente cuando |
|---|---|---|---|---|---|
| `gtr_presence_captures` | Google Trends | captures | país | capturas con el tema | no hay capturas conocidas del país en la ventana |
| `gtr_presence_share` | Google Trends | ratio | país | capturas con el tema / capturas conocidas | < 3 capturas conocidas |
| `gtr_presence_share_change` | Google Trends | ratio_difference | país | share(actual) − share(anterior) | < 3 capturas en alguna ventana |
| `gtr_max_traffic_lower_bound` | Google Trends | searches_lower_bound | país | máximo de "200+" → 200 | ningún tráfico interpretable |
| `gtr_interest_countries` | Google Trends | countries | `*` | países con al menos una captura del tema | sin capturas conocidas en la ventana |
| `wiki_views_total` | Wikimedia | views | proyecto:Artículo | suma de 7 días | falta algún día |
| `wiki_views_daily_mean` | Wikimedia | views_per_day | proyecto:Artículo | total / 7 | falta algún día |
| `wiki_views_abs_change` | Wikimedia | views | proyecto:Artículo | total(actual) − total(anterior) | falta algún día |
| `wiki_views_growth` | Wikimedia | growth_rate | proyecto:Artículo | (actual − anterior) / anterior | falta algún día o anterior < 70 |
| `wiki_views_acceleration` | Wikimedia | growth_rate_difference | proyecto:Artículo | growth(reciente) − growth(previo) | 21 días incompletos o alguna base < 70 |
| `gdelt_articles_total` | GDELT | articles | consulta con filtros | suma de 7 días | falta algún día |
| `gdelt_articles_daily_mean` | GDELT | articles_per_day | consulta | total / 7 | falta algún día |
| `gdelt_articles_abs_change` | GDELT | articles | consulta | diferencia | falta algún día |
| `gdelt_articles_growth` | GDELT | growth_rate | consulta | tasa | falta algún día o anterior < 7 |
| `gdelt_articles_acceleration` | GDELT | growth_rate_difference | consulta | diferencia de tasas | 21 días incompletos o alguna base < 7 |
| `gdelt_publisher_countries` | GDELT | countries | `*` | países del MEDIO con artículos > 0 | ninguna consulta filtrada por país del medio |

## Lo que cada fuente NO es

- **Google Trends RSS:** son capturas puntuales de unas 10 tendencias por país. **No** es una
  serie de volumen de búsquedas. Las "capturas conocidas" son los instantes con al menos una
  tendencia guardada para el país; las capturas vacías o fallidas no cuentan. No se calcula
  crecimiento de búsquedas.
- **Wikimedia:** son visitas de personas a Wikipedia, **no** búsquedas. La edición (`es`) no
  indica el país de los lectores, por eso no tiene métrica regional.
- **GDELT:** es cobertura periodística, **no** búsquedas ni redes sociales. El país es el del
  medio y solo existe cuando la consulta se filtró por él.

## Regiones: tres significados distintos

| Dimensión | Fuente | Significado |
|---|---|---|
| País de interés | Google Trends (`reported_by_source`) | El tema estaba en tendencia en ese país según Google |
| País del medio | GDELT (`publisher_country`) | Medios de ese país publicaron artículos |
| (ninguna) | Wikimedia | No se atribuye país |

## Estado de validación real (17/10/2026)

| Fuente | Validación real | `source_validated` |
|---|---|---|
| Google Trends RSS | Hecha (extremo a extremo) | `true` |
| Wikimedia | Hecha (extremo a extremo) | `true` |
| GDELT | **Pendiente**: tiempo de espera agotado en las consultas reales, incluso con 60 s | `false` |

Las métricas de GDELT se calculan con las observaciones guardadas, pero se marcan
`source_validated=false` hasta validar el conector.

## Persistencia

- `rules_versions`: los parámetros exactos de cada versión, inmutables. Si una versión ya
  existe con otros parámetros, el cálculo se rechaza.
- `metric_values`: una fila por tema, fuente, ámbito, métrica, periodo y versión. Recalcular
  actualiza la misma fila (idempotente). Cada fila guarda el estado, el motivo, los ids de
  las observaciones usadas (hasta 500, más el total) y los detalles. SQLite rechaza valores
  no finitos, estados incoherentes y modos mezclados.
