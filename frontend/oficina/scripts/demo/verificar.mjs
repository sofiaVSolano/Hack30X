// Verificación de la demostración simulada contra servidores reales (E14).
// Lo llama `demo-simulada.mjs servir --verificar`. Solo lecturas.
import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { createRequire } from "node:module";

import { chromium } from "playwright-core";

const require = createRequire(import.meta.url);

const OFICINA = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

async function getJson(url) {
  const response = await fetch(url);
  return { status: response.status, text: await response.text() };
}

/** Comprueba a través del intermediario que cada modo devuelve solo registros de ese modo. */
export async function modeSeparation(officeUrl, token) {
  const checks = [];
  let tokenSeen = false;
  const endpoints = ["agentes", "recolecciones", "temas", "metricas", "clasificaciones", "temas/vinculos"];
  for (const mode of ["real", "simulated"]) {
    for (const endpoint of endpoints) {
      const { status, text } = await getJson(`${officeUrl}/api/oficina/${endpoint}?data_mode=${mode}`);
      tokenSeen ||= text.includes(token);
      const body = JSON.parse(text);
      const records = endpoint === "agentes" ? body.agentes.flatMap((a) => (a.ultima_ejecucion ? [a.ultima_ejecucion] : [])) : body.items;
      const foreign = records.filter((r) => r.data_mode !== mode).length;
      checks.push({ modo: mode, endpoint, status, modo_respuesta: body.data_mode, registros: records.length, de_otro_modo: foreign });
    }
    for (const agent of ["trend_hunter", "format_hunter", "supervisor", "analyst", "audience_filter", "strategist"]) {
      const { status, text } = await getJson(`${officeUrl}/api/oficina/agentes/${agent}/ejecuciones?data_mode=${mode}&limite=100`);
      tokenSeen ||= text.includes(token);
      const body = JSON.parse(text);
      checks.push({
        modo: mode,
        endpoint: `agentes/${agent}/ejecuciones`,
        status,
        modo_respuesta: body.data_mode,
        registros: body.ejecuciones.length,
        de_otro_modo: body.ejecuciones.filter((r) => r.data_mode !== mode).length,
      });
    }
  }
  return { checks, ok: checks.every((c) => c.status === 200 && c.modo_respuesta === c.modo && c.de_otro_modo === 0), tokenSeen };
}

function visualSweep(officeUrl, salida, mode) {
  const result = spawnSync(process.execPath, ["scripts/verificar-visual.mjs"], {
    cwd: OFICINA,
    env: { ...process.env, OFICINA_URL: officeUrl, SALIDA: salida, MODO: mode },
    encoding: "utf8",
    timeout: 600_000,
  });
  if (result.status !== 0) throw new Error(`verificación visual (${mode}) falló: ${result.stderr.slice(-1500)}`);
  return JSON.parse(readFileSync(join(salida, `informe-${mode}.json`), "utf8"));
}

