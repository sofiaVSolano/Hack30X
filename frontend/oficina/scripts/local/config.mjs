// Funciones puras del lanzador local: se prueban en tests/local/config.test.ts.
import { isAbsolute, join, relative, resolve, sep } from "node:path";

const ALLOWED_KEYS = /^(OFICINA_DETECTAR_URL|OFICINA_DETECTAR_TIMEOUT_MS|OFICINA_PUERTO|DETECTAR_[A-Z0-9_]+)$/;

function inside(child, parent) {
  const rel = relative(resolve(parent), resolve(child));
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

/** Motivos por los que la ruta del archivo de secretos NO es apta (vacío = apta). */
export function checkConfigPath(path, { env = process.env, repoRoot } = {}) {
  const problems = [];
  if (!isAbsolute(path)) problems.push("la ruta debe ser absoluta");
  const full = resolve(path);
  const roots = [env.OneDrive, env.OneDriveConsumer, env.OneDriveCommercial].filter(Boolean);
  if (full.split(sep).some((part) => /^onedrive/i.test(part)) || roots.some((root) => inside(full, root))) {
    problems.push("está dentro de OneDrive");
  }
  if (repoRoot && inside(full, repoRoot)) problems.push("está dentro del repositorio");
  return problems;
}

/**
 * Lee un archivo KEY=VALUE. Solo admite claves conocidas; los valores nunca aparecen en los
 * mensajes de error (solo el número de línea y la clave).
 */
export function parseConfig(text) {
  const values = {};
  const errors = [];
  text.split(/\r?\n/).forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) return;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) {
      errors.push(`línea ${index + 1}: formato KEY=VALUE`);
      return;
    }
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    if (!ALLOWED_KEYS.test(key)) {
      errors.push(`línea ${index + 1}: clave no admitida (${key.slice(0, 40)})`);
      return;
    }
    if (key in values) errors.push(`línea ${index + 1}: ${key} repetida`);
    values[key] = value;
  });
  return { values, errors };
}

/** Archivos .env* del proyecto (excepto el ejemplo) que contienen el token. */
export function projectEnvWithToken(dir, names, read) {
  return names
    .filter((name) => /^\.env/.test(name) && name !== ".env.example")
    .filter((name) => /^\s*DETECTAR_ADMIN_TOKEN\s*=\s*\S/m.test(read(join(dir, name))));
}
