# Cierre funcional de DETECTAR

**DETECTAR queda cerrado funcionalmente dentro de su alcance actual.** No está integrado con los
demás módulos ni listo para producción ni para acceso por red.

## 1. Tres niveles distintos

| Nivel | Estado |
|---|---|
| **Cierre funcional** (DETECTAR y oficina, uso local) | **Sí.** Backend y oficina funcionan juntos. La demostración simulada es reproducible y recorre carga, normalización, métricas, clasificación, agentes y vistas, todo verificado en Edge |
| **Integración con otros módulos** | **No.** El contrato con ENTENDER (`detectar.v0.1`) es una propuesta sin acordar. No hay autenticación entre módulos ni endpoint de resumen |
| **Producción o acceso por red** | **No.** No hay autenticación de usuarios, el token es administrativo y la exclusión es de un solo proceso |

## 2. Qué se corrigió en el cierre

1. **Acceso local:**
   - validación de `Host`, `X-Forwarded-Host` y `Sec-Fetch-Site` en `src/proxy.ts`, con defensa en profundidad en el intermediario;
   - bloqueo de arranque fuera de loopback.
2. **Secretos fuera de OneDrive:**
   - lanzador `scripts/local.mjs` con un archivo en `%LOCALAPPDATA%\hack30x\oficina\oficina.env` o variables de entorno;
   - rechazo de `.env*` del proyecto que contengan el token.
3. **Datos sintéticos:** cargador versionado en `backend/app/modules/detectar/simulation/` y conjunto `detectar_demo_sintetico@1.0.0` (ver `backend/app/modules/detectar/docs/datos-simulados.md`).
4. **Defecto encontrado durante la verificación visual:** una evidencia `excluded` sin métricas se guardaba con `fuente_validada: false` aunque la fuente estuviera validada, y Wikimedia aparecía como «no validada». Ahora usa el estado real del conector. No cambian roles, etapas, umbrales ni la versión de las reglas.
5. **Interfaz:** la franja del modo simulado indica que es un conjunto sintético de demostración.
6. **E15, diseño:** la oficina es una planta arquitectónica con salas por módulo y un puesto por agente. Solo hay trabajo en pantalla con `pendiente` o `en_curso` de la API, y los roles sin tarea son puestos vacantes. La gráfica lleva unidad, rótulos directos y trazos distintos. Ver `docs/e15-diseno-visual.md`.

## 3. Verificado

- **Seguridad con servidores reales:**
  - `Host: evil.example` → 421, en API, páginas y estáticos;
  - un puerto ajeno → 421 y `X-Forwarded-Host` ajeno → 421;
  - `cross-site` a la API → 403, y la navegación normal sigue funcionando;
  - `next start --hostname 0.0.0.0`, `next start` sin `--hostname` y `next dev` sin lanzador → arranque bloqueado, sin llegar a abrir el puerto;
  - con el lanzador, ambos procesos escuchan solo en `127.0.0.1`.
- **Token:** no aparece en las respuestas, los logs ni los 88 archivos públicos (compilación con token canario).
- **Demostración** (`%TEMP%\hack30x-demo-simulada\detectar.db`):
  - se cargaron 159 observaciones y se crearon 5 temas, 315 valores de métricas y 5 clasificaciones (`acelerando`, `punto_maximo` y 3 `datos_insuficientes` con su motivo), además de 3 ejecuciones de agentes;
  - todo es `simulated`: hay 0 filas `real`;
  - una nueva carga devuelve `ya_cargado`.
- **Verificación visual en Edge,** en escritorio (1440×900) y móvil (390×844):
  - las 7 vistas en real y simulado;
  - el detalle de un tema;
  - la gráfica, con los 10 puntos dibujados iguales a los 10 valores del backend;
  - el estado de datos insuficientes, sin gráfica y con «sin valor»;
  - las clasificaciones con evidencias;
  - la franja del conjunto sintético;
  - teclado y movimiento reducido;
  - la recuperación con el backend caído;
  - 0 errores de consola, 0 violaciones de axe (WCAG 2.1 AA) y 0 desbordamientos.
- **Programador,** con procesos y base temporales:
  - apagado por defecto;
  - activado de forma explícita, ejecuta `supervisor` como programado;
  - apagado ordenado;
  - al reiniciar no duplica ejecuciones (no vencidas);
  - recupera una ejecución abandonada como `failed`/`abandoned`;
  - tras terminarlo a la fuerza, la base queda íntegra;
  - los estados terminales son inmutables (lo impide un trigger).

## 4. Riesgos y pendientes

- **Autenticación:** no hay usuarios. Cualquier proceso o usuario del mismo equipo puede leer la oficina, y validar `Host` no elimina todos los riesgos locales.
- **Token administrativo:** el intermediario usa el token completo. Un token de solo lectura requiere cambiar la autenticación compartida (decisión del equipo).
- **Varios procesos:** la coordinación es de un solo proceso. Con varios workers habría varios programadores.
- **Apagado durante una tarea:** no se pudo verificar una terminación forzada *durante* una tarea, porque las tareas duran milisegundos. La consecuencia, una ejecución abandonada, sí está verificada.
- **Registros del programador:** los mensajes INFO de la aplicación («programador detenido») no aparecen con la configuración por defecto de uvicorn. El apagado se verificó por su resultado.
- **Fuentes y reglas:** GDELT sigue sin validar con la fuente real, `stages-v1` sigue sin calibrar y `saturada` no se asigna.
- **Pendiente con el equipo:** el contrato con ENTENDER, la autenticación entre módulos, la ubicación definitiva del frontend y un posible frontend común.