/** Backend caído: se conservan los datos y se avisa; al volver, «Actualizar» los recupera. */
async function recovery(officeUrl, salida, stopBackend, restartBackend) {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  const stations = page.getByRole("group", { name: "Estaciones de agentes" });
  const stale = page.getByText("No se pudo actualizar").first();
  const refresh = page.getByRole("button", { name: "Actualizar" });
  const result = {};
  try {
    await page.goto(`${officeUrl}/?modo=simulated`);
    await stations.waitFor({ state: "attached" });
    result.datosIniciales = await stations.getByRole("button").count();

    await stopBackend();
    await refresh.click();
    await stale.waitFor({ timeout: 15_000 });
    result.avisoConBackendCaido = await stale.isVisible();
    result.datosConservados = await stations.getByRole("button").count();
    await page.screenshot({ path: join(salida, "recuperacion-1-backend-caido.png"), fullPage: false });

    await restartBackend();
    await page.waitForFunction(() => !document.querySelector("button[disabled]"), null, { timeout: 15_000 }).catch(() => {});
    await refresh.click();
    await stale.waitFor({ state: "detached", timeout: 15_000 });
    result.avisoTrasRecuperar = await page.getByText("No se pudo actualizar").count();
    await page.screenshot({ path: join(salida, "recuperacion-2-recuperado.png"), fullPage: false });

    // Recarga completa con el backend caído: error explícito, sin datos inventados.
    await stopBackend();
    await page.reload();
    await page.getByRole("alert").first().waitFor({ timeout: 15_000 });
    result.recargaSinBackend = {
      alertas: await page.getByRole("alert").count(),
      estaciones: await stations.count(),
    };
    await page.screenshot({ path: join(salida, "recuperacion-3-recarga-sin-backend.png"), fullPage: false });
    await restartBackend();
    await page.getByRole("button", { name: /Reintentar/ }).first().click();
    await stations.waitFor({ state: "attached", timeout: 15_000 });
    result.reintentarRecupera = (await stations.getByRole("button").count()) === 6;
  } finally {
    await browser.close();
  }
  result.ok =
    result.datosIniciales === 6 &&
    result.avisoConBackendCaido &&
    result.datosConservados === 6 &&
    result.avisoTrasRecuperar === 0 &&
    result.recargaSinBackend.alertas > 0 &&
    result.recargaSinBackend.estaciones === 0 &&
    result.reintentarRecupera;
  return result;
}

/**
 * Vistas con datos del conjunto sintético (modo simulated): temas, gráfica, datos insuficientes y
 * clasificaciones. Compara lo dibujado con lo que devuelve el intermediario.
 */
