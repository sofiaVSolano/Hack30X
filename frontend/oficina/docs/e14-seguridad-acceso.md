# E14: análisis de seguridad del acceso a la oficina

> **Actualización (cierre de DETECTAR):** ya está implementada la alternativa A: validación de `Host`/`X-Forwarded-Host`/`Sec-Fetch-Site` en `src/proxy.ts`, bloqueo de arranque fuera de loopback y secretos fuera de OneDrive con `scripts/local.mjs`, lo que cierra R1, R3 y R5. **Siguen abiertos R2 (otros procesos o usuarios del equipo) y R4 (token administrativo completo), y la oficina sigue sin estar lista para la red:** las alternativas B y C requieren decisión del equipo. Ver `docs/cierre-detectar.md`.

**Estado: análisis y recomendación.** No se implementa nada de lo propuesto aquí. Hasta que el
equipo lo apruebe, la oficina **solo puede usarse en `127.0.0.1` y no está lista para exponerse en
ninguna red**.

## 1. Estado actual (verificado el 2026-10-17)

```
Navegador ──GET /api/oficina/*──► Next.js (127.0.0.1:3000) ──Bearer DETECTAR_ADMIN_TOKEN──► DETECTAR (127.0.0.1:8000)
```

| Aspecto | Estado | Cómo se verificó |
|---|---|---|
| Interfaz de escucha | Solo `127.0.0.1` (`next dev/start --hostname 127.0.0.1`; uvicorn igual) | `Get-NetTCPConnection`: `LocalAddress = 127.0.0.1` |
| Autenticación de usuarios de la oficina | **Ninguna**: cualquiera que alcance el puerto lee todo | Diseño E13 |
| Token administrativo | Solo en el servidor; no aparece en archivos públicos, respuestas ni logs | Pruebas E13 y compilación con token canario |
| Métodos | Solo `GET`; `POST`/`PUT`/`DELETE` responden 405 | Pruebas y servidor real |
| Rutas | Lista cerrada de 12 lecturas, con parámetros validados | Pruebas |
| CORS | No se emiten cabeceras `Access-Control-*` | `curl` con `Origin: http://evil.example` |
| Cabecera `Host` | **No se valida**: `Host: evil.example` se procesa igual que `127.0.0.1` | `curl -H "Host: …"` contra `next start` |
| Cookies | Ninguna | Diseño |
| Privilegios del token | `DETECTAR_ADMIN_TOKEN` es **administrativo completo** en DETECTAR (también permite `POST`) | `require_admin` en el backend |
| Ubicación de `.env.local` | Dentro del repositorio, que está **en OneDrive** | Ruta del repositorio |

## 2. Riesgos actuales

| # | Riesgo | Gravedad | Explicación |
|---|---|---|---|
| R1 | **DNS rebinding** | Alta (en el equipo de desarrollo) | Una web maliciosa abierta en el navegador puede resolver su dominio a `127.0.0.1`. Así lee `/api/oficina/*` como si fuera su propio origen: la falta de CORS no protege, porque para el navegador es la misma web. El servidor acepta cualquier `Host` |
| R2 | Otros procesos o usuarios del mismo equipo | Media | Cualquier proceso local puede leer el puerto sin credenciales. Los datos son de solo lectura, pero administrativos |
| R3 | Exposición accidental en red | Alta si ocurre | Basta con cambiar `--hostname` a `0.0.0.0` o desplegar con `next start` sin ese parámetro para que **cualquiera en la red** lea la oficina sin autenticarse |
| R4 | Token con privilegios excesivos | Alta si el servidor de la oficina se ve comprometido | Quien obtenga el token puede iniciar recolecciones, ejecutar agentes y corregir vínculos, no solo leer. El intermediario lo limita a lecturas, pero el secreto en sí no está limitado |
| R5 | Sincronización del secreto | Media | `frontend/oficina/.env.local` y `backend/*.env` viven en una carpeta de OneDrive, de modo que el token se sube a la nube del usuario. `.gitignore` evita el repositorio, no OneDrive |
| R6 | Modo de desarrollo | Baja | `next dev` incluye recarga en caliente y superficies de depuración. Solo debe usarse para desarrollar |
| R7 | CSRF | **No aplica hoy** | No hay cookies ni operaciones con efectos: todas las rutas son `GET` de lectura. Pasará a ser aplicable en cuanto exista una sesión por cookie |

Un intermediario por sí solo **no** protege la aplicación. Evita que el token llegue al
navegador, pero no impide que **cualquiera que alcance el intermediario** lea los datos.

## 3. Alternativas

### A. Acceso estrictamente local (situación actual, reforzada)

Se conserva el uso en `127.0.0.1` y se añaden tres medidas:
- **Lista de `Host` permitidos** en el intermediario (`127.0.0.1:<puerto>`, `localhost:<puerto>`), que mitiga R1.
- Comprobar `Sec-Fetch-Site`/`Origin` en `/api/oficina/*` y rechazar `cross-site`.
- Negarse a arrancar si la oficina escucha en una interfaz que no sea de loopback.

| Ventajas | Desventajas |
|---|---|
| Pocas líneas, sin estado, sin dependencias | No sirve para usar la oficina desde otro equipo ni para el equipo completo |
| Cierra R1 y R3 | R2 persiste (cualquier usuario local) |

### B. Sesión web propia de la oficina (cookie)

- Inicio de sesión en la oficina; el servidor emite una cookie de sesión `HttpOnly`, `Secure` (con
  HTTPS), `SameSite=Lax` (o `Strict`), `Path=/` y `Max-Age` corto (p. ej. 8 h). Se renueva con
  la actividad y se invalida al cerrar sesión, en el servidor.
