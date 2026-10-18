# E16 · Oficina inmersiva: portada, oficina isométrica y computadores

Rediseño de la experiencia de HACK 30X: una portada mínima, una oficina tecnológica de noche en
isométrico y computadores que abren la aplicación real. El backend, los contratos y las reglas de
negocio no cambian.

## Recorrido

1. **Portada** (`/`): logotipo, «Las tendencias no esperan. Anticípate.», una frase y «Entrar a la
   oficina». La ilustración es la escena real de la oficina en modo real (sin cifras ni indicadores).
2. **Oficina** (`/oficina`): cinco salas (DETECTAR, ENTENDER, CREAR, VALIDAR y Centro de agentes),
   doce puestos con computador. Pasar por una sala la resalta; su placa (en el pasillo) o su suelo
   la encuadran y abren el panel de la sala.
3. **Entrar** (coreografía de cámara por planos, `SHOT` en `OfficeWorld.tsx`):
   - acercamiento lento a un plano medio del puesto: 2,2 s;
   - pausa: el monitor se enciende dentro de la escena: 0,5 s;
   - empuje lento hacia la pantalla: 1,6 s;
   - la ruta del computador se abre con el tipo de transición `entrar-computador`.
   Un clic o Enter salta la secuencia; Escape la cancela; con movimiento reducido no hay acercamiento.
4. **Computador**: el monitor se endereza y crece hasta ser el marco del computador (transición de
   vista compartida, 1 s) mientras la interfaz pasa de borrosa a nítida; cambia el cursor y aparece la
   navegación del módulo. Dentro funcionan las vistas
   reales de siempre.
5. **Volver**: «Volver a la oficina» o Escape (salvo escribiendo o con un diálogo abierto) usa el
   tipo `salir-computador`; la pantalla vuelve al monitor, la cámara se aleja, el puesto queda
   marcado y recupera el foco.

## Arquitectura

- `src/app/(oficina)/layout.tsx` monta `OfficeWorld`, **persistente** entre rutas: la escena no se
  desmonta y cada ruta existente es un computador. Los enlaces, el historial del navegador y los
  enlaces directos siguen funcionando.
- Puestos y rutas (`src/components/office/scene.ts`):

| Puesto | Sala | Ruta del computador |
|---|---|---|
| Cazador de tendencias (`trend_hunter`) | DETECTAR | `/tendencias` |
| Pantallas de pared: temas, métricas, clasificaciones | DETECTAR | `/temas`, `/metricas`, `/clasificaciones` |
| Cazador de formatos, Analista, Filtro de audiencia, Estratega | DETECTAR / ENTENDER / CREAR | `/puesto/<id>` |
| Supervisor | Centro de agentes | `/coordinacion` (pestañas Ejecuciones, Agentes, Programador) |
| Pantallas de pared: ejecuciones, programador | Centro de agentes | `/ejecuciones`, `/programador` |
| Puesto de validación (sin agente) | VALIDAR | `/validar` |

- **Cámara**: una sola transformación (`translate` + `scale`) sobre el mundo, calculada desde las
  coordenadas de la pantalla de cada puesto (`cameraFor`), así que vale para cualquier puesto,
  resolución y proporción. Escala máxima 6 para no rasterizar capas enormes.
- **Monitor → computador**: `<ViewTransition name="pantalla-computador" share="pantalla">` en la
  pantalla del puesto enfocado y en el marco del computador; solo uno está montado a la vez. La
  pantalla de origen se dibuja en coordenadas de pantalla (fuera del mundo escalado): así la
  transición no interpola la escala de la cámara ni captura una capa enorme. La
  raíz no se funde (receta «live root»). Las pestañas del computador usan el tipo `pestana`.
- **Datos**: `useAgents` y `useScheduler` (los mismos intermediarios de siempre). Sin datos de la
  API, los puestos aparecen como «Estado no disponible» y no se dibuja a nadie.
- **Cursor**: solo dentro del computador y con puntero fino: flecha propia (SVG en CSS), flecha
  clara sobre controles, cursor de texto nativo en los campos y un halo que se mueve escribiendo
  `transform` en el elemento (sin estado de React por fotograma). Sin halo en táctil ni con
  movimiento reducido. Al volver se desmonta y la oficina recupera el cursor normal.
- **Sonido**: dos tonos de Web Audio (sin archivos ni dependencias), apagado por defecto; la
  preferencia se guarda solo en el navegador.

## Skills

- Para el ritmo de la cámara (E16, segunda pasada) se buscaron con `find-skills` skills de cámara y
  movimiento: `design-motion-principles` (kylezantos, 12 K) se instaló en el proyecto y fija el ritmo
  por contexto (momento poco frecuente e inmersivo: lentes de Jakub y Jhey, salida más sutil que la
  entrada, nada de rebote, zoom grande solo sin movimiento reducido). `cinematic-camera`
  (liamrjohnston) se leyó pero no se instaló (está pensada para vídeos de Remotion); de ella se tomó
  el modelo de cámara por planos con pausas.

- Encontradas con `find-skills` (`npx skills find`): `vercel-labs/agent-skills@vercel-react-view-transitions`
  (156 K instalaciones), `emilkowalski/skills@animation-performance`, `devmartinese/awwwards-animations`,
  `bergside/awesome-design-skills@immersive` / `perspective`, entre otras.
- Instaladas **en el proyecto** (`frontend/oficina/.claude/skills`, `skills-lock.json`), tras revisar
  que solo contienen documentación: `vercel-react-view-transitions` (principal) y
  `animation-performance`. Descartada `awwwards-animations`: exige GSAP y sustituye el cursor entero.
- Ya instaladas y usadas: `impeccable` (mundo fijado por el encargo, suelo de calidad, detector,
  documentación), `emil-design-eng` (curvas, pulsación, hover con puntero fino).

## Dependencias

- Añadidas: `@fontsource-variable/geist` y `@fontsource-variable/geist-mono` 5.3.0 (fuentes locales,
  licencia OFL). Retiradas: Archivo y JetBrains Mono. Ninguna biblioteca de animación ni de 3D.

## Verificación

- Pruebas: escena y cámara (`tests/ui/scene.test.tsx`), recorrido completo
  (`tests/ui/office-world.test.tsx`), portada, puestos y VALIDAR, separación de modos.
- Edge (`scripts/verificar-visual.mjs`): axe, teclado, consola y desbordamiento en todas las rutas,
  escritorio y móvil.
- Solapes: placas, etiquetas y paneles comprobados contra muebles y puestos a 1280, 1440 y 1920 px.

## Límites

- ENTENDER, CREAR y VALIDAR no existen como módulos: sus salas no tienen herramientas.
- Sin autenticación de usuarios: uso local únicamente; no está listo para producción.
- Las transiciones de vista necesitan Chromium 125+, Safari 18.2+ o Firefox 144+; en otros
  navegadores la navegación funciona sin animación.
