# HACK 30X · DETECTAR y oficina de agentes

HACK 30X ayuda a creadores de contenido de Latinoamérica a encontrar tendencias **antes de que se
saturen**. El proyecto tiene cuatro módulos, en orden:

1. **DETECTAR:** encuentra los temas que están creciendo. **Está terminado (este repositorio).**
2. **ENTENDER:** analiza qué significan y si encajan con la audiencia.
3. **CREAR:** convierte la oportunidad en ideas de contenido.
4. **VALIDAR:** comprueba los resultados.

ENTENDER, CREAR y VALIDAR están a cargo de otras personas del equipo.

## Qué hace DETECTAR

Funciona como una cadena de cuatro pasos:

1. **Recoge señales** de tres fuentes públicas: Google Trends (lo que se busca), Wikipedia (lo que
   se lee) y GDELT (lo que publican los medios).
2. **Agrupa** todo lo que habla del mismo tema, aunque cada fuente lo escriba distinto.
3. **Mide** cada tema: cuántas visitas tiene, cuánto crece y si ese crecimiento se acelera.
4. **Clasifica** la etapa de cada tema:
   - **Emergente:** empieza a aparecer.
   - **Acelerando:** crece cada vez más rápido.
   - **Punto máximo:** subió y ahora se mantiene.
   - **Datos insuficientes:** no hay información para decidir, y explica por qué.

Dos reglas que se cumplen siempre:

- **No inventa números.** No da porcentajes de «confianza», «saturación» ni «oportunidad» que no
  pueda respaldar.
- **No mezcla datos reales con datos de prueba.** Cada dato es `real` o `simulated`.

## Los agentes

Son seis «trabajadores» automáticos. Dos ya trabajan de verdad:

- **Cazador de tendencias** (`trend_hunter`): ejecuta la cadena completa de arriba.
- **Supervisor** (`supervisor`): revisa y resume lo que han hecho los demás.

Los otros cuatro (Cazador de formatos, Analista, Filtro de audiencia y Estratega) están definidos
pero **aún no tienen tarea**: corresponden a otros módulos.

Hay además un **programador** que puede hacer que los agentes trabajen solos cada cierto tiempo.
Viene **apagado** por seguridad.

## La oficina de agentes

Es la página web que se abre en `http://127.0.0.1:3000`. La **portada** (`/`) presenta DETECTAR al
jurado como una guía de programación de TV impresa: la parrilla real del día (temas y etapa), las
reglas con sus umbrales reales, los seis agentes con su estado real y el botón «Abrir la oficina».
Solo lee datos reales; si no hay, lo dice. Dentro de la oficina están estas secciones:

| Sección | Qué se ve |
|---|---|
| **Tendencias** (`/tendencias`) | Lo más importante, en lenguaje simple: los temas que la gente busca hoy, agrupados por etapa («Creciendo cada vez más rápido», «Empezando a crecer», «En su punto más alto»), con sus visitas reales en Wikipedia y cuánto crecieron. Los temas sin etapa clara explican por qué (por ejemplo, «sus visitas están bajando») |
| **Oficina** (`/oficina`) | Un plano de oficina con salas y una personita en su escritorio por agente. Si un agente está trabajando de verdad, teclea, su pantalla se enciende y la luz «al aire» se pone roja; si no, descansa y su pantalla muestra el último resultado; un rol sin tarea aparece como silla vacía. Al hacer clic en una personita se abre su ficha: descripción, responsabilidad, fuentes, herramientas, frecuencia, preguntas abiertas e historial |
| **Agentes** | La ficha de cada agente |
| **Ejecuciones** | El historial de lo que ha hecho cada agente |
| **Programador** | Si el trabajo automático está encendido o apagado, y por qué |
| **Temas** | Los temas detectados |
| **Métricas** | Gráficas de cómo evoluciona cada tema |
| **Clasificaciones** | La etapa de cada tema y qué fuente la respalda |

## Tendencias reales

Con el backend en marcha, este comando trae las tendencias **reales** de hoy y calcula sus etapas:

```bash
npm run tendencias:actualizar
```

