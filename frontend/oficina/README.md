# Oficina de agentes · HACK 30X

Interfaz de **solo lectura y de uso exclusivamente local** de la oficina de agentes de DETECTAR. El
navegador habla solo con el intermediario de esta aplicación (`/api/oficina/...`), que es el único
que conoce `DETECTAR_ADMIN_TOKEN`.

**No está lista para exponerse en red ni para producción:** no hay autenticación de usuarios (es una
decisión pendiente del equipo).

Documentación:
- **guía de entrega (instalar, configurar, ejecutar, probar y demostración):** [docs/guia-entrega.md](docs/guia-entrega.md);
- diseño: [docs/e13-diseno.md](docs/e13-diseno.md) y [docs/e15-diseno-visual.md](docs/e15-diseno-visual.md) (oficina como planta con puestos; skills de diseño aplicadas);
- seguridad: [docs/e14-seguridad-acceso.md](docs/e14-seguridad-acceso.md);
- estado final: [docs/cierre-detectar.md](docs/cierre-detectar.md).

## 1. Secretos fuera de OneDrive (una sola vez)

```bash
cd frontend/oficina
npm ci
npm run configurar
```

`configurar` crea `%LOCALAPPDATA%\hack30x\oficina\oficina.env`, fuera del repositorio y de OneDrive, con
un token nuevo que **no se muestra**. Si el archivo ya existe, no lo modifica.

- **Otra ubicación:** defina `OFICINA_CONFIG` con una ruta absoluta (también fuera de OneDrive y del repositorio).
- **Sin archivo:** defina `DETECTAR_ADMIN_TOKEN` y `OFICINA_DETECTAR_URL` como variables de entorno del proceso; tienen prioridad sobre el archivo.
- **No use `.env.local` en este proyecto:** si contiene el token, el lanzador se niega a arrancar. No lo mueve ni lo borra: debe hacerlo usted.

## 2. Arranque (dos terminales)

```bash
npm run backend      # DETECTAR en http://127.0.0.1:8000 (uvicorn, solo loopback)
npm run build        # una vez, o tras cambios
npm start            # oficina en http://127.0.0.1:3000 (o: npm run dev)
```

- **Mismo token:** ambos procesos leen el token del mismo archivo.
- **Base de datos:** el backend usa su base por defecto (`%LOCALAPPDATA%\hack30x\detectar\detectar.db`) salvo que el archivo o el entorno definan `DETECTAR_DB_PATH`.
- **Puertos:** se cambian con `DETECTAR_PUERTO` y `OFICINA_PUERTO`.

## 3. Demostración con datos sintéticos (base temporal aislada)

```bash
npm run build
npm run demo:preparar    # carpeta %TEMP%\hack30x-demo-simulada: carga el conjunto y ejecuta el flujo real
npm run demo:servir      # abre http://127.0.0.1:<puerto>/?modo=simulated (Ctrl+C para terminar)
npm run demo:verificar -- --salida C:\ruta\capturas    # comprobaciones automáticas con Edge
npm run demo:limpiar     # borra solo la carpeta marcada de la demostración
```

Para recrearla desde cero: `npm run demo:preparar -- --reiniciar`. Sin ese parámetro, el
procedimiento se niega a reutilizar una demostración existente.

## 4. Comandos

| Comando | Qué hace |
|---|---|
| `npm test` | Pruebas (Vitest): intermediario, acceso local, configuración, seguridad estática, series, vistas y procedimiento de demostración |
| `npm run typecheck` | Comprobación de tipos |
| `npm run verificar:bundle` | Compila con un token canario y comprueba que no llega a los archivos públicos |
| `npm run verificar:visual` | Capturas, consola, axe-core, teclado y movimiento reducido con el Edge instalado |

## 5. Protecciones de acceso local

- **Arranque:**
  - `npm run dev` y `npm start` siempre usan `127.0.0.1`.
  - `next start` con otro host, o sin `--hostname`, y `next dev` lanzado sin el lanzador se detienen al arrancar (`src/instrumentation.ts`).
- **`src/proxy.ts`,** que se ejecuta en cada solicitud:
  - solo admite `Host` `localhost`, `127.0.0.1` o `[::1]` en el puerto real (421 en otro caso);
  - valida `X-Forwarded-Host`;
  - rechaza `Sec-Fetch-Site: cross-site` o `same-site` en la API (403).
- **Intermediario:** repite la validación de `Host`.

Estas medidas reducen el DNS rebinding y la exposición accidental, pero **no** sustituyen a la
autenticación: cualquier proceso o usuario del propio equipo puede leer la oficina.

## 6. Qué no hace

- No ejecuta agentes, no enciende el programador y no recolecta. La demostración lo hace contra el backend, no desde la interfaz.
- No normaliza ni corrige vínculos, alias o ambigüedad.
- No calcula etapas, saturación, oportunidad ni confianza.
