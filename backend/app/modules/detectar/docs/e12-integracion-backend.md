# E12: integración en el backend compartido y arranque real

## 1. Punto de partida (verificado el 17/10/2026)

- **No existían** `backend/app/main.py` ni `backend/pyproject.toml`, así que se crean. No había
  contenido previo que conservar.
- En `backend/app/modules/` solo existe `detectar`. No hay routers ni manejadores de otros
  módulos.
- `backend/app` y `backend/app/modules` son paquetes de espacio de nombres (sin `__init__.py`).
  No se agregan, para no imponer estructura a otros módulos.

## 2. Aplicación (`backend/app/main.py`)

```python
app = create_app()       # módulo importable: no arranca nada al importarse
create_app():
    FastAPI(title="HACK 30X", lifespan=lifespan)
    include_router(detectar_router, prefix="/api/detectar")   # el router no trae prefijo propio
    install_exception_handlers(app, prefix="/api/detectar")    # errores RFC 9457 de DETECTAR
lifespan(app):
    async with detectar_scheduler_lifespan() as scheduler:     # E11
        app.state.detectar_scheduler = scheduler                # None si está apagado
        yield
```

- **Errores:** `install_exception_handlers` registra `DetectarError` y el manejador de errores de
  validación. Este último solo responde en formato problem+json para rutas bajo
  `/api/detectar`; el resto conserva el formato de FastAPI.

  ⚠️ Es un manejador de toda la app: cuando otros módulos se integren, hay que acordar cómo
  combinarlos.
- **Salud:** se mantiene el contrato existente de `GET /api/detectar/health`, sin comprobaciones
  externas.

## 3. Ciclo de vida del programador

- **`DETECTAR_SCHEDULER_ENABLED=false` (por defecto):** no se crea ni se inicia nada, y
  `app.state.detectar_scheduler` vale `None`.
- **Habilitado:**
  - se usa `get_agent_scheduler()`, que es una instancia única por proceso y está construida
    sobre `get_agent_coordinator()`, el **mismo** coordinador que usa
    `POST /agentes/{id}/ejecuciones`;
  - `start()` es idempotente.
- **Errores de inicio:** una configuración inválida, como frecuencias fuera de rango, se
  registra en el log y **hace fallar el arranque de la aplicación**. No queda una app a medio
  iniciar. Si `start()` falla, no queda ninguna tarea creada.
- **Apagado:** `stop()` pide la parada, espera el tick en curso y, si supera el tiempo, lo
  cancela. Un error de apagado se registra en el log y se propaga.

  Las ejecuciones interrumpidas quedan en `running` y la recuperación de E11 las cierra como
  `abandoned` cuando corresponda. Nunca se fingen como completadas.

## 4. Base de datos

No cambia nada. `DETECTAR_DB_PATH` (o `%LOCALAPPDATA%\hack30x\detectar\detectar.db`) se abre de
forma perezosa en la primera solicitud que la necesita, con `init_db` y las migraciones
explícitas hasta la versión 4. `/health` no abre la base.

## 5. Dependencias (`backend/pyproject.toml`)

- **Ejecución:** las versiones fijas son las instaladas y verificadas en `backend/.venv`.
- **Desarrollo:** en `[dependency-groups]`.
- **`uvicorn`:** solo en `backend/.venv` y sin extras (`uvicorn`, no `uvicorn[standard]`).
- **pytest:** `testpaths` y `pythonpath`.
- **Ruff:** sin reglas nuevas ni `ruff format`.

## 6. Arranque

Desde `backend/`:

```
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Solo en `127.0.0.1`. Para las rutas protegidas hace falta `DETECTAR_ADMIN_TOKEN`; nunca debe ir
en el navegador (ver `acceso-oficina.md`).

## 7. Fuera de alcance

Frontend, autenticación compartida, otros módulos, despliegue y ejecución con varios procesos o
workers (no soportada por el programador: ver E11, sección 7).
