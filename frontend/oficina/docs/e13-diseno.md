# E13: frontend de la oficina de agentes (solo lectura)

## 1. Punto de partida

- No había frontend en el repositorio (solo `backend/`). El `.gitignore` raíz ya preveía Node.
- Node 24.18 y npm 11.16 disponibles. No hay pnpm, yarn ni bun.
- Las skills disponibles relevantes para frontend son `svg-animations` (SVG accesible y
  `prefers-reduced-motion`) y `find-skills` (instala skills de forma global con `npx skills add -g`,
  cosa que E13 no autoriza). No hay herramientas de navegador conectadas a esta sesión.

## 2. Stack

| Decisión | Motivo |
|---|---|
| **Next.js 16 (App Router) + React 19 + TypeScript** | Un solo framework para la interfaz y el intermediario: las rutas de servidor (`route.ts`) guardan el token y el navegador nunca lo recibe |
| **CSS Modules + variables CSS** | Sistema visual propio sin depender de un framework de utilidades |
| **zod** | Esquemas que replican los modelos Pydantic reales; el intermediario rechaza respuestas inesperadas |
| **Gráficos en SVG propio** | Control exacto sobre huecos y días faltantes (una librería tiende a interpolar) |
| **lucide-react** | Iconografía coherente y accesible |
| **Space Grotesk + JetBrains Mono (`@fontsource`)** | Identidad tipográfica sin peticiones a Google en tiempo de ejecución |
| **Vitest + Testing Library + jsdom** | Pruebas de componentes y del intermediario |
| **playwright-core + axe-core** | Verificación visual con el Edge ya instalado; no se descargan navegadores |

Ubicación: `frontend/oficina/`. Si otros módulos crean su propio frontend, la carpeta deja espacio
para que convivan. Un frontend común único es una decisión del equipo.

## 3. Arquitectura

```
Navegador ──GET /api/oficina/...──► Rutas de servidor de Next (intermediario)
                                       │  lista cerrada de endpoints y parámetros
                                       │  Authorization: Bearer <token> (solo aquí)
                                       ▼
                                  DETECTAR /api/detectar/...
```

- `src/server/` lleva `import "server-only"`: si un componente del cliente lo importa, la compilación falla.
- `src/server/endpoints.ts` declara **cada** endpoint permitido: ruta de DETECTAR, parámetros
  admitidos con su validación y esquema de respuesta. No hay ruta comodín ni reenvío arbitrario.
  - Un parámetro desconocido o repetido produce un 400. La URL de destino se construye sobre la base
    configurada y se comprueba que el origen no cambia.
- Al backend solo se envían `Accept` y `Authorization`, con `redirect: "error"`, un tiempo de espera
  y un tamaño máximo de respuesta.
- La respuesta se valida con zod y se reserializa. Nunca se reenvían cabeceras del backend.
- Correspondencia de errores:

  | Situación | Respuesta del intermediario |
  |---|---|
  | 404 y 422 del backend | Se mantiene el texto de DETECTAR, que no repite la entrada |
  | 401 y 403 | 502 `intermediario_no_autorizado` |
  | 5xx o respuesta inválida | 502 |
  | Tiempo agotado | 504 |
  | Falta configuración | 503 |

  Nunca se muestran trazas ni el token.
- Solo existen manejadores `GET`. E13 no ejecuta agentes, no recolecta y no modifica datos.

## 4. Datos y honestidad

- **Modo de datos:** `real` o `simulated`, elegido en la URL (`?modo=`). Cada consulta usa uno
  solo. En modo simulado, una franja permanente lo indica.
- **Actividad:** se muestra únicamente el campo `actividad` de `/agentes` y las ejecuciones registradas.
  Solo hay movimiento (pulso discreto, desactivado con `prefers-reduced-motion`) cuando la API
  devuelve `pendiente` o `en_curso`.
- **Etapas:** no se recalculan ni se asignan en el cliente.
- **Campos que no existen:** no se muestran `saturacion`, `oportunidad` ni `confianza`. Solo se
  explica su ausencia.
- **`calibrado: false` y `fuente_validada: false`:** se muestran como advertencias con icono y texto.
- **Gráficos:** solo para una métrica (con una sola fuente y unidad), una serie por ámbito. Los puntos
  `insufficient` no se dibujan como valores. Los días no consecutivos cortan la línea y no se
  convierten en ceros. Con menos de dos puntos válidos no se dibuja ninguna serie.
- **Duraciones:** solo se calculan cuando existen `inicio` y `fin`.

## 5. Vistas

| Ruta | Contenido |
|---|---|
| `/` Oficina | Planta de seis estaciones, indicadores verificables, programador, últimas ejecuciones, clasificaciones y temas recientes, y limitaciones |
| `/agentes` | Fichas completas y panel lateral con el historial |
| `/ejecuciones` | Historial por agente con filtro de estado, orden y detalle estructurado |
| `/programador` | Estado operativo, plan con motivos de omisión y último tick |
| `/temas` | Búsqueda, paginación, ambigüedad, cola de revisión y detalle (alias, sujetos, vínculos) |
| `/metricas` | Catálogo de definiciones, explorador de valores y serie temporal |
| `/clasificaciones` | Reglas (provisionales), filtros y fichas con evidencias por fuente |

## 6. Actualización

- Botón manual en cada vista e indicador de "actualizado hace…".
- Sondeo moderado de 30 s en las vistas operativas (oficina, agentes y programador).
  - Se pausa con la pestaña oculta y se reanuda al volver.
  - Cancela las solicitudes obsoletas (`AbortController`) y no duplica las que siguen en curso.
- Si un refresco falla, se mantienen los últimos datos válidos y se avisa de que pueden estar
  desactualizados.

## 7. Fuera de alcance

- Ejecutar agentes, encender el programador, normalizar, corregir vínculos, alias o ambigüedad.
- La autenticación de usuarios de la oficina (sesión), pendiente de decisión del equipo. Mientras
  tanto, el servidor solo escucha en `127.0.0.1`.
