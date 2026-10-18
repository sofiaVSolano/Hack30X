// Procedimiento de demostración simulada de la oficina (E14). Solo local.
//
//   node scripts/demo-simulada.mjs preparar [--dir <ruta>] [--reiniciar]
//   node scripts/demo-simulada.mjs servir   [--dir <ruta>] [--verificar --salida <ruta>]
//   node scripts/demo-simulada.mjs limpiar  [--dir <ruta>]
//
// - La base vive en una carpeta temporal aislada (por defecto %TEMP%\hack30x-demo-simulada), fuera
//   de OneDrive, del repositorio y de la base real; se comprueba antes de escribir.
// - Solo usa endpoints EXISTENTES de DETECTAR y solo en data_mode=simulated.
// - Las observaciones salen del conjunto SINTÉTICO versionado de DETECTAR, cargado con su comando
//   local (python -m app.modules.detectar.simulation cargar). Después, normalización, métricas,
//   clasificación y agentes se ejecutan con los endpoints existentes (ver docs/datos-simulados.md).
// - El token se genera en cada ejecución y solo vive en las variables de entorno de los procesos hijos.
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { checkDemoDir, defaultDemoDir, defaultRealDbDir, isDemoDir, lastClosedUtcDay, MARKER } from "./demo/rutas.mjs";

const OFICINA = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = resolve(OFICINA, "..", "..");
const BACKEND = join(REPO, "backend");
const PYTHON = join(BACKEND, ".venv", process.platform === "win32" ? "Scripts\\python.exe" : "bin/python");

const args = process.argv.slice(2);
const command = args[0];
const option = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
};
const flag = (name) => args.includes(name);
const demoDir = resolve(option("--dir") ?? defaultDemoDir());
const dbPath = join(demoDir, "detectar.db");

function fail(message) {
  console.error(`ERROR: ${message}`);
  process.exit(1);
}

function guard() {
  const problems = checkDemoDir(demoDir, { repoRoot: REPO });
  if (problems.length) fail(`carpeta no apta (${demoDir}): ${problems.join("; ")}`);
}

const freePort = () =>
  new Promise((ok) => {
    const server = createServer();
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => ok(port));
    });
  });

async function waitFor(url, ms = 60_000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try {
      const response = await fetch(url);
      if (response.status < 500 || response.status === 502) return;
    } catch {
      /* todavía arrancando */
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`no responde: ${url}`);
}

function startBackend(port, token) {
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.toUpperCase().startsWith("DETECTAR_")));
  Object.assign(env, { DETECTAR_DB_PATH: dbPath, DETECTAR_ADMIN_TOKEN: token, DETECTAR_SCHEDULER_ENABLED: "false" });
  const log = [];
  const child = spawn(PYTHON, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: BACKEND,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (d) => log.push(String(d)));
  child.stderr.on("data", (d) => log.push(String(d)));
  return { child, log };
}

function startOficina(port, backendPort, token) {
  const env = { ...process.env, OFICINA_DETECTAR_URL: `http://127.0.0.1:${backendPort}`, DETECTAR_ADMIN_TOKEN: token, NEXT_TELEMETRY_DISABLED: "1" };
  const log = [];
  const child = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", String(port)], {
    cwd: OFICINA,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (d) => log.push(String(d)));
  child.stderr.on("data", (d) => log.push(String(d)));
  return { child, log };
}

async function stop(proc) {
  // En Windows, un proceso terminado con kill() queda con signalCode y exitCode null.
  if (!proc || proc.child.exitCode !== null || proc.child.signalCode !== null) return;
  const done = new Promise((r) => proc.child.once("exit", r));
  proc.child.kill();
  await done;
}

function python(args) {
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.toUpperCase().startsWith("DETECTAR_")));
  const result = spawnSync(PYTHON, ["-m", "app.modules.detectar.simulation", ...args], { cwd: BACKEND, env, encoding: "utf8" });
  if (result.status !== 0) fail(`comando de simulación (${args[0]}): ${(result.stderr || result.stdout).trim().slice(-800)}`);
  return JSON.parse(result.stdout);
}

