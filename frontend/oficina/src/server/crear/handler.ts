import "server-only";

import { z } from "zod";

import { checkLocalRequest, rejection } from "@/lib/local-access";
import type { OficinaProblem } from "@/lib/schemas";

import { readConfig, type DetectarConfig } from "../config";
import { CREAR_ENDPOINTS, type CrearEndpoint, type CrearEndpointId } from "./endpoints";

/**
 * Intermediario entre el navegador y CREAR (mismo backend y mismo token que DETECTAR).
 *
 * Mantiene las garantías del intermediario de DETECTAR y añade las de escritura:
 * - el token solo se añade aquí y nunca forma parte de una respuesta;
 * - solo se aceptan las operaciones, segmentos y parámetros de CREAR_ENDPOINTS;
 * - los POST exigen `Content-Type: application/json`, un cuerpo pequeño y un esquema estricto;
 *   al backend se reenvía el cuerpo YA validado, nunca el original;
 * - no se reenvía ninguna cabecera del navegador ni del backend.
 */
export const CREAR_API_PREFIX = "/api/crear";
export const MAX_RESPONSE_BYTES = 2_000_000;
export const MAX_BODY_BYTES = 16_000;
/** Generar con Claude puede tardar: las escrituras esperan más que las lecturas. */
export const GENERATION_TIMEOUT_MS = 150_000;
export const MAX_DOCUMENT_BYTES = 10_000_000;
/** Único nombre de archivo que se acepta del backend; si no coincide, se usa uno fijo. */
const SAFE_DISPOSITION = /^attachment; filename="[a-z0-9-]{1,90}\.pdf"$/;

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

function log(endpoint: CrearEndpointId, outcome: string): void {
  // Solo la operación y el resultado: nunca URL, cabeceras ni cuerpos.
  console.warn(`[oficina] crear.${endpoint}: ${outcome}`);
}

export type CrearTarget = { ok: true; url: URL } | { ok: false; response: Response };

export function buildCrearTarget(
  spec: CrearEndpoint,
  baseUrl: URL,
  segments: Record<string, string | string[] | undefined>,
  search: URLSearchParams,
): CrearTarget {
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
  const basePath = baseUrl.pathname.replace(/\/+$/, "");
  const url = new URL(baseUrl.origin);
  url.pathname = `${basePath}${CREAR_API_PREFIX}${path}`;
  url.search = query.toString();
  if (url.origin !== baseUrl.origin || !url.pathname.startsWith(`${basePath}${CREAR_API_PREFIX}/`)) {
    return { ok: false, response: invalidRequest("Destino no permitido.") };
  }
  return { ok: true, url };
}

type BodyResult = { ok: true; json: string } | { ok: false; response: Response };

async function readBody(endpoint: CrearEndpointId, spec: CrearEndpoint, request: Request): Promise<BodyResult> {
  if (!spec.body) return { ok: false, response: invalidRequest("Esta operación no admite cuerpo.") };
  const type = request.headers.get("content-type") ?? "";
  if (!/^application\/json(\s*;|$)/i.test(type)) {
    return { ok: false, response: problem(415, { code: "tipo_no_admitido", title: "El cuerpo debe ser JSON" }) };
  }
  const declared = Number(request.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) {
    return { ok: false, response: problem(413, { code: "cuerpo_demasiado_grande", title: "Solicitud demasiado grande" }) };
  }
  const text = await request.text().catch(() => null);
  if (text === null || text.length > MAX_BODY_BYTES) {
    return { ok: false, response: problem(413, { code: "cuerpo_demasiado_grande", title: "Solicitud demasiado grande" }) };
  }
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { ok: false, response: invalidRequest("El cuerpo no es JSON válido.") };
  }
  const parsed = spec.body.safeParse(raw);
  if (!parsed.success) {
    log(endpoint, "cuerpo rechazado");
    // Solo la ruta de cada campo: nunca el valor recibido.
    const errors = parsed.error.issues.slice(0, 10).map((issue) => ({
      campo: ["body", ...issue.path.map(String)].join(".").slice(0, 200),
      mensaje: "Valor no admitido.",
    }));
    return { ok: false, response: problem(400, { code: "parametros_invalidos", title: "Solicitud no válida", errors }) };
  }
  return { ok: true, json: JSON.stringify(parsed.data) };
}

async function readLimited(response: globalThis.Response): Promise<string | null> {
  const declared = Number(response.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > MAX_RESPONSE_BYTES) return null;
  const text = await response.text();
  return text.length > MAX_RESPONSE_BYTES ? null : text;
}

function mapBackendError(endpoint: CrearEndpointId, status: number, body: unknown): Response {
  const parsed = BackendProblem.safeParse(body);
  if ((status === 404 || status === 422) && parsed.success) {
    // Mensajes de dominio de CREAR: no repiten la entrada ni contienen secretos.
    const { code, title, detail, errors } = parsed.data;
    return problem(status, { code, title, ...(detail ? { detail } : {}), ...(errors ? { errors } : {}) });
  }
  if (status === 401 || status === 403) {
    log(endpoint, `backend ${status}`);
    return problem(502, {
      code: "intermediario_no_autorizado",
      title: "El intermediario no está autorizado",
      detail: "El backend rechazó las credenciales del servidor de la oficina. Revise su configuración.",
    });
  }
  log(endpoint, `backend ${status}`);
  return problem(502, {
    code: "error_crear",
    title: "CREAR devolvió un error",
    detail: parsed.success ? `Código de CREAR: ${parsed.data.code}.` : `Estado HTTP ${status}.`,
  });
}

