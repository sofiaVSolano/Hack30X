---
name: HACK 30X · DETECTAR
description: La programación de tendencias del día, impresa como una guía de TV latinoamericana.
colors:
  paper: "#f1ecdf"
  paper-raised: "#f8f4ea"
  paper-2: "#e9e2d2"
  paper-3: "#ded5c2"
  rule: "#d3c9b4"
  rule-strong: "#b5a98f"
  ink: "#16130f"
  ink-muted: "#4a443a"
  ink-faint: "#635b4e"
  wall: "#2a2620"
  signal-red: "#d21f2b"
  channel-blue: "#1f56b3"
  channel-yellow: "#f2c230"
  ok: "#136136"
  warn: "#6f4500"
  danger: "#b3261e"
  simulated: "#6a3fa3"
typography:
  display:
    fontFamily: "Archivo Variable, Archivo, system-ui, sans-serif"
    fontSize: "clamp(76px, 15.5vw, 236px)"
    fontWeight: 850
    lineHeight: 0.8
    letterSpacing: "-0.01em"
  section:
    fontFamily: "Archivo Variable, Archivo, system-ui, sans-serif"
    fontSize: "clamp(48px, 6.4vw, 104px)"
    fontWeight: 850
    lineHeight: 0.9
  page-title:
    fontFamily: "Archivo Variable, Archivo, system-ui, sans-serif"
    fontSize: "clamp(34px, 4.4vw, 54px)"
    fontWeight: 800
    lineHeight: 1
  heading:
    fontFamily: "Archivo Variable, Archivo, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 800
    lineHeight: 1.1
  body:
    fontFamily: "Archivo Variable, Archivo, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.5
  small:
    fontFamily: "Archivo Variable, Archivo, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.4
  code:
    fontFamily: "JetBrains Mono Variable, ui-monospace, monospace"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  sm: "4px"
  md: "8px"
  lg: "12px"
spacing:
  tile-gap: "8px"
  row-gap: "4px"
  gutter: "clamp(16px, 2.4vw, 32px)"
components:
  button-primary:
    backgroundColor: "{colors.signal-red}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
  button-ink:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
    height: "56px"
  channel-acelerando:
    backgroundColor: "{colors.signal-red}"
    textColor: "#ffffff"
    rounded: "2px"
  channel-emergente:
    backgroundColor: "{colors.channel-blue}"
    textColor: "#ffffff"
    rounded: "2px"
  channel-punto-maximo:
    backgroundColor: "{colors.channel-yellow}"
    textColor: "{colors.ink}"
    rounded: "2px"
  nav-item-active:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
  board-row:
    backgroundColor: "{colors.wall}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
    height: "72px"
  board-row-open:
    backgroundColor: "{colors.signal-red}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
---

# Design System: HACK 30X · DETECTAR

## Overview

La guía de programación impresa. DETECTAR publica cada día qué temas crecen en América Latina y en
qué momento está cada uno; el sistema lo trata como la parrilla de una revista de TV: papel, tinta,
un rojo propio, y el azul y el amarillo solo como insignias de canal. La fila elegida se invierte
(papel↔tinta, o rojo en la parrilla) igual que el programa que está «en emisión».

Dos modos conviven. La **portada** (`/`) persuade al jurado: bandas de color llenas, el nombre
enorme, la parrilla real del día, capturas reales de la oficina. La **oficina** (`/tendencias`,
`/oficina` y el resto) opera: misma tinta y papel, más contenida, densa y escaneable; la marca vive
en los detalles (insignias de canal, ítem activo invertido, títulos condensados).

Regla de honestidad que el diseño no puede romper: todo número, etapa, umbral o estado de agente que
se ve sale de la API. Las animaciones de actividad solo reflejan estados reales.

## Colors

### Primary
- **Rojo señal** (`#d21f2b`): banda del nombre, acción principal, fila abierta de la parrilla, canal
  «Acelerando», luz «al aire» de un agente que trabaja. Texto encima siempre en blanco (5,29:1); el
  papel encima no llega a AA (4,48:1).

