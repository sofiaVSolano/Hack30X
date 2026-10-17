/**
 * Cliente del navegador. Solo habla con el intermediario (`/api/oficina/...`) del mismo
 * origen; nunca con DETECTAR ni con credenciales.
 */
import type { ZodType } from "zod";

import { OficinaProblem } from "./schemas";

export const OFICINA_API = "/api/oficina";

export type QueryParams = Record<string, string | number | boolean | null | undefined>;

export class OficinaError extends Error {
  constructor(
    readonly kind: "http" | "network" | "invalid",
    readonly title: string,
    readonly detail?: string,
    readonly status?: number,
    readonly code?: string,
  ) {
    super(detail ? `${title}: ${detail}` : title);
    this.name = "OficinaError";
  }
}

export function buildUrl(path: string, params: QueryParams = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params).sort(([a], [b]) => a.localeCompare(b))) {
    if (value === undefined || value === null || value === "") continue;
    search.append(key, String(value));
  }
  const query = search.toString();
  return `${OFICINA_API}${path}${query ? `?${query}` : ""}`;
}

export async function getJson<T>(url: string, schema: ZodType<T>, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store", signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new OficinaError("network", "Sin conexión con el servidor de la oficina", "Compruebe su conexión y vuelva a intentarlo.");
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new OficinaError("invalid", "Respuesta ilegible", undefined, response.status);
  }
  if (!response.ok) {
    const parsed = OficinaProblem.safeParse(body);
    if (parsed.success) {
      throw new OficinaError("http", parsed.data.title, parsed.data.detail, response.status, parsed.data.code);
    }
    throw new OficinaError("http", "Error del servidor de la oficina", `Estado HTTP ${response.status}.`, response.status);
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    throw new OficinaError("invalid", "Respuesta inesperada", "Los datos recibidos no coinciden con el contrato conocido.", response.status);
  }
  return parsed.data;
}