/** Reenvía el PDF de un lote solo si es realmente un PDF y de un tamaño razonable. */
async function relayDocument(endpoint: CrearEndpointId, backend: globalThis.Response): Promise<Response> {
  const invalid = () => {
    log(endpoint, "documento no válido");
    return problem(502, { code: "documento_invalido", title: "El documento recibido no es válido" });
  };
  if (!(backend.headers.get("content-type") ?? "").startsWith("application/pdf")) return invalid();
  const declared = Number(backend.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > MAX_DOCUMENT_BYTES) return invalid();
  const buffer = await backend.arrayBuffer().catch(() => null);
  if (!buffer || buffer.byteLength > MAX_DOCUMENT_BYTES) return invalid();
  if (new TextDecoder().decode(buffer.slice(0, 5)) !== "%PDF-") return invalid();
  const disposition = backend.headers.get("content-disposition") ?? "";
  return new Response(buffer, {
    status: 200,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/pdf",
      "Content-Disposition": SAFE_DISPOSITION.test(disposition) ? disposition : 'attachment; filename="propuestas-crear.pdf"',
      "X-Content-Type-Options": "nosniff",
    },
  });
}

async function fetchBackend(config: DetectarConfig, spec: CrearEndpoint, url: URL, json: string | null) {
  const accept = spec.binary ? `${spec.binary}, application/json` : "application/json";
  const headers: Record<string, string> = { Accept: accept, Authorization: `Bearer ${config.token}` };
  if (json !== null) headers["Content-Type"] = "application/json";
  return fetch(url, {
    method: spec.method,
    headers,
    body: json ?? undefined,
    redirect: "error",
    cache: "no-store",
    signal: AbortSignal.timeout(spec.method === "POST" ? GENERATION_TIMEOUT_MS : config.timeoutMs),
  });
}

export async function handleCrear(
  endpoint: CrearEndpointId,
  request: Request,
  segments: Record<string, string | string[] | undefined> = {},
): Promise<Response> {
  // Defensa en profundidad: proxy.ts ya valida cada solicitud (host local y mismo origen).
  const local = checkLocalRequest({
    host: request.headers.get("host") ?? new URL(request.url).host,
    secFetchSite: request.headers.get("sec-fetch-site"),
    secFetchMode: request.headers.get("sec-fetch-mode"),
    pathname: new URL(request.url).pathname,
    expectedPort: process.env.PORT,
  });
  if (!local.ok) return rejection(local);
  const spec: CrearEndpoint = CREAR_ENDPOINTS[endpoint];
  if (request.method !== spec.method) {
    return problem(405, { code: "metodo_no_permitido", title: "Método no permitido" });
  }
  const configResult = readConfig();
  if (!configResult.ok) {
    log(endpoint, `configuración incompleta (${configResult.reason})`);
    return problem(503, {
      code: "intermediario_sin_configurar",
      title: "La oficina no está configurada",
      detail: "Falta o no es válida la configuración del servidor para conectar con el backend.",
    });
  }
  const { config } = configResult;
  const target = buildCrearTarget(spec, config.baseUrl, segments, new URL(request.url).searchParams);
  if (!target.ok) return target.response;

  let json: string | null = null;
  if (spec.method === "POST") {
    const body = await readBody(endpoint, spec, request);
    if (!body.ok) return body.response;
    json = body.json;
  }

  let backend: globalThis.Response;
  try {
    backend = await fetchBackend(config, spec, target.url, json);
  } catch (error) {
    const timeout = error instanceof DOMException && (error.name === "TimeoutError" || error.name === "AbortError");
    log(endpoint, timeout ? "tiempo agotado" : "sin conexión");
    return timeout
      ? problem(504, {
          code: "tiempo_agotado",
          title: "CREAR no respondió a tiempo",
          detail: "La operación puede seguir en curso: revise el historial de propuestas en unos segundos.",
        })
      : problem(502, {
          code: "backend_no_disponible",
          title: "No se pudo conectar con el backend",
          detail: "Compruebe que el backend está en ejecución.",
        });
  }

  if (spec.binary && backend.ok) return relayDocument(endpoint, backend);

  const text = await readLimited(backend).catch(() => null);
  if (text === null) {
    log(endpoint, "respuesta ilegible o demasiado grande");
    return problem(502, { code: "respuesta_invalida", title: "Respuesta no válida de CREAR" });
  }
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    log(endpoint, `respuesta no JSON (${backend.status})`);
    return problem(502, { code: "respuesta_invalida", title: "Respuesta no válida de CREAR" });
  }
  if (!backend.ok) return mapBackendError(endpoint, backend.status, body);

  const parsed = spec.schema.safeParse(body);
  if (!parsed.success) {
    log(endpoint, "respuesta con estructura inesperada");
    return problem(502, {
      code: "respuesta_inesperada",
      title: "Respuesta inesperada de CREAR",
      detail: "La respuesta no coincide con el contrato conocido; no se muestra para no presentar datos incompletos.",
    });
  }
  return new Response(JSON.stringify(parsed.data), { status: backend.status, headers: JSON_HEADERS });
}
