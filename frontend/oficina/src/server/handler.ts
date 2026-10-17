import "server-only";

import { z } from "zod";

import { checkLocalRequest, rejection } from "@/lib/local-access";
import type { OficinaProblem } from "@/lib/schemas";

import { readConfig, type DetectarConfig } from "./config";
import { ENDPOINTS, type EndpointId, type EndpointSpec } from "./endpoints";

/**
 * Intermediario de solo lectura entre el navegador y DETECTAR.
 *
 * - El token solo se añade aquí, en el servidor, y nunca forma parte de una respuesta.
 * - Del navegador solo se aceptan los segmentos y parámetros declarados en ENDPOINTS.
 * - Al backend solo se envían `Accept` y `Authorization`; no se reenvía ninguna cabecera
 *   del navegador ni del backend.
 */
export const API_PREFIX = "/api/detectar";
export const MAX_RESPONSE_BYTES = 2_000_000;

const BackendProblem = z.object({
  code: z.string().regex(/^[a-z_]{1,40}$/),
  title: z.string().max(200),
  detail: z.string().max(500).nullish(),
  errors: z.array(z.object({ campo: z.string().max(200), mensaje: z.string().max(500) })).nullish(),
});

const JSON_HEADERS = { "Cache-Control": "no-store", "Content-Type": "application/json; charset=utf-8" };

function problem(status: number, body: OficinaProblem): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Cache-Control": "no-store", "Content-Type": "application/problem+json; charset=utf-8" },
  });
}

function invalidRequest(detail: string): Response {
  return problem(400, { code: "parametros_invalidos", title: "Solicitud no válida", detail });
}

function log(endpoint: EndpointId, outcome: string): void {
  // Solo el identificador del endpoint y el resultado: nunca URL, cabeceras ni cuerpos.
  console.warn(`[oficina] ${endpoint}: ${outcome}`);
}

export type TargetResult = { ok: true; url: URL } | { ok: false; response: Response };

export function buildTarget(
  spec: EndpointSpec,
  baseUrl: URL,
  segments: Record<string, string | string[] | undefined>,
  search: URLSearchParams,
): TargetResult {
  let path = spec.path;
  for (const [name, pattern] of Object.entries(spec.segments)) {
    const value = segments[name];
    if (typeof value !== "string" || !pattern.test(value)) {
      return { ok: false, response: invalidRequest(`El segmento «${name}» no es válido.`) };
    }
    path = path.replace(`{${name}}`, encodeURIComponent(value));
  }

  const query = new URLSearchParams();
  const seen = new Set<string>();
  for (const [key, value] of search) {
    const rule = spec.query[key];
    if (!rule) return { ok: false, response: invalidRequest(`El parámetro «${key.slice(0, 40)}» no está permitido.`) };
    if (seen.has(key)) return { ok: false, response: invalidRequest(`El parámetro «${key}» está repetido.`) };
    if (!rule(value)) return { ok: false, response: invalidRequest(`El valor del parámetro «${key}» no es válido.`) };
    seen.add(key);
    query.append(key, value);
  }

  // URL normaliza una ruta vacía a "/": se quita la barra final para no duplicarla.
  const basePath = baseUrl.pathname.replace(/\/+$/, "");
  const url = new URL(baseUrl.origin);
  url.pathname = `${basePath}${API_PREFIX}${path}`;
  url.search = query.toString();
  // Defensa adicional: el destino nunca puede salir del backend configurado.
  if (url.origin !== baseUrl.origin || !url.pathname.startsWith(`${basePath}${API_PREFIX}/`)) {
    return { ok: false, response: invalidRequest("Destino no permitido.") };
  }
  return { ok: true, url };
}

async function readLimited(response: globalThis.Response): Promise<string | null> {
  const declared = Number(response.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > MAX_RESPONSE_BYTES) return null;
  const text = await response.text();
  return text.length > MAX_RESPONSE_BYTES ? null : text;
}

async function fetchBackend(config: DetectarConfig, url: URL): Promise<globalThis.Response> {
  return fetch(url, {
    method: "GET",
    headers: { Accept: "application/json", Authorization: `Bearer ${config.token}` },
    redirect: "error",
    cache: "no-store",
    signal: AbortSignal.timeout(config.timeoutMs),
  });
}

