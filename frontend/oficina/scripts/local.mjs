// Lanzador local de la oficina y del backend (cierre de DETECTAR).
//
//   node scripts/local.mjs configurar           crea el archivo de secretos FUERA de OneDrive (no lo sobrescribe)
//   node scripts/local.mjs oficina dev|start    Next.js en 127.0.0.1 (puerto OFICINA_PUERTO o 3000)
//   node scripts/local.mjs backend              uvicorn en 127.0.0.1 (puerto DETECTAR_PUERTO o 8000)
//
// Secretos: se toman de las variables de entorno del proceso o, si faltan, del archivo de
// configuración (OFICINA_CONFIG o, por defecto, %LOCALAPPDATA%\hack30x\oficina\oficina.env).
// Nunca se imprimen. El archivo no puede estar en OneDrive ni en el repositorio, y si el proyecto
// contiene un .env* con el token, el lanzador se niega a continuar (no lo mueve ni lo borra).
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { checkConfigPath, parseConfig, projectEnvWithToken } from "./local/config.mjs";

const OFICINA = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = resolve(OFICINA, "..", "..");
const BACKEND = join(REPO, "backend");
const PYTHON = join(BACKEND, ".venv", process.platform === "win32" ? "Scripts\\python.exe" : "bin/python");
const HOST = "127.0.0.1";

function fail(message) {
  console.error(`ERROR: ${message}`);
  process.exit(1);
}

function defaultConfigPath() {
  if (process.platform === "win32" && process.env.LOCALAPPDATA) return join(process.env.LOCALAPPDATA, "hack30x", "oficina", "oficina.env");
  return join(process.env.XDG_CONFIG_HOME || join(homedir(), ".config"), "hack30x", "oficina.env");
}

const configPath = resolve(process.env.OFICINA_CONFIG || defaultConfigPath());

function loadConfig({ required }) {
  const problems = checkConfigPath(configPath, { repoRoot: REPO });
  if (problems.length) fail(`archivo de configuración no apto (${configPath}): ${problems.join("; ")}`);
  const leaks = projectEnvWithToken(OFICINA, readdirSync(OFICINA), (f) => readFileSync(f, "utf8"));
  if (leaks.length) {
    fail(`el proyecto contiene ${leaks.join(", ")} con DETECTAR_ADMIN_TOKEN, dentro de una carpeta sincronizada. ` +
      `Mueva el valor al archivo de configuración (${configPath}) o a variables de entorno y elimine ese archivo usted mismo.`);
  }
  const fromFile = existsSync(configPath) ? parseConfig(readFileSync(configPath, "utf8")) : { values: {}, errors: [] };
  if (fromFile.errors.length) fail(`configuración inválida: ${fromFile.errors.join("; ")}`);
  // Las variables del proceso tienen prioridad sobre el archivo.
  const merged = { ...fromFile.values };
  for (const key of Object.keys(process.env)) {
    if (key.startsWith("DETECTAR_") || key.startsWith("OFICINA_")) merged[key] = process.env[key];
  }
  delete merged.OFICINA_CONFIG;
  if (required && !merged.DETECTAR_ADMIN_TOKEN) {
    fail(`falta DETECTAR_ADMIN_TOKEN. Ejecute "npm run configurar" o defínalo en las variables de entorno.`);
  }
  return merged;
}

function run(command, args, options) {
  const child = spawn(command, args, { stdio: "inherit", ...options });
  const stop = () => child.kill();
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  child.on("exit", (code) => process.exit(code ?? 0));
}

function configurar() {
  const problems = checkConfigPath(configPath, { repoRoot: REPO });
  if (problems.length) fail(`ruta no apta (${configPath}): ${problems.join("; ")}`);
  if (existsSync(configPath)) {
    console.log(`Ya existe ${configPath}; no se modifica.`);
    return;
  }
  mkdirSync(dirname(configPath), { recursive: true });
  const token = randomBytes(48).toString("base64url");
  writeFileSync(
    configPath,
    [
      "# Configuración local de HACK 30X · oficina y backend de DETECTAR. NO versionar ni sincronizar.",
      "# El token se generó al crear el archivo y no se ha mostrado en pantalla.",
      `OFICINA_DETECTAR_URL=http://${HOST}:8000`,
      "OFICINA_DETECTAR_TIMEOUT_MS=8000",
      `DETECTAR_ADMIN_TOKEN=${token}`,
      "",
    ].join("\n"),
    { mode: 0o600, flag: "wx" },
  );
  try {
    chmodSync(configPath, 0o600);
  } catch {
    /* en Windows, %LOCALAPPDATA% ya es privado del usuario */
  }
  console.log(`Creado ${configPath} con un token nuevo (no se muestra).`);
}

function oficina(mode) {
  if (!["dev", "start"].includes(mode)) fail('uso: local.mjs oficina dev|start');
  const config = loadConfig({ required: true });
  const port = config.OFICINA_PUERTO || "3000";
  if (!/^\d{2,5}$/.test(port)) fail("OFICINA_PUERTO no es un puerto válido");
  const env = { ...process.env, NEXT_TELEMETRY_DISABLED: "1", OFICINA_HOSTNAME: HOST };
  for (const key of ["OFICINA_DETECTAR_URL", "OFICINA_DETECTAR_TIMEOUT_MS", "DETECTAR_ADMIN_TOKEN"]) {
    if (config[key] !== undefined) env[key] = config[key];
  }
  console.log(`Oficina (${mode}) en http://${HOST}:${port} — solo equipo local.`);
  run(process.execPath, ["node_modules/next/dist/bin/next", mode, "--hostname", HOST, "--port", port], { cwd: OFICINA, env });
}

function backend() {
  const config = loadConfig({ required: true });
  const port = config.DETECTAR_PUERTO || "8000";
  if (!/^\d{2,5}$/.test(port)) fail("DETECTAR_PUERTO no es un puerto válido");
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith("DETECTAR_") && !k.startsWith("OFICINA_")));
  for (const [key, value] of Object.entries(config)) {
    if (key.startsWith("DETECTAR_") && key !== "DETECTAR_PUERTO") env[key] = value;
  }
  console.log(`Backend DETECTAR en http://${HOST}:${port} — solo equipo local.`);
  run(PYTHON, ["-m", "uvicorn", "app.main:app", "--host", HOST, "--port", port], { cwd: BACKEND, env });
}

const [command, arg] = process.argv.slice(2);
if (command === "configurar") configurar();
else if (command === "oficina") oficina(arg);
else if (command === "backend") backend();
else fail("uso: local.mjs configurar | oficina dev|start | backend");