export async function dataViews(officeUrl, salida) {
  const api = async (path) => (await fetch(`${officeUrl}/api/oficina${path}`)).json();
  const topics = (await api("/temas?data_mode=simulated&limite=100")).items;
  const id = (name) => topics.find((t) => t.nombre === name)?.id;
  const alfa = id("Tema demo Alfa");
  const delta = id("Tema demo Delta");
  const result = { temas: topics.map((t) => t.nombre).sort() };
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    for (const viewport of [
      { name: "escritorio", width: 1440, height: 900 },
      { name: "movil", width: 390, height: 844 },
    ]) {
      const page = await browser.newPage({ viewport, reducedMotion: "reduce" });
      const errors = [];
      page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
      const axeRun = async () => {
        await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
        return page.evaluate(async () => (await axe.run(document, { runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] })).violations.map((v) => v.id));
      };
      const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      const r = (result[viewport.name] = {});

      // Temas: lista y detalle.
      await page.goto(`${officeUrl}/temas?modo=simulated`);
      await page.getByRole("button", { name: "Tema demo Alfa" }).click();
      const drawer = page.getByRole("dialog");
      await drawer.getByText("Vínculos vigentes").waitFor();
      await page.waitForLoadState("networkidle");
      r.detalleTema = {
        sujetos: await drawer.getByText("Tema_demo_Alfa").count(),
        etapa: await drawer.getByText("Acelerando").count(),
      };
      r.axeTema = await axeRun();
      await page.screenshot({ path: join(salida, `${viewport.name}-datos-tema-detalle.png`) });
      await page.keyboard.press("Escape");

      // Métricas: la gráfica dibuja exactamente los valores «ok» del backend.
      const values = (await api(`/metricas?data_mode=simulated&tema_id=${alfa}&metrica=wiki_views_total&limite=200`)).items;
      await page.goto(`${officeUrl}/metricas?modo=simulated&tema_id=${alfa}&metrica=wiki_views_total`);
      const chart = page.getByRole("img", { name: /Serie de wiki_views_total/ });
      await chart.waitFor();
      const drawn = await chart.locator("circle title").allTextContents();
      const okValues = values.filter((v) => v.estado === "ok").map((v) => v.valor).sort((a, b) => a - b);
      const drawnValues = drawn.map((t) => Number(t.split(": ")[1].split(" ")[0].replace(/\./g, "").replace(",", "."))).sort((a, b) => a - b);
      r.grafica = { puntos: drawn.length, valoresBackend: okValues.length, coinciden: JSON.stringify(okValues) === JSON.stringify(drawnValues) };
      r.axeMetricas = await axeRun();
      r.desbordamientoMetricas = await overflow();
      await page.screenshot({ path: join(salida, `${viewport.name}-datos-metricas-grafica.png`), fullPage: true });

      // Datos insuficientes: sin gráfica, «sin valor» y el motivo.
      await page.goto(`${officeUrl}/metricas?modo=simulated&tema_id=${delta}&metrica=wiki_views_total`);
      await page.getByText("No se dibuja una serie").waitFor();
      r.insuficiente = { graficas: await page.getByRole("img", { name: /Serie/ }).count(), sinValor: await page.getByText("sin valor").count() };
      await page.screenshot({ path: join(salida, `${viewport.name}-datos-metricas-insuficiente.png`), fullPage: true });

      // Clasificaciones con evidencias.
      await page.goto(`${officeUrl}/clasificaciones?modo=simulated`);
      await page.getByRole("heading", { name: "Tema demo Alfa" }).waitFor();
      await page.waitForLoadState("networkidle");
      const card = (name) => page.locator("article").filter({ has: page.getByRole("heading", { name }) });
      r.clasificaciones = {
        tarjetas: await page.locator("article").count(),
        sinCalibrar: await page.locator("article").getByText("Sin calibrar").count(),
        alfaAcelerando: await card("Tema demo Alfa").getByText("Acelerando").count(),
        alfaGdeltNoValidada: await card("Tema demo Alfa").locator("tr", { hasText: "GDELT" }).getByText("Fuente no validada").count(),
        gammaMotivo: await card("Tema demo Gamma").getByText("solo_fuente_no_validada").count(),
        betaPuntoMaximo: await card("Tema demo Beta").getByText("Punto máximo").count(),
        bannerSintetico: await page.getByRole("note").getByText(/conjunto sintético/).count(),
      };
      r.axeClasificaciones = await axeRun();
      r.desbordamientoClasificaciones = await overflow();
      await page.screenshot({ path: join(salida, `${viewport.name}-datos-clasificaciones.png`), fullPage: true });
      r.erroresConsola = errors;
      await page.close();
    }
  } finally {
    await browser.close();
  }
  return result;
}

function summarize(report) {
  const pages = report.pages.filter((p) => p.shot);
  return {
    paginas: pages.length,
    erroresConsola: pages.flatMap((p) => p.consoleErrors),
    violacionesAxe: pages.flatMap((p) => p.axe.map((v) => `${p.viewport} ${p.route}: ${v.id}`)),
    desbordamiento: pages.filter((p) => p.horizontalOverflow).map((p) => `${p.viewport} ${p.route}`),
    teclado: pages.filter((p) => !p.keyboard?.ok).map((p) => `${p.viewport} ${p.route}: ${JSON.stringify(p.keyboard)}`),
    animacionesConMovimientoReducido: pages.filter((p) => p.runningAnimations > 0).map((p) => `${p.viewport} ${p.route}`),
    focoTrasCerrarDetalle: report.pages.filter((p) => "focusReturned" in p).map((p) => p.focusReturned),
  };
}

export async function verificar({ officeUrl, salida, token, stopBackend, restartBackend }) {
  mkdirSync(salida, { recursive: true });
  const separacion = await modeSeparation(officeUrl, token);
  const real = summarize(visualSweep(officeUrl, salida, "real"));
  const simulado = summarize(visualSweep(officeUrl, salida, "simulated"));
  const datos = await dataViews(officeUrl, salida);
  const recuperacion = await recovery(officeUrl, salida, stopBackend, restartBackend);
  return { salida, separacionDeModos: separacion, visualReal: real, visualSimulado: simulado, datos, recuperacion };
}