async function api(base, token, method, path, body) {
  const response = await fetch(`${base}/api/detectar${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", Accept: "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await response.json();
  if (!response.ok) throw new Error(`${method} ${path} -> ${response.status} ${json.code ?? ""}`);
  return json;
}

// --- preparar -----------------------------------------------------------------------------

async function preparar() {
  guard();
  if (existsSync(demoDir)) {
    if (!isDemoDir(demoDir)) fail(`${demoDir} existe y no la creó este procedimiento; no se toca`);
    if (!flag("--reiniciar")) fail(`la demostración ya existe en ${demoDir}. Use --reiniciar para recrearla desde cero (no se duplica nada)`);
    rmSync(demoDir, { recursive: true, force: true });
  }
  const realDbDir = defaultRealDbDir();
  const realExisted = existsSync(realDbDir);
  mkdirSync(demoDir, { recursive: true });
  writeFileSync(join(demoDir, MARKER), JSON.stringify({ proposito: "demo-simulada-hack30x", creado: new Date().toISOString() }));

  // 1. Conjunto sintético: metadatos y carga (el cargador repite todas las comprobaciones de ruta).
  const dataset = python(["describir"]);
  const carga = python(["cargar", "--db", dbPath]);
  console.log(`- Carga del conjunto ${carga.dataset}: ${carga.status} ${JSON.stringify(carga.observations)}`);
  const asOf = dataset.fecha_clasificacion ?? lastClosedUtcDay();

  const token = randomBytes(32).toString("base64url");
  const port = await freePort();
  const backend = startBackend(port, token);
  const base = `http://127.0.0.1:${port}`;
  const steps = [{ paso: "Carga del conjunto sintético", solicitud: "python -m app.modules.detectar.simulation cargar", resultado: carga }];
  try {
    await waitFor(`${base}/api/detectar/health`);
    const run = async (name, method, path, body) => {
      const result = await api(base, token, method, path, body);
      steps.push({ paso: name, solicitud: `${method} /api/detectar${path}`, cuerpo: body ?? null, resultado: result });
      console.log(`- ${name}`);
      return result;
    };
    await run("Normalización de temas", "POST", "/temas/normalizaciones", { data_mode: "simulated" });
    for (const day of dataset.fechas_metricas ?? [asOf]) {
      await run(`Cálculo de métricas ${day}`, "POST", "/metricas/calculos", { data_mode: "simulated", fecha_referencia: day });
    }
    await run("Clasificación por etapas", "POST", "/clasificaciones/calculos", { data_mode: "simulated", fecha_referencia: asOf });
    for (const [agent, parametros] of [
      ["trend_hunter", { fecha_referencia: asOf }],
      ["format_hunter", {}],
      ["supervisor", {}],
    ]) {
      const r = await run(`Ejecución del agente ${agent}`, "POST", `/agentes/${agent}/ejecuciones`, { data_mode: "simulated", parametros });
      console.log(`    estado=${r.estado}${r.codigo_error ? ` codigo_error=${r.codigo_error}` : ""}`);
    }
    // Comprobación de aislamiento: el modo real sigue vacío.
    const real = await api(base, token, "GET", "/agentes?data_mode=real");
    const realRuns = real.agentes.filter((a) => a.ultima_ejecucion !== null).length;
    if (realRuns !== 0) throw new Error(`hay ${realRuns} agentes con ejecuciones reales en la base de demostración`);
    steps.push({ paso: "Aislamiento", resultado: { agentes_con_ejecuciones_reales: realRuns } });
  } catch (error) {
    await stop(backend);
    console.error(backend.log.join("").slice(-2000));
    fail(error.message);
  }
  await stop(backend);
  if (backend.log.join("").includes(token)) fail("el token apareció en el log del backend");
  if (!realExisted && existsSync(realDbDir)) fail(`se creó la carpeta de la base real ${realDbDir}`);
  writeFileSync(
    join(demoDir, "registro.json"),
    JSON.stringify({ data_mode: "simulated", dataset: carga.dataset, fecha_referencia: asOf, base: dbPath, pasos: steps }, null, 2),
  );
  console.log(`\nDemostración preparada en ${demoDir}`);
  console.log(`Registro de pasos y resultados: ${join(demoDir, "registro.json")}`);
}

// --- servir / verificar ---------------------------------------------------------------------

async function servir() {
  guard();
  if (!isDemoDir(demoDir) || !existsSync(dbPath)) fail(`no hay demostración preparada en ${demoDir}. Ejecute primero "preparar"`);
  const token = randomBytes(32).toString("base64url");
  const backendPort = await freePort();
  const officePort = await freePort();
  let backend = startBackend(backendPort, token);
  const office = startOficina(officePort, backendPort, token);
  const officeUrl = `http://127.0.0.1:${officePort}`;
  const cleanup = async () => {
    await stop(office);
    await stop(backend);
  };
  try {
    await waitFor(`http://127.0.0.1:${backendPort}/api/detectar/health`);
    await waitFor(`${officeUrl}/api/oficina/salud`);
    if (!flag("--verificar")) {
      console.log(`Oficina (modo simulado): ${officeUrl}/tendencias?modo=simulated   — Ctrl+C para detener`);
      await new Promise((r) => process.once("SIGINT", r));
      return;
    }
    const salida = resolve(option("--salida") ?? join(demoDir, "verificacion"));
    const { verificar } = await import("./demo/verificar.mjs");
    const report = await verificar({
      officeUrl,
      salida,
      token,
      restartBackend: async () => {
        await stop(backend);
        backend = startBackend(backendPort, token);
        await waitFor(`http://127.0.0.1:${backendPort}/api/detectar/health`);
      },
      stopBackend: () => stop(backend),
    });
    const logs = office.log.join("") + backend.log.join("");
    report.tokenEnLogs = logs.includes(token);
    writeFileSync(join(salida, "verificacion-demo.json"), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    if (report.tokenEnLogs) fail("el token apareció en los logs");
  } finally {
    await cleanup();
  }
}

function limpiar() {
  if (!existsSync(demoDir)) return console.log(`No existe ${demoDir}; nada que limpiar.`);
  if (!isDemoDir(demoDir)) fail(`${demoDir} no fue creada por este procedimiento; no se borra`);
  rmSync(demoDir, { recursive: true, force: true });
  console.log(`Eliminada ${demoDir}`);
}

const commands = { preparar, servir, limpiar };
if (!commands[command]) fail("uso: demo-simulada.mjs preparar|servir|limpiar [--dir <ruta>] [--reiniciar] [--verificar --salida <ruta>]");
await commands[command]();
