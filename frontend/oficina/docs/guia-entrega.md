# Guía de entrega: DETECTAR y su oficina de agentes

**Estado:** cierre funcional **local**. No está preparada para producción ni para acceso por red:
no hay autenticación de usuarios. Detalle en [cierre-detectar.md](cierre-detectar.md).

## 1. Requisitos

| Herramienta | Versión verificada |
|---|---|
| Windows 11 (Git Bash o PowerShell) | — |
| Python | 3.13 (`backend/.venv`; el proyecto admite 3.12 o superior) |
| Node.js y npm | Node 24.18 y npm 11.16 (`engines`: Node 22.12 o superior) |
| Microsoft Edge | Solo para la verificación visual automática (`playwright-core` usa el Edge instalado) |

No hace falta ninguna instalación global.

## 2. Instalación

```bash
# Backend (desde backend/)
python -m venv .venv
.venv/Scripts/python.exe -m pip install fastapi==0.139.0 uvicorn==0.49.0 pydantic==2.14.1 \
  pydantic-settings==2.14.2 httpx==0.28.1 sqlalchemy==2.0.51 defusedxml==0.7.1 \
  pytest==9.1.1 respx==0.23.1 ruff==0.17.1

# Oficina (desde frontend/oficina/)
npm ci
```

Las versiones del backend coinciden con las fijadas en `backend/pyproject.toml`; una prueba
comprueba que las instaladas son esas.

## 3. Configuración de secretos (fuera de OneDrive)

```bash
cd frontend/oficina
npm run configurar
```

- **Qué hace:** crea `%LOCALAPPDATA%\hack30x\oficina\oficina.env` con un token nuevo, que no se muestra en pantalla. Si el archivo ya existe, no lo toca.
- **Alternativas:** `OFICINA_CONFIG=<ruta absoluta>` (fuera de OneDrive y del repositorio) o variables de entorno del proceso.
- **No guarde el token en un `.env` del proyecto:** el lanzador se niega a arrancar si lo encuentra.

## 4. Ejecución local

```bash
# Terminal 1 (frontend/oficina/)
npm run backend        # DETECTAR en http://127.0.0.1:8000

# Terminal 2 (frontend/oficina/)
npm run build
npm start              # oficina en http://127.0.0.1:3000   (desarrollo: npm run dev)
```

- **Solo loopback:**
  - ambos servidores escuchan únicamente en `127.0.0.1`;
  - `next start` sin `--hostname` de loopback, o `next dev` sin el lanzador, se detienen al arrancar;
  - las solicitudes con un `Host` ajeno se rechazan (421).
- **Base de datos:** el backend usa `%LOCALAPPDATA%\hack30x\detectar\detectar.db`, salvo que `DETECTAR_DB_PATH` indique otra.
- **Programador:** está apagado por defecto. Para activarlo hacen falta las variables `DETECTAR_SCHEDULER_*`, descritas en `backend/app/modules/detectar/docs/e11-programador-periodico.md`.

## 5. Demostración con datos sintéticos (base aislada)

```bash
cd frontend/oficina
npm run build
npm run demo:preparar            # %TEMP%\hack30x-demo-simulada: carga y flujo real (añada -- --reiniciar para recrearla)
npm run demo:servir              # abra http://127.0.0.1:<puerto>/?modo=simulated ; Ctrl+C para terminar
npm run demo:limpiar             # borra solo la carpeta marcada de la demostración
```

- **El conjunto:** es `detectar_demo_sintetico@1.0.0`, con temas «Tema demo …» y valores inventados declarados como tales. Lo documenta `backend/app/modules/detectar/docs/datos-simulados.md`.
- **El flujo:** normalización, métricas y clasificación se ejecutan con los endpoints reales. Resultado: Alfa `acelerando`, Beta `punto_maximo` y tres temas con `datos_insuficientes` y su motivo.
- **En la oficina:** una franja permanente identifica el modo simulado y el conjunto sintético.

## 6. Pruebas

```bash
# Backend (desde backend/)
.venv/Scripts/python.exe -m pytest tests/detectar -q
.venv/Scripts/python.exe -m ruff check app/modules/detectar tests/detectar app/main.py

# Oficina (desde frontend/oficina/)
npm test
npm run typecheck
npm run verificar:bundle                       # token canario: no debe llegar a los archivos públicos
npm run demo:verificar -- --salida <carpeta>   # Edge: 7 vistas en real y simulado, en escritorio y móvil,
                                               # datos, accesibilidad (axe), teclado y recuperación
```

Resultados en la entrega:

| Prueba | Resultado |
|---|---|
| Backend | 812 pruebas aprobadas |
| Oficina | 173 pruebas aprobadas |
| Ruff y TypeScript | Sin errores |
| Bundle | Sin token |
| Verificación en Edge | Sin errores de consola, sin violaciones de axe y sin desbordamiento |

## 7. Documentación

| Tema | Documento |
|---|---|
| Diseño de la oficina | `docs/e13-diseno.md` y `docs/e15-diseno-visual.md` (skills de diseño aplicadas) |
| Seguridad del acceso | `docs/e14-seguridad-acceso.md` |
| Estado y riesgos | `docs/cierre-detectar.md` |
| Contrato con ENTENDER | `backend/app/modules/detectar/docs/contrato-detectar-v0-revision.md` (propuesta, con estado de implementación) |
| Métricas, etapas, programador y datos simulados | `backend/app/modules/detectar/docs/` |

## 8. Pendientes (decisiones del equipo)

- **Autenticación de usuarios de la oficina:** no existe; no exponer en red.
- **Integración con ENTENDER:** contrato sin acordar, sin autenticación entre módulos y sin endpoint de resumen.
- **GDELT:** sin validar con la fuente real.
- **`stages-v1`:** umbrales sin calibrar.
- **Programador:** coordinación solo dentro de un proceso; no usar varios workers.