function mapBackendError(endpoint: EndpointId, status: number, body: unknown): Response {
  const parsed = BackendProblem.safeParse(body);
  if ((status === 404 || status === 422) && parsed.success) {
    // Mensajes de dominio de DETECTAR: no repiten la entrada ni contienen secretos.
    const { code, title, detail, errors } = parsed.data;
    return problem(status, {
      code,
      title,
      ...(detail ? { detail } : {}),
      ...(errors ? { errors } : {}),
    });
  }
  if (status === 401 || status === 403) {
    log(endpoint, `backend ${status}`);
    return problem(502, {
      code: "intermediario_no_autorizado",
      title: "El intermediario no está autorizado",
      detail: "DETECTAR rechazó las credenciales del servidor de la oficina. Revise su configuración.",
    });
  }
  log(endpoint, `backend ${status}`);
  return problem(502, {
    code: "error_detectar",
    title: "DETECTAR devolvió un error",
    detail: parsed.success ? `Código de DETECTAR: ${parsed.data.code}.` : `Estado HTTP ${status}.`,
  });
}

export async function handleRead(
  endpoint: EndpointId,
  request: Request,
  segments: Record<string, string | string[] | undefined> = {},
): Promise<Response> {
  // Defensa en profundidad: proxy.ts ya valida cada solicitud; se repite por si cambia su alcance.
  const local = checkLocalRequest({
    host: request.headers.get("host") ?? new URL(request.url).host,
    secFetchSite: request.headers.get("sec-fetch-site"),
    secFetchMode: request.headers.get("sec-fetch-mode"),
    pathname: new URL(request.url).pathname,
    expectedPort: process.env.PORT,
  });
  if (!local.ok) return rejection(local);
  if (request.method !== "GET") {
    return problem(405, { code: "metodo_no_permitido", title: "Método no permitido" });
  }
  const configResult = readConfig();
  if (!configResult.ok) {
    log(endpoint, `configuración incompleta (${configResult.reason})`);
    return problem(503, {
      code: "intermediario_sin_configurar",
      title: "La oficina no está configurada",
      detail: "Falta o no es válida la configuración del servidor para conectar con DETECTAR.",
    });
  }
  const { config } = configResult;
  const spec = ENDPOINTS[endpoint];
  const target = buildTarget(spec, config.baseUrl, segments, new URL(request.url).searchParams);
  if (!target.ok) return target.response;

  let backend: globalThis.Response;
  try {
    backend = await fetchBackend(config, target.url);
  } catch (error) {
    const timeout = error instanceof DOMException && (error.name === "TimeoutError" || error.name === "AbortError");
    log(endpoint, timeout ? "tiempo agotado" : "sin conexión");
    return timeout
      ? problem(504, {
          code: "tiempo_agotado",
          title: "DETECTAR no respondió a tiempo",
          detail: `Se superaron ${config.timeoutMs} ms de espera.`,
        })
      : problem(502, {
          code: "detectar_no_disponible",
          title: "No se pudo conectar con DETECTAR",
          detail: "Compruebe que el backend está en ejecución.",
        });
  }

  const text = await readLimited(backend).catch(() => null);
  if (text === null) {
    log(endpoint, "respuesta ilegible o demasiado grande");
    return problem(502, { code: "respuesta_invalida", title: "Respuesta no válida de DETECTAR" });
  }
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    log(endpoint, `respuesta no JSON (${backend.status})`);
    return problem(502, { code: "respuesta_invalida", title: "Respuesta no válida de DETECTAR" });
  }

  if (!backend.ok) return mapBackendError(endpoint, backend.status, body);

  const parsed = spec.schema.safeParse(body);
  if (!parsed.success) {
    log(endpoint, "respuesta con estructura inesperada");
    return problem(502, {
      code: "respuesta_inesperada",
      title: "Respuesta inesperada de DETECTAR",
      detail: "La respuesta no coincide con el contrato conocido; no se muestra para no presentar datos incompletos.",
    });
  }
  return new Response(JSON.stringify(parsed.data), { status: 200, headers: JSON_HEADERS });
}
