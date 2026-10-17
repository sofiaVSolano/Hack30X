# E15: plan visual de la oficina (aplicando skills de diseño)

## 1. Skills utilizadas

| Skill | Cómo se encontró | Para qué se usa |
|---|---|---|
| **`anthropics/skills@frontend-design`** (principal) | `find-skills`: la clasificación de skills.sh y `npx skills find "dashboard ui"`, donde aparece primera (~998 K instalaciones, oficial) | Dirección visual, plan de tokens, tipografía, uso del movimiento y autocrítica con capturas |
| `vercel-labs/agent-skills@web-design-guidelines` | Clasificación de skills.sh (~750 K, Vercel). Sus reglas se descargaron de `vercel-labs/web-interface-guidelines/command.md` | Auditoría de accesibilidad, foco, animación, tipografía, formularios y temas oscuros |
| `anthropics/knowledge-work-plugins@data-visualization` | `npx skills find "data visualization"` (13 K, oficial) | Gráfica de métricas: ejes con unidades, rótulos directos, fuente y periodo, y no depender solo del color |
| `svg-animations` (local, `~/.claude/skills`) | Ya disponible | Ilustración SVG de los puestos y animación accesible |

Las instrucciones se descargaron y se leyeron completas, sin instalar nada (`npx skills add -g`
habría modificado la configuración global).

## 2. Encargo

La oficina debe **verse como una oficina en la que trabajan los agentes**, sin simular actividad
(regla de E13). Por tanto:

- cada agente tiene un **puesto** en una planta;
- la **pantalla y la postura** del agente solo indican trabajo cuando la API devuelve `pendiente` o
  `en_curso`;
- el resto del tiempo el puesto muestra su estado real: último resultado (`completada`,
  `fallida`, `bloqueada`), sin ejecuciones o **puesto sin tarea** (rol planificado: silla vacía y
  pantalla apagada).

## 3. Revisión frente a los patrones genéricos que señala `frontend-design`

| Patrón genérico detectado en E13/E14 | Decisión |
|---|---|
| Casi negro con un único acento ácido | Pasamos a un azul de plano nocturno (`#0F1A26`). El lima se conserva como señal de HACK 30X, más suave, y **solo** para lo activo, lo seleccionado o lo implementado |
| Etiquetas en mayúsculas con espaciado sobre cada título | Se eliminan; la ubicación ya la da la navegación |
| Metadatos unidos con «·» | Se sustituyen por frases o pares etiqueta/valor |
| Monoespaciada para etiquetas pequeñas | Solo para identificadores reales (`trend_hunter`, `tpc_…`), con `translate="no"`; las cifras usan `tabular-nums` |
| Todo en tarjetas iguales | Hay jerarquía: la planta es la pieza protagonista (plano arquitectónico con salas y muros) y los paneles secundarios son más sobrios |
| Indicadores grandes con etiqueta pequeña | Los conteos se convierten en la **leyenda de la planta**: cada cifra explica un estado visible de los puestos |

## 4. Tokens

- **Color:**

  | Nombre | Hex | Uso |
  |---|---|---|
  | Noche de plano | `#0F1A26` | Fondo |
  | Plano | `#152434` | Superficie |
  | Muro | `#2C4157` | Líneas de plano |
  | Tinta | `#E6EDF4` | Texto |
  | Señal | `#B6E36B` | Lima de HACK 30X, para lo activo |
  | Lámpara | `#F2B35E` | Luz cálida de los puestos activos |

  Los estados conservan sus tonos, ajustados para mantener el contraste AA.
- **Tipografía:** Space Grotesk (identidad existente) para títulos y texto, con la escala
  13 / 15 / 18 / 24 / 34. JetBrains Mono solo para identificadores. Los títulos usan
  `text-wrap: balance`.
- **Composición:** a la izquierda la planta, con las salas por módulo según `alcance` de la API
  (DETECTAR, ENTENDER, CREAR y coordinación transversal). Debajo, un pasillo con la mesa del
  coordinador y el reloj del programador, que muestra el estado real de `/agentes/programador`.
  Texto alineado a la izquierda.

```
┌ Planta ───────────────────────────────────────────────────────────┐
│ ┌ Sala DETECTAR ───────┐ ┌ Sala ENTENDER ──────┐ ┌ Coordinación ─┐ │
│ │ [puesto] [puesto]    │ │ [puesto] [puesto]   │ │ [puesto]      │ │
│ └────────── ▯ ─────────┘ └────────── ▯ ────────┘ └────── ▯ ──────┘ │
│ ┌ Sala CREAR ──────────┐   pasillo: mesa del coordinador · reloj   │
│ │ [puesto]             │                                          │
│ └────────── ▯ ─────────┘                                          │
└───────────────────────────────────────────────────────────────────┘
```

- **Principios:**
  - la audacia se concentra en la planta; lo demás queda sobrio;
  - todo movimiento procede de la API (`pendiente` o `en_curso`) o responde a una acción del
    usuario, y desaparece con `prefers-reduced-motion`;
  - el estado nunca depende solo del color: siempre lleva icono, texto y dibujo de pantalla.
