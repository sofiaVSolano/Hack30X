---
name: HACK 30X · Oficina de tendencias
description: Una oficina tecnológica de noche, en isométrico, donde cada puesto es un computador con la aplicación real.
colors:
  night: "#070d1c"
  surface: "#0c1630"
  surface-2: "#111e3f"
  surface-3: "#172850"
  line: "#1e2f5a"
  line-strong: "#2f467f"
  text: "#e8eefc"
  text-muted: "#a9b6d6"
  text-faint: "#8a99c0"
  electric: "#3d7bff"
  electric-text: "#7ea6ff"
  electric-fill: "#2f63e0"
  electric-fill-hover: "#2556c9"
  lime: "#c6f432"
  lime-ink: "#0b1400"
  ok: "#6fe0a0"
  warn: "#f5c060"
  danger: "#ff8f8f"
  simulated: "#c4a6ff"
  computer-night: "#050b18"
  computer-bar: "#070f22"
  computer-edge: "#22356b"
  scene-floor: "#0a1430"
  scene-wall: "#16254d"
  scene-desk: "#2b3d6d"
typography:
  display:
    fontFamily: "Geist Variable, Geist, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(42px, 5.6vw, 82px)"
    fontWeight: 650
    lineHeight: 1.02
    letterSpacing: "-0.04em"
  page-title:
    fontFamily: "Geist Variable, Geist, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(28px, 3.2vw, 40px)"
    fontWeight: 650
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  heading:
    fontFamily: "Geist Variable, Geist, Segoe UI, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.015em"
  body:
    fontFamily: "Geist Variable, Geist, Segoe UI, system-ui, sans-serif"
    fontSize: "15.5px"
    fontWeight: 400
    lineHeight: 1.55
  small:
    fontFamily: "Geist Variable, Geist, Segoe UI, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  data:
    fontFamily: "Geist Mono Variable, Geist Mono, Cascadia Code, ui-monospace, monospace"
    fontSize: "12.5px"
    fontWeight: 500
    lineHeight: 1.4
rounded:
  xs: "4px"
  sm: "6px"
  md: "10px"
  lg: "14px"
  frame: "16px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  xxl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.electric-fill}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    height: "38px"
  button-primary-hover:
    backgroundColor: "{colors.electric-fill-hover}"
  button-secondary:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    height: "36px"
  stage-acelerando:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.lime-ink}"
    rounded: "{rounded.pill}"
  stage-emergente:
    backgroundColor: "{colors.electric-fill}"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
  room-plaque:
    backgroundColor: "{colors.night}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
  computer-frame:
    backgroundColor: "{colors.computer-night}"
    textColor: "{colors.text}"
    rounded: "{rounded.frame}"
  computer-tab-active:
    textColor: "{colors.text}"
    height: "42px"
---

# Design System: HACK 30X · Oficina de tendencias

## Overview

HACK 30X es una oficina tecnológica de noche vista en isométrico. La portada presenta la idea en
una frase y una acción («Entrar a la oficina»); la oficina es el mapa del producto: salas por
módulo (DETECTAR, ENTENDER, CREAR, VALIDAR y la coordinación), puestos con computador y personas
solo donde un agente tiene tarea. Al elegir un puesto la cámara se acerca al monitor y la pantalla
se convierte en la aplicación real; «Volver a la oficina» deshace el camino.

Dos registros conviven: la oficina (exploración, ilustración geométrica exacta, luz ambiental azul)
y el computador (trabajo: el mismo azul noche, más profundo y técnico, con navegación contextual).

Regla que el diseño no puede romper: toda actividad visible sale de la API. Una persona teclea y
la luz lima se enciende solo con una ejecución pendiente o en curso registrada; un rol sin tarea es
una silla vacía; un módulo sin implementar se presenta «en preparación», sin resultados simulados.

## Colors

### Primary
- **Azul eléctrico** (`#3d7bff`): bordes de foco y selección, anillos de los puestos, subrayado de la
  pestaña activa, luz ambiental. Como texto se usa su variante clara `#7ea6ff` (≥ 4,5:1 sobre la
  noche); bajo texto blanco, la variante profunda `#2f63e0` (5,27:1).

### Secondary
- **Lima** (`#c6f432`): solo señales importantes: la etapa «acelerando» y la luz de actividad real
  de un puesto. Texto encima siempre `#0b1400`.

### Neutral
- **Azul noche** `#070d1c` de fondo; superficies `#0c1630`, `#111e3f`, `#172850`; líneas `#1e2f5a`,
  `#2f467f`. Texto `#e8eefc`, secundario `#a9b6d6`, terciario `#8a99c0`.
- Estados (sobre la noche, todos ≥ 4,5:1): correcto `#6fe0a0`, aviso `#f5c060`, error `#ff8f8f`,
  simulado `#c4a6ff`. Siempre con icono y texto.