1. Recoge las tendencias de hoy de Google Trends en 8 países (Colombia, México, Argentina, Chile,
   Perú, Ecuador, Venezuela y Estados Unidos).
2. Busca el historial de visitas de esos temas en Wikipedia (últimos 45 días).
3. Calcula métricas y etapas con las reglas de siempre.

Conviene ejecutarlo una vez al día: con más días de Google Trends, las señales mejoran. Wikipedia
publica las visitas con un día de retraso, por eso las etapas se calculan con fecha de anteayer.
Las tendencias sin artículo en Wikipedia (por ejemplo, búsquedas como «clima hoy») aparecen en una
lista aparte, porque no hay historial para medirlas. GDELT (noticias) no se usa: la fuente está
fallando.

Para usarlo hay que tener activada Wikipedia en el archivo de configuración
(`DETECTAR_WIKIMEDIA_MODE=on` y `DETECTAR_HTTP_CONTACT=<correo de contacto>`).

## La demostración

Además existe un **conjunto de datos inventados de ejemplo** («Tema demo Alfa», «Tema demo
Beta»…) para enseñar la oficina sin conexión a internet.

- En **modo Simulado** se ven esos datos con todas las gráficas y etapas. Una franja morada avisa
  siempre de que son inventados.
- En **modo Real** se ve lo que trae `npm run tendencias:actualizar`.

El selector **Real / Simulado** está en el menú lateral de la oficina.

## Cómo levantarlo

Todos los comandos se ejecutan desde `frontend/oficina`.

**Primera vez:**

```bash
npm ci
npm run configurar          # guarda el token fuera de OneDrive; no lo muestra
npm run build
npm run demo:preparar       # crea la base de demostración en una carpeta temporal
```

El backend necesita además su entorno de Python en `backend/.venv`. Los pasos están en
[frontend/oficina/docs/guia-entrega.md](frontend/oficina/docs/guia-entrega.md).

**Cada vez, en dos terminales:**

```powershell
# Terminal 1: backend en http://127.0.0.1:8000 con los datos reales
npm run backend
# (o, solo para la demostración sintética:)
# $env:DETECTAR_DB_PATH = "$env:TEMP\hack30x-demo-simulada\detectar.db"; npm run backend

# Terminal 2: oficina en http://127.0.0.1:3000
npm start
```

Después, en una tercera terminal, `npm run tendencias:actualizar` y abrir `http://127.0.0.1:3000`
(portada) o directamente `http://127.0.0.1:3000/tendencias`.
Para detener cada servidor, pulsar `Ctrl+C` en su terminal.

- Para ver la demostración: arrancar el backend con `DETECTAR_DB_PATH` (comentado arriba) y abrir
  `http://127.0.0.1:3000/tendencias?modo=simulated` (la portada siempre muestra datos reales). Si la carpeta temporal se borró:
  `npm run demo:preparar -- --reiniciar`.

## Seguridad

- La oficina **solo funciona en el propio equipo**: no se puede abrir desde otra computadora.
- El token administrativo nunca llega al navegador y se guarda fuera de OneDrive.

## Lo que falta

No depende de DETECTAR, sino de decisiones del equipo:

- **Usuarios y contraseñas** en la oficina. Por eso todavía no se puede publicar en internet.
- **Conectar con ENTENDER:** acordar qué datos le pasa DETECTAR. Hay una propuesta en
  [contrato-detectar-v0-revision.md](backend/app/modules/detectar/docs/contrato-detectar-v0-revision.md).
- **Ajustar las reglas de etapas** con datos reales y **validar GDELT**.

## Más documentación

| Tema | Documento |
|---|---|
| Instalar, configurar, probar y demostración | [guia-entrega.md](frontend/oficina/docs/guia-entrega.md) |
| Estado final y riesgos | [cierre-detectar.md](frontend/oficina/docs/cierre-detectar.md) |
| Uso de la oficina | [frontend/oficina/README.md](frontend/oficina/README.md) |
| Métricas, etapas, programador y datos de demostración | [backend/app/modules/detectar/docs/](backend/app/modules/detectar/docs/) |
