/**
 * Escrituras del laboratorio creativo. Igual que las lecturas, solo hablan con el intermediario
 * del mismo origen (`/api/oficina/crear/...`); nunca con el backend ni con credenciales.
 */
import type { ZodType } from "zod";

import { buildUrl, OficinaError } from "@/lib/api-client";
import { OficinaProblem } from "@/lib/schemas";

export async function postJson<T>(path: string, body: unknown, schema: ZodType<T>, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(buildUrl(path), {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new OficinaError("network", "Sin conexión con el servidor de la oficina", "Compruebe su conexión y vuelva a intentarlo.");
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new OficinaError("invalid", "Respuesta ilegible", undefined, response.status);
  }
  if (!response.ok) {
    const parsed = OficinaProblem.safeParse(data);
    if (parsed.success) {
      throw new OficinaError("http", parsed.data.title, parsed.data.detail, response.status, parsed.data.code);
    }
    throw new OficinaError("http", "Error del servidor de la oficina", `Estado HTTP ${response.status}.`, response.status);
  }
  const parsed = schema.safeParse(data);
  if (!parsed.success) {
    throw new OficinaError("invalid", "Respuesta inesperada", "Los datos recibidos no coinciden con el contrato conocido.", response.status);
  }
  return parsed.data;
}