- El intermediario comprueba la sesión en **cada** ruta `/api/oficina/*` y en las páginas.
- Necesita una **fuente de identidades** (proveedor OIDC del equipo o usuarios locales con
  contraseña con hash fuerte: argon2id o bcrypt) y un almacén de sesiones (memoria, firmado sin
  estado o base de datos).
- **CSRF:** mientras todo sea `GET` sin efectos, `SameSite` basta. Si algún día hay acciones
  (`POST`), hará falta un token CSRF (doble envío o sincronizador) y comprobar `Origin`.
- **Roles:** `lector_oficina` (todas las lecturas actuales) y, a futuro, `operador` (acciones
  como ejecutar agentes), separado y con confirmación explícita.

| Ventajas | Desventajas |
|---|---|
| Permite usar la oficina en red de forma controlada | Requiere decidir el proveedor de identidad, almacenar sesiones y gestionar contraseñas o OIDC |
| Expiración, cierre de sesión y auditoría por usuario | Más superficie: inicio de sesión, fuerza bruta, fijación de sesión, rotación |
| Base para roles | Solo protege la oficina; el resto de HACK 30X necesitaría lo mismo |

### C. Autenticación común de HACK 30X (frontend o pasarela compartida)

- Un único inicio de sesión para todos los módulos (DETECTAR, ENTENDER, CREAR, VALIDAR), con roles
  por módulo. La oficina pasa a ser una sección del frontend común o va detrás de la misma pasarela.
- El backend compartido podría aceptar **identidades de servicio** con permisos limitados, por
  ejemplo un token de **solo lectura** para la oficina distinto del administrativo (mitiga R4).
- La autenticación **entre módulos** (ENTENDER → DETECTAR) se decide en el mismo marco.

| Ventajas | Desventajas |
|---|---|
| Coherente para todo el producto; una sola política | Depende de decisiones de todo el equipo, no solo de DETECTAR |
| Permite tokens limitados por servicio | Cambia el backend compartido (autenticación) y posiblemente la ubicación del frontend |

### D. Proxy inverso con autenticación delante (p. ej. un proxy con inicio de sesión o una VPN)

| Ventajas | Desventajas |
|---|---|
| No toca el código; rápido para una demostración interna | Infraestructura adicional, y protege el borde pero no da roles dentro de la aplicación |
| Útil como medida temporal | Fácil de configurar mal (rutas sin proteger, cabeceras de identidad falsificables si el puerto interno queda accesible) |

## 4. Recomendación

1. **Ya, en una etapa corta autorizada:** aplicar las medidas de la alternativa A (lista de `Host`
   permitidos, `Sec-Fetch-Site` y negarse a arrancar fuera de loopback). Cierra R1 y R3 sin
   decidir nada de arquitectura.
2. **Ya, operativo y sin código:** guardar los secretos **fuera de OneDrive** (R5), por ejemplo en
   variables de entorno del usuario o en un archivo en `%LOCALAPPDATA%`, y usar `next start`
   salvo para desarrollar (R6).
3. **Antes de cualquier uso en red:** la alternativa C (o B, si el equipo prefiere que la oficina
   sea independiente). En ambos casos con:
   - un token de **solo lectura** en DETECTAR para el intermediario (R4);
   - cookie `HttpOnly` + `Secure` + `SameSite=Lax`, con expiración y cierre de sesión en el servidor;
   - el rol `lector_oficina`;
   - HTTPS de extremo a extremo.
4. **D** solo como medida temporal para una demostración puntual, nunca como solución permanente.

## 5. Decisiones que debe aprobar el equipo

1. ¿La oficina será una aplicación independiente o una sección de un frontend común de HACK 30X?
   ¿Dónde vivirá el código?
2. ¿Qué proveedor de identidad se usa (OIDC del equipo, usuarios locales u otro)?
3. ¿Qué roles existen y qué puede ver cada uno? ¿Alguien podrá ejecutar acciones desde la oficina?
4. ¿Se crea en DETECTAR un token o una identidad de servicio de **solo lectura**? Implica cambiar
   la autenticación del backend compartido.
5. ¿Cómo se autentican los módulos entre sí (ENTENDER → DETECTAR)?
6. ¿Dónde se guardan los secretos en desarrollo y en producción?
7. ¿Se autoriza ya la etapa corta de endurecimiento local (alternativa A)?

## 6. Plan para una etapa futura autorizada

| Paso | Contenido | Pruebas |
|---|---|---|
| 1 | Endurecimiento local (A): validar `Host`, `Sec-Fetch-Site`; comprobar la interfaz de escucha al arrancar | `Host` ajeno → 421/403; `Sec-Fetch-Site: cross-site` → 403; arranque en `0.0.0.0` rechazado |
| 2 | Token de solo lectura en DETECTAR (si se aprueba C/B). Cambio en `require_admin`/dependencias, con el administrativo intacto | El token de lectura no puede hacer `POST` (403); el administrativo sigue funcionando |
| 3 | Sesión (B o C): inicio y cierre de sesión, cookie `HttpOnly`/`Secure`/`SameSite`, expiración e invalidación en el servidor | Sin sesión → 401 en `/api/oficina/*` y redirección en las páginas; sesión caducada; cierre de sesión invalida en el servidor |
| 4 | Roles: `lector_oficina` | Un rol sin permiso → 403 |
| 5 | CSRF (solo si se añaden acciones `POST`) | `POST` sin token CSRF o con `Origin` ajeno → 403 |
| 6 | HTTPS y cabeceras: `Strict-Transport-Security`, `Content-Security-Policy` | Comprobación de cabeceras |

Mientras no se completen los pasos 2 a 6, **la oficina no debe exponerse en red**, aunque el paso 1
esté hecho.