### Named Rules
- **La regla de la señal lima.** El lima no decora: aparece solo cuando hay algo que anticipar
  (acelerando) o algo ocurriendo de verdad (ejecución en curso).
- **La regla del texto sobre azul.** Texto blanco solo sobre `#2f63e0` o más profundo; el `#3d7bff`
  lleno con texto blanco no llega a AA (3,84:1).

## Typography

Geist para todo y Geist Mono para cifras, identificadores, códigos de módulo y datos. Sin anchos
condensados: la jerarquía viene del tamaño, el peso (400 / 600 / 650) y el interletrado negativo
de los títulos (−0,03 a −0,04 em).

### Hierarchy
- Titular de la portada: clamp(42px, 5,6vw, 82px), 650, interlineado 1,02.
- Título de vista en el computador: clamp(28px, 3,2vw, 40px), 650.
- Encabezado de panel: 18px, 600.
- Texto: 15,5px/1,55; notas 13px. Nada por debajo de 11,5px (código de módulo en las placas).

## Layout

- **Portada:** dos columnas; la escena real de la oficina asoma por la derecha y se desvanece con
  una máscara (sin franjas de color). En móvil, texto arriba y escena debajo.
- **Oficina:** escenario a pantalla completa con cámara (traslación + escala calculadas desde las
  coordenadas de cada puesto). HUD arriba; placas de sala en el pasillo, la única franja sin
  muebles; al enfocar una sala, su panel se ancla a la izquierda de arriba abajo y la cámara
  encuadra la sala en el espacio restante. En móvil, la escena encabeza y la lista de puestos es la
  vía principal.
- **Computador:** marco fijo a 12px del borde (pantalla completa en móvil): barra con ubicación,
  modo de datos, sonido y «Volver a la oficina»; barra del módulo con sus secciones; contenido con
  desplazamiento propio y ancho máximo de 1360px.

## Elevation & Depth

La profundidad de la oficina es geométrica: cajas isométricas con tapa clara y cara derecha en
sombra, sin texturas ni ruido. En la interfaz, una sombra suave por elemento flotante (etiquetas,
panel, marco del computador) y nunca borde más sombra difusa en tarjetas.

### Named Rules
- **Nada encima de nada.** Placas, etiquetas y paneles no tapan muebles, puestos ni otras placas;
  se comprueba con la prueba de solapes en el navegador a 1280, 1440 y 1920 px.

## Shapes

Radios de 4, 6, 10 y 14px; 16px solo para el marco del computador; píldoras para etapas e
insignias. Las pantallas del mundo son paralelogramos isométricos exactos (pendiente ±0,5).

## Components

### Buttons
Primario azul profundo con texto blanco; secundario en superficie con borde. `:active` escala a
0,97; hover solo con puntero fino.

### Chips
Etapa como píldora: «Acelerando» lima, «Emergente» azul profundo, «Punto máximo» ámbar con borde,
«Datos insuficientes» solo con borde.

### Navigation
Ubicación en migas (HACK 30X › Oficina › Sala › Computador › Módulo); secciones del módulo como
pestañas con subrayado azul eléctrico.

### La oficina (componente propio)
Escena SVG isométrica con salas, muros con ventanas, mamparas bajas de vidrio y pantallas de pared.
Cada puesto es un botón con nombre y estado accesibles; al pasar o enfocar con teclado muestra su
etiqueta (estado real y «Ficha del agente»). Estados de pantalla: completada, fallida, bloqueada,
pendiente, en espera, desconocido (sin API), vacante y consulta.

### El computador (componente propio)
Coreografía de cámara por planos: acercamiento lento a un plano medio del puesto (2,2 s), pausa en
la que el monitor se enciende (0,5 s), empuje lento hacia la pantalla (1,6 s) y transición de vista
compartida (`<ViewTransition name="pantalla-computador">`, 1 s) en la que la pantalla se endereza y
crece hasta ser el computador mientras la interfaz pasa de borrosa a nítida. La salida es más corta
y sutil (1 s + pausa + 1,5 s). Clic o Enter saltan la secuencia; Escape la cancela. Cursor propio
solo dentro del computador y con puntero fino (flecha azul; flecha clara sobre controles; cursor de
texto nativo en los campos) con un halo que crece sobre controles y late al hacer clic.

## Do's and Don'ts

### Do:
- Mostrar solo estados, cifras y actividad que devuelve la API, y decir cuando no responde.
- Mantener la cámara y las transiciones en `transform`/`opacity` y respetar `prefers-reduced-motion`.
- Comprobar que nada se superpone tras cambiar la escena o las placas.

### Don't:
- No simular trabajo de agentes ni resultados de ENTENDER, CREAR o VALIDAR.
- No usar el lima como decoración ni texto blanco sobre `#3d7bff`.
- No poner etiquetas pequeñas sobre los titulares, degradados de texto ni efectos de neón o escaneo.
