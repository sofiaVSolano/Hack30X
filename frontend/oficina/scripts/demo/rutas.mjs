// Protecciones de ruta del procedimiento de demostración simulada (E14).
// Funciones puras: se prueban en tests/demo/rutas.test.ts.
import { existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative, resolve, sep } from "node:path";

export const MARKER = ".hack30x-demo-simulada";
export const DEFAULT_DIR_NAME = "hack30x-demo-simulada";

/** Carpeta por defecto: temporal del sistema (en Windows, %LOCALAPPDATA%\Temp), fuera de OneDrive. */
export function defaultDemoDir(env = process.env) {
  return join(env.TEMP || env.TMP || tmpdir(), DEFAULT_DIR_NAME);
}

/** Ruta de la base REAL por defecto de DETECTAR (storage/db.py: default_db_path). Nunca se toca. */
export function defaultRealDbDir(env = process.env, platform = process.platform) {
  if (platform === "win32" && env.LOCALAPPDATA) return join(env.LOCALAPPDATA, "hack30x", "detectar");
  const base = env.XDG_DATA_HOME || join(env.HOME || "", ".local", "share");
  return join(base, "hack30x", "detectar");
}

function inside(child, parent) {
  const rel = relative(resolve(parent), resolve(child));
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

function oneDriveRoots(env) {
  return [env.OneDrive, env.OneDriveConsumer, env.OneDriveCommercial].filter(Boolean);
}

/**
 * Comprueba que una carpeta es apta para la base de demostración. Devuelve la lista de
 * motivos por los que NO lo es (vacía = apta).
 */
export function checkDemoDir(dir, { env = process.env, repoRoot, platform = process.platform } = {}) {
  const problems = [];
  if (!isAbsolute(dir)) problems.push("la ruta debe ser absoluta");
  const full = resolve(dir);
  if (full.split(sep).some((part) => /^onedrive/i.test(part)) || oneDriveRoots(env).some((root) => inside(full, root))) {
    problems.push("la ruta está dentro de OneDrive");
  }
  if (inside(full, defaultRealDbDir(env, platform)) || inside(defaultRealDbDir(env, platform), full)) {
    problems.push("la ruta coincide con la carpeta de la base real por defecto");
  }
  if (repoRoot && inside(full, repoRoot)) problems.push("la ruta está dentro del repositorio");
  return problems;
}

/** Una carpeta existente solo se puede reutilizar o borrar si la creó este procedimiento. */
export function isDemoDir(dir) {
  const marker = join(dir, MARKER);
  if (!existsSync(marker)) return false;
  try {
    return JSON.parse(readFileSync(marker, "utf8")).proposito === "demo-simulada-hack30x";
  } catch {
    return false;
  }
}

/** Último día cerrado en UTC (como el backend): la fecha UTC de hoy menos un día. */
export function lastClosedUtcDay(now = new Date()) {
  const day = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - 1));
  return day.toISOString().slice(0, 10);
}
