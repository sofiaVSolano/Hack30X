# DETECTAR: cómo podría la oficina web leer el estado sin exponer el token

Los endpoints de lectura (`GET /api/detectar/recolecciones`, `/recolecciones/{run_id}`,
`/agentes` y `/agentes/{id}/ejecuciones`) exigen el token administrativo
`DETECTAR_ADMIN_TOKEN`. **Ese token no debe incluirse nunca en el código del navegador**:
cualquier persona podría leerlo en el JavaScript, en las herramientas de desarrollo o en el
tráfico, y con él podría también **iniciar recolecciones**.

## Opción recomendada: intermediario en el servidor (backend-for-frontend)

```
Navegador ──(sesión del usuario: cookie HttpOnly)──► Servidor de la oficina ──(Bearer token)──► DETECTAR
```

- El navegador se autentica ante el servidor de la oficina con el mecanismo de sesión que
  acuerde el equipo.
- El servidor de la oficina guarda `DETECTAR_ADMIN_TOKEN` como variable de entorno y lo añade
  al llamar a DETECTAR **solo** para las rutas `GET` de lectura.
- Ese servidor no reenvía `POST /recolecciones` desde el navegador. Iniciar recolecciones
  queda como acción administrativa explícita.
- Las respuestas se pueden reenviar tal cual: no contienen secretos (los mensajes de error
  ya se guardan sin ellos).

## Alternativa a futuro: autenticación compartida del backend

Si el backend común define autenticación de usuarios con roles, estos endpoints podrían
aceptar un rol de "solo lectura" separado del administrativo. **No está implementado**:
requiere acordarlo con el equipo y modificar la autenticación compartida, que esta etapa no
toca.

## Qué no hacer

- Poner el token en variables `VITE_*` o similares: se incrustan en el código del navegador.
- Abrir CORS a cualquier origen para que el navegador llame directamente con el token.
- Crear un token de lectura sin protección, o desactivar la autenticación de los `GET`.

## Actividad mostrada

La oficina debe mostrar solo lo que devuelve `/agentes`:

- `definido`, `implementado` y `ejecutado`;
- `actividad`, que se deriva exclusivamente de la última ejecución registrada;
- `ultima_ejecucion`.

Una animación de "trabajando" sin una ejecución `pendiente` o `en_curso` registrada sería
actividad inventada. Desde E10, `trend_hunter` y `supervisor` tienen tarea implementada; los otros
cuatro roles siguen planificados y sus ejecuciones quedarían bloqueadas.

## Implementación (E13)

El intermediario recomendado está implementado en `frontend/oficina/` (rutas de servidor de
Next.js con una lista cerrada de lecturas). Ver `frontend/oficina/docs/e13-diseno.md`.
