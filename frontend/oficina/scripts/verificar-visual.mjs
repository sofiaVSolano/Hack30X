// Verificación visual con el Edge instalado en el equipo (playwright-core no descarga navegadores).
// Recorre las vistas en escritorio y móvil, guarda capturas, registra errores de consola y
// ejecuta axe-core (WCAG 2 A/AA). No ejecuta ninguna acción de escritura.
//
// Uso: OFICINA_URL=http://127.0.0.1:3000 SALIDA=<carpeta> MODO=real|simulated node scripts/verificar-visual.mjs
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

import { chromium } from "playwright-core";

const require = createRequire(import.meta.url);
const base = process.env.OFICINA_URL ?? "http://127.0.0.1:3000";
const out = process.env.SALIDA ?? "verificacion";
const mode = process.env.MODO === "simulated" ? "simulated" : "real";
const routes = (process.env.RUTAS ?? "/,/tendencias,/oficina,/agentes,/ejecuciones,/programador,/temas,/metricas,/clasificaciones").split(",");
const viewports = [
  { name: "escritorio", width: 1440, height: 900 },
  { name: "movil", width: 390, height: 844 },
];
mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: "msedge", headless: true });
const report = { base, mode, pages: [] };

async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() => !document.querySelector('[aria-busy="true"]'), null, { timeout: 15000 }).catch(() => {});
  await page.evaluate(() => document.fonts.ready);
}

for (const viewport of viewports) {
  const context = await browser.newContext({ viewport, reducedMotion: "reduce", locale: "es-ES" });
  for (const route of routes) {
    const page = await context.newPage();
    const consoleErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" || msg.type() === "warning") consoleErrors.push(`${msg.type()}: ${msg.text()}`);
    });
    page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err.message}`));
    const url = `${base}${route}${mode === "simulated" ? "?modo=simulated" : ""}`;
    await page.goto(url);
    await settle(page);
    // Comprobación de teclado sobre la carga limpia (antes de capturas y axe).
    // Teclado: el primer Tab lleva al enlace «Saltar al contenido», visible y con anillo de foco;
    // Enter mueve el foco al contenido principal.
    await page.keyboard.press("Tab");
    // Dos fotogramas: con movimiento reducido las transiciones duran 0,01 ms, pero existen.
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
    const keyboard = await page.evaluate(() => {
      const el = document.activeElement;
      const box = el?.getBoundingClientRect();
      return {
        primerFoco: el?.textContent?.trim() ?? null,
        visible: Boolean(box && box.top >= 0 && box.height > 0),
        anillo: el ? getComputedStyle(el).boxShadow !== "none" || getComputedStyle(el).outlineStyle !== "none" : false,
      };
    });
    await page.keyboard.press("Enter");
    keyboard.focoEnContenido = await page.evaluate(() => document.activeElement?.id === "contenido" || location.hash === "#contenido");
    keyboard.ok = keyboard.primerFoco === "Saltar al contenido" && keyboard.visible && keyboard.anillo && keyboard.focoEnContenido;
    await page.goto(url); // sin el #contenido que añadió el Enter
    await settle(page);
    const slug = route === "/" ? "portada" : route.slice(1);
    const shot = join(out, `${viewport.name}-${mode}-${slug}.png`);
    await page.screenshot({ path: shot, fullPage: true });

    await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
    const axe = await page.evaluate(async () => {
      // eslint-disable-next-line no-undef
      const result = await axe.run(document, { runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] });
      return result.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, ejemplo: v.nodes[0]?.target }));
    });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    // Con prefers-reduced-motion: ninguna animación en curso de más de 10 ms.
    const runningAnimations = await page.evaluate(
      () => document.getAnimations().filter((a) => a.playState === "running" && Number(a.effect?.getTiming().duration) > 10).length,
    );
    report.pages.push({ viewport: viewport.name, route, shot, consoleErrors, axe, horizontalOverflow: overflow, runningAnimations, keyboard });
    await page.close();
  }

  // Interacción: abrir el detalle de un agente desde la planta y cerrarlo con Escape.
  if (routes.includes("/oficina")) {
    const page = await context.newPage();
    await page.goto(`${base}/oficina${mode === "simulated" ? "?modo=simulated" : ""}`);
    await settle(page);
    const station = page.getByRole("button", { name: /Ver detalle/ }).first();
    if (await station.count()) {
      await station.click();
      await page.getByRole("dialog").waitFor();
      await settle(page);
      await page.screenshot({ path: join(out, `${viewport.name}-${mode}-detalle-agente.png`) });
      await page.keyboard.press("Escape");
      await page.getByRole("dialog").waitFor({ state: "hidden" });
      const focusReturned = await page.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? null);
      report.pages.push({ viewport: viewport.name, route: "/oficina (detalle de agente)", focusReturned });
    }
    await page.close();
  }
  await context.close();
}

await browser.close();
writeFileSync(join(out, `informe-${mode}.json`), JSON.stringify(report, null, 2));
const problems = report.pages.filter((p) => p.consoleErrors?.length || p.axe?.length || p.horizontalOverflow);
console.log(JSON.stringify(report.pages.map(({ shot, ...rest }) => rest), null, 1));
console.log(problems.length ? `Páginas con observaciones: ${problems.length}` : "Sin errores de consola, sin violaciones axe y sin desbordamiento horizontal.");
