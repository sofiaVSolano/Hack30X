# CREAR · laboratorio creativo

CREAR convierte lo que detecta DETECTAR en propuestas de contenido para creadores de
Latinoamérica. Lee DETECTAR **en solo lectura** y guarda sus propuestas en **su propia base**
(`crear.db`).

| Requisito | Qué hace | Dónde |
|---|---|---|
| RF-06 | Compara la atención que recibe cada tema en inglés y en español (reglas `brechas-v1`) | `gaps/` |
| RF-09 | Genera tres propuestas: educativa, controversial y narrativa | `generation/`, `service.py` |
| RF-10 | Regenera una propuesta cambiando enfoque, audiencia, plataforma o país; las versiones anteriores se conservan | `service.py` |
| Entregable | Documento PDF del lote: las tres propuestas (versión más reciente), los datos de DETECTAR y las precauciones | `export/pdf.py` |

## RF-06: brechas inglés–español

Cada fuente se compara por separado, en su unidad y con las métricas `metrics-v1` que DETECTAR
ya calculó (CREAR no recalcula nada):

| Fuente | Inglés | Español |
|---|---|---|
| Wikimedia (validada) | visitas de 7 días en `en.wikipedia.org` | visitas en `es.wikipedia.org` |
| Google Trends RSS (validada) | presencia en capturas de EE. UU., Reino Unido, Canadá… | presencia en capturas de países de Latinoamérica |
| GDELT (no validada) | artículos `sourcelang:english` | artículos `sourcelang:spanish` |

Veredictos (categorías con reglas explícitas, nunca una puntuación):

- **Brecha confirmada:** una fuente validada muestra al menos 3× más atención en inglés y
  ninguna fuente validada muestra lo contrario.
- **Brecha por confirmar:** hay atención en inglés, pero el español no se midió o solo lo sugiere GDELT.
- **Señales mixtas:** fuentes validadas apuntan en direcciones opuestas.
- **Sin brecha:** atención parecida o mayor en español.
- **Datos insuficientes:** no hay mediciones en inglés.

Un dato ausente nunca es cero: «sin medición» significa que DETECTAR no recolectó ese idioma.
Los umbrales son provisionales y no están calibrados (`GET /api/crear/brechas/reglas`).

## RF-09 y RF-10: motores de generación

- **Claude** (`claude-opus-5-5`, SDK oficial `anthropic`): salida estructurada validada con
  Pydantic y `fallbacks="default"` (si los clasificadores de seguridad declinan, la API
  reintenta con el modelo de respaldo recomendado). Se usa si hay `ANTHROPIC_API_KEY`.
- **Plantillas** (`plantillas-v1`): deterministas, sin red. Se usan si no hay credencial o si
  Claude falla; la propuesta indica el motivo.

Cada propuesta guarda los hechos de DETECTAR con que se creó. Una verificación marca las
**cifras sin respaldo**: porcentajes, multiplicadores o cantidades que no aparecen en esos hechos.

## API (`/api/crear`, mismo token que DETECTAR)

| Método y ruta | Uso |
|---|---|
| `GET /health` | Estado y motor activo (sin token) |
| `GET /opciones` | Enfoques, plataformas, audiencias, países y motor |
| `GET /temas` | Temas de DETECTAR con su etapa y su veredicto de brechas |
| `GET /brechas`, `GET /brechas/{tema_id}`, `GET /brechas/reglas` | RF-06 |
| `POST /propuestas` | RF-09: tres propuestas (`origen`: `brecha`, `tema` o `manual`) |
| `POST /propuestas/{id}/regeneraciones` | RF-10: nueva versión (solo se envía lo que cambia) |
| `GET /propuestas`, `GET /propuestas/{id}` | Historial y versiones |
| `GET /lotes/{lote_id}/pdf` | Documento PDF del lote (requiere ReportLab, extra `crear`) |

## Configuración

Ver `backend/crear.env.example`. Todo es opcional: sin configurar nada, CREAR funciona con
plantillas y guarda `crear.db` junto a la base de DETECTAR (si `DETECTAR_DB_PATH` está definida)
o en `~/.local/share/hack30x/crear/` (`%LOCALAPPDATA%\hack30x\crear\` en Windows).

Extra opcional `crear` de `pyproject.toml`: `pip install anthropic==1.15.0 reportlab==4.4.10`.
ReportLab genera el PDF (sin él, la descarga responde 503 con instrucciones). Para usar Claude,
defina además `ANTHROPIC_API_KEY` en la sesión del backend.

## Demostración

El conjunto de DETECTAR solo tiene señales en español. El complemento de CREAR añade temas
sintéticos con señales en inglés (Eta, Zeta, Theta) **sin modificar los temas de DETECTAR**, y
ejecuta el flujo real de DETECTAR sobre la base de demostración:

```bash
# Después de «npm run demo:preparar» (frontend/oficina), desde backend/:
.venv/Scripts/python.exe -m app.modules.crear.demo   # Windows
.venv/bin/python -m app.modules.crear.demo           # macOS/Linux
```

Resultado: un tema por veredicto (Eta confirmada, Zeta por confirmar, Theta mixta, Alfa y
Épsilon sin brecha, Beta, Delta y Gamma insuficientes). Es idempotente.

## Integración y límites

- Archivos compartidos que se tocaron: `app/main.py` (montar el router), `pyproject.toml`
  (extra opcional), la aserción de rutas de `tests/detectar/integration/test_app_integration.py`
  y, en la oficina, una entrada del menú y el recorrido de rutas de `tests/server/handler.test.ts`.
- El agente **Estratega** (`strategist`, alcance CREAR) sigue en `planned`: conectarlo al
  servicio de CREAR es el siguiente paso natural, pero modifica el registro de DETECTAR.
- La comparación mide atención, no la cantidad de contenido publicado en cada idioma.
