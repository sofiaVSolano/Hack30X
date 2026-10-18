# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Oficina (aplicación):** quien opera DETECTAR en HACK 30X. Revisa qué temas están creciendo y
  en qué etapa están, para pasarlos al siguiente módulo (ENTENDER). La persona usuaria encontró la
  primera versión poco intuitiva: necesita entender el resultado de un vistazo, en lenguaje simple.
- **Portada:** el **jurado / evaluadores de HACK 30X** y quien llega por primera vez. Necesitan
  entender la propuesta en una frase y entrar a la oficina; sin indicadores operativos antes de entrar.
- **Oficina inmersiva:** se recorre como un espacio (salas por módulo, puestos con computador) y cada
  computador abre la aplicación real de su módulo.

## Product Purpose

HACK 30X ayuda a creadores de contenido de Latinoamérica a encontrar tendencias **antes de que se
saturen**. DETECTAR es el primer módulo (DETECTAR → ENTENDER → CREAR → VALIDAR): recoge señales
públicas, agrupa lo que habla del mismo tema, mide su evolución y clasifica la etapa de cada tema
(emergente, acelerando, punto máximo, datos insuficientes). Éxito: que alguien vea en segundos qué
temas reales están creciendo y por qué, sin tener que interpretar jerga técnica.

## Positioning

Clasificación por etapa basada en evidencia verificable y con sus límites a la vista: cada etapa
muestra de qué fuente sale, qué regla se aplicó y por qué un tema no tiene señal clara. No inventa
puntuaciones de confianza, saturación ni oportunidad.

## Operating Context

- Uso exclusivamente local (`127.0.0.1`); sin autenticación de usuarios todavía.
- Actualización diaria con `npm run tendencias:actualizar`: Google Trends (tendencias de hoy en
  8 países: CO, MX, AR, CL, PE, EC, VE, US) + Wikipedia (45 días de visitas). Wikipedia publica con un
  día de retraso, por eso las etapas tienen fecha de anteayer.
- Modo `simulated` con un conjunto sintético de demostración, siempre identificado como tal.
- Agentes de la oficina: `trend_hunter` y `supervisor` implementados; otros cuatro roles definidos
  sin tarea.

## Capabilities and Constraints

- Next.js 16 + React 19 + TypeScript, CSS Modules, sin biblioteca de componentes. Backend FastAPI
  (solo lectura desde la oficina, a través de un intermediario de servidor).
- Datos reales y simulados nunca se mezclan. Valores ausentes no son cero. GDELT no está validada
  y no se usa en la actualización diaria. Reglas `stages-v1` sin calibrar.
- La etapa indica el momento del tema, no si conviene: eso lo decide ENTENDER (sin integrar).
- Idioma de la interfaz: español.

## Brand Commitments

- Nombre: **HACK 30X**. Módulo: **DETECTAR**. Concepto: «oficina de agentes» en isométrico, de noche;
  azul noche, azul eléctrico para lo interactivo y lima solo para señales importantes (fijado por la
  persona usuaria en E16).

## Evidence on Hand

- Tendencias reales clasificadas en la base local (`%LOCALAPPDATA%\hack30x\detectar\detectar.db`),
  leídas por la API. Varían cada día.
- Conjunto sintético `detectar_demo_sintetico@1.0.0`.
- **No existen** y no deben inventarse: testimonios, clientes, métricas de uso, precios, logos de
  terceros ni resultados de negocio.

## Product Principles

1. Primero el resultado en lenguaje simple; el detalle técnico, a un clic.
2. Toda cifra es real y trazable a la API; si falta, se dice por qué.
3. La actividad de los agentes solo se muestra cuando ocurre de verdad.
4. Honestidad sobre los límites (sin calibrar, sin validar, sin saturación) a la vista, sin alarmismo.

## Accessibility & Inclusion

WCAG 2.1 AA (verificado con axe en E13–E15), navegación por teclado, `prefers-reduced-motion`
respetado, escritorio y móvil.
