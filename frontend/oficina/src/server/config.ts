import "server-only";

/**
 * Configuración del intermediario. Se lee en cada solicitud desde variables de entorno del
 * servidor; ninguna lleva el prefijo público de Next, de modo que nunca se incrustan en el
 * código del navegador.
 */
export interface DetectarConfig {
  /** Origen y ruta base del backend (la barra final se ignora al construir el destino). */
  baseUrl: URL;
  token: string;
  timeoutMs: number;
}

export type ConfigResult =
  | { ok: true; config: DetectarConfig }
  | { ok: false; reason: "missing_url" | "invalid_url" | "missing_token" | "invalid_token" };

const DEFAULT_TIMEOUT_MS = 8000;

function parseTimeout(raw: string | undefined): number {
  const value = Number(raw);
  if (!raw || !Number.isInteger(value) || value < 1000 || value > 30000) return DEFAULT_TIMEOUT_MS;
  return value;
}

export function readConfig(env: NodeJS.ProcessEnv = process.env): ConfigResult {
  const rawUrl = env.OFICINA_DETECTAR_URL?.trim();
  if (!rawUrl) return { ok: false, reason: "missing_url" };
  let baseUrl: URL;
  try {
    baseUrl = new URL(rawUrl);
  } catch {
    return { ok: false, reason: "invalid_url" };
  }
  if (
    !["http:", "https:"].includes(baseUrl.protocol) ||
    baseUrl.username ||
    baseUrl.password ||
    baseUrl.search ||
    baseUrl.hash
  ) {
    return { ok: false, reason: "invalid_url" };
  }
  baseUrl.pathname = baseUrl.pathname.replace(/\/+$/, "");

  const token = env.DETECTAR_ADMIN_TOKEN ?? "";
  if (!token) return { ok: false, reason: "missing_token" };
  // Sin espacios ni saltos de línea: evita inyectar cabeceras y errores de copia.
  if (!/^[\x21-\x7e]{1,512}$/.test(token)) return { ok: false, reason: "invalid_token" };

  return { ok: true, config: { baseUrl, token, timeoutMs: parseTimeout(env.OFICINA_DETECTAR_TIMEOUT_MS) } };
}