### Secondary
- **Azul canal** (`#1f56b3`) y **amarillo canal** (`#f2c230`): solo insignias de etapa («Emergente»,
  «Punto máximo») y baldosas de color de la portada. Nunca texto corrido ni fondos de página.

### Neutral
- **Papel** (`#f1ecdf`) fondo; **papel 2/3** (`#e9e2d2`, `#ded5c2`) baldosas y paneles;
  **tinta** (`#16130f`) texto y bloques invertidos; **pared** (`#2a2620`) filas de la parrilla y
  pictogramas.

### Named Rules
- **La regla del canal.** El color de etapa es una insignia llena con su nombre, nunca un punto ni un
  borde de color suelto.
- **La regla de la fila en emisión.** Lo seleccionado se invierte; no se resalta con sombra ni con
  un tono intermedio.

## Typography

Una sola familia, Archivo Variable (Omnibus-Type, Buenos Aires), con su eje de anchura: condensada al
62 % para el nombre y los títulos de sección, al 82 % para títulos y etiquetas, normal para el texto.
JetBrains Mono solo para identificadores y código.

### Hierarchy
- Display (nombre, palabra gigante): condensada 62 %, 850, interlineado 0,8.
- Sección: condensada 62 %, 850, clamp(48px, 6,4vw, 104px).
- Título de página de la oficina: condensada, 800, clamp(34px, 4,4vw, 54px).
- Encabezado: condensada 82 %, 800, 22px.
- Texto: 18px/1,5 en la portada; 16px en tablas de la oficina. Nada por debajo de 13px.

## Layout

Portada: rejilla de 12 columnas con separaciones de 8px entre baldosas llenas («el tablero bien
llevado»); hero de raíles (datos a la izquierda, captura con su frase en el centro, cifras en vivo a
la derecha y la baldosa roja de acción). En teléfono pasa a dos columnas con su propia composición.
Oficina: barra lateral fija con el ítem activo invertido, contenido en paneles sobre papel.

## Elevation & Depth

Plano. Sin sombras en reposo y sin degradados: la profundidad viene de bloques de color llenos y de
la inversión. El diálogo lateral se separa con un velo desenfocado sobre la página.

## Shapes

Un solo radio: 4px en baldosas y botones (8px y 12px solo en paneles de la oficina). Las insignias de
canal usan 2px, como un recuadro impreso.

## Components

### Buttons
Primario rojo con texto blanco; de tinta con texto papel. `:active` escala a 0,97; el hover solo
existe con puntero fino.

### Chips
Insignias de canal (`.channel[data-stage]`): rojo «Acelerando», azul «Emergente», amarillo «Punto
máximo»; «Datos insuficientes» y «Saturada» solo con contorno.

### Navigation
Barra lateral de la oficina con marca roja; el ítem activo es un bloque de tinta con texto papel.

### La parrilla (componente propio)
Filas de 72px sobre tinta con 4px entre ellas; la fila abierta pasa a rojo, crece y muestra la frase
de su etapa, de dónde viene el tema y «Ver la evidencia». Un clic abre otra fila.

### La personita (componente propio)
Pictograma de tinta de una persona en su escritorio, uno por agente. Teclea y enciende la luz «al
aire» solo si la API dice que tiene una ejecución pendiente o en curso; si no, descansa y su pantalla
muestra el último resultado; un rol sin tarea es una silla vacía con contorno discontinuo. Al hacer
clic se abre la ficha del agente.

## Do's and Don'ts

### Do:
- Mostrar solo cifras, etapas, umbrales y estados que devuelve la API, y decir cuando faltan.
- Usar las capturas reales de la oficina como imágenes de la portada.
- Entrar con movimiento solo con transform/opacity y respetar `prefers-reduced-motion`.

### Don't:
- No animar actividad que la API no registra.
- No usar degradados, sombras en reposo, vidrio ni etiquetas diminutas en mayúsculas sobre títulos.
- No poner texto papel sobre rojo (4,48:1): en rojo, el texto es blanco.
- No numerar filas ni secciones (01, 02…).
