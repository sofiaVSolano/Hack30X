// Actualiza las tendencias REALES con los endpoints existentes de DETECTAR (modo real).
//
//   npm run tendencias:actualizar            (el backend debe estar en marcha: npm run backend)
//
// Pasos, en orden:
//   1. Google Trends RSS: tendencias de hoy de los países configurados (DETECTAR_COUNTRIES).
//   2. Normalización: cada tendencia pasa a ser un tema.
//   3. Wikipedia: historial de visitas diarias (45 días cerrados) de esos temas. Se prueban
//      variantes del título con mayúsculas ("real madrid" -> "Real madrid", "Real Madrid"); un
//      artículo inexistente queda como "sin datos", nunca como cero.
//   4. Normalización otra vez: las visitas se unen al mismo tema por su nombre normalizado.
//   5. Métricas de los días anteriores, para las series.
//   6. El agente trend_hunter clasifica la fecha más reciente que Wikipedia ya tiene completa (publica
//      las visitas con uno o dos días de retraso; lo deciden las propias métricas) y queda registrado.
//   7. El agente supervisor resume las ejecuciones.
//
// Requiere en la configuración DETECTAR_WIKIMEDIA_MODE=on y DETECTAR_HTTP_CONTACT. El token se
// lee del archivo de configuración o del entorno y nunca se imprime.
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

import { parseConfig } from "./local/config.mjs";

const WIKI_DAYS = 45;
const METRIC_DAYS = 10;
const MAX_TOPICS = Number(process.env.TENDENCIAS_MAX_TEMAS || 60);
const CHUNK = Number(process.env.TENDENCIAS_LOTE_WIKIPEDIA || 20); // DETECTAR_WIKIMEDIA_MAX_ARTICLES por defecto
const FORBIDDEN = /[#<>[\]|{}]/;

function fail(message) {
  console.error(`ERROR: ${message}`);
  process.exit(1);
}

function config() {
  const path = resolve(
    process.env.OFICINA_CONFIG ||
      (process.platform === "win32" && process.env.LOCALAPPDATA
        ? join(process.env.LOCALAPPDATA, "hack30x", "oficina", "oficina.env")
        : join(process.env.XDG_CONFIG_HOME || join(homedir(), ".config"), "hack30x", "oficina.env")),
  );
  const values = existsSync(path) ? parseConfig(readFileSync(path, "utf8")).values : {};
  const token = process.env.DETECTAR_ADMIN_TOKEN || values.DETECTAR_ADMIN_TOKEN;
  const base = (process.env.OFICINA_DETECTAR_URL || values.OFICINA_DETECTAR_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  if (!token) fail('falta DETECTAR_ADMIN_TOKEN (ejecute "npm run configurar")');
  if (!/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(base)) fail("OFICINA_DETECTAR_URL debe ser el backend local");
  return { token, base };
}

const { token, base } = config();

async function api(method, path, body) {
  const response = await fetch(`${base}/api/detectar${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json", "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${method} ${path} -> ${response.status} ${json.code ?? ""} ${json.detail ?? ""}`.trim());
  return json;
}

const day = (offset) => {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + offset)).toISOString().slice(0, 10);
};

function variants(title) {
  const t = title.trim().replace(/\s+/g, " ");
  if (!t || t.length > 120 || FORBIDDEN.test(t)) return [];
  const first = t.charAt(0).toLocaleUpperCase("es") + t.slice(1);
  const words = t
    .split(" ")
    .map((w) => (w.length > 3 || /^[a-z]/.test(w) === false ? w.charAt(0).toLocaleUpperCase("es") + w.slice(1) : w))
    .join(" ");
  return [...new Set([first, words])];
}

async function main() {
  try {
    await api("GET", "/health");
  } catch {
    fail(`el backend no responde en ${base}. Arránquelo con "npm run backend"`);
  }
  const yesterday = day(-1);

  console.log("1. Google Trends RSS (tendencias de hoy)…");
  const gtr = await api("POST", "/recolecciones", { fuentes: ["google_trends_rss"] });
  for (const f of gtr.fuentes) console.log(`   ${f.fuente}: ${f.estado}, ${f.observaciones_nuevas} observaciones nuevas, países ${gtr.paises.join(", ")}`);

  console.log("2. Normalización de temas…");
  const n1 = await api("POST", "/temas/normalizaciones", { data_mode: "real", limite: 5000 });
  console.log(`   ${n1.procesadas} observaciones procesadas, ${n1.temas_creados} temas nuevos`);

  const topics = [];
  for (let offset = 0; offset < 10_000; offset += 100) {
    const page = await api("GET", `/temas?data_mode=real&limite=100&desplazamiento=${offset}`);
    topics.push(...page.items);
    if (offset + page.items.length >= page.total) break;
  }
  const trending = topics
    .filter((t) => (t.vinculos_por_fuente.google_trends_rss ?? 0) > 0)
    .sort((a, b) => (b.vinculos_por_fuente.google_trends_rss ?? 0) - (a.vinculos_por_fuente.google_trends_rss ?? 0))
    .slice(0, MAX_TOPICS);
  const articles = [...new Set(trending.flatMap((t) => variants(t.nombre)))];
  console.log(`3. Wikipedia: ${trending.length} temas, ${articles.length} títulos a probar, ${day(-WIKI_DAYS)} a ${yesterday}…`);
  let found = 0;
  let missing = 0;
  for (let i = 0; i < articles.length; i += CHUNK) {
    const chunk = articles.slice(i, i + CHUNK);
    try {
      const run = await api("POST", "/recolecciones", {
        fuentes: ["wikimedia"],
        wikimedia: { articulos: chunk, desde: day(-WIKI_DAYS), hasta: yesterday },
      });
      const source = run.fuentes[0];
      const notFound = source.error?.codigo === "article_not_found" ? (source.error.detalle?.split(":").pop()?.split(",").length ?? 0) : 0;
      missing += notFound;
      found += chunk.length - notFound;
      console.log(`   lote ${i / CHUNK + 1}: ${source.estado}, ${source.observaciones_nuevas} días de visitas nuevos`);
    } catch (error) {
      console.log(`   lote ${i / CHUNK + 1}: no se pudo recolectar (${error.message.slice(0, 160)})`);
    }
  }
  console.log(`   títulos con artículo: ~${found}; sin artículo en Wikipedia: ~${missing}`);

  console.log("4. Normalización de las visitas…");
  const n2 = await api("POST", "/temas/normalizaciones", { data_mode: "real", limite: 5000 });
  console.log(`   ${n2.procesadas} observaciones procesadas, ${n2.temas_creados} temas nuevos`);

  console.log(`5. Métricas de los últimos ${METRIC_DAYS} días cerrados (para las series)…`);
  for (let i = METRIC_DAYS + 1; i >= 2; i--) await api("POST", "/metricas/calculos", { data_mode: "real", fecha_referencia: day(-i) });

  // Wikipedia publica cada día con uno o dos de retraso. Se clasifica la fecha más reciente cuyas
  // métricas NO indiquen días faltantes (motivo current_missing_days), según la propia API.
  let asOf = day(-4);
  for (const offset of [-2, -3, -4]) {
    const growth = await api("GET", `/metricas?data_mode=real&metrica=wiki_views_growth&fecha_referencia=${day(offset)}&limite=200`);
    const incomplete = growth.items.filter((m) => (m.motivo ?? "").startsWith("current_missing_days")).length;
    if (growth.items.length > 0 && incomplete / growth.items.length < 0.5) {
      asOf = day(offset);
      break;
    }
    console.log(`   ${day(offset)}: Wikipedia aún no tiene completo ese día (${incomplete} de ${growth.items.length} temas con días faltantes)`);
  }

  // El agente trend_hunter hace el trabajo del día (normaliza, mide y clasifica) y queda registrado:
  // la oficina muestra su ejecución real. Después, el supervisor resume lo ocurrido.
  console.log(`6. Agente trend_hunter: métricas y clasificación del ${asOf} (Wikipedia publica con retraso)…`);
  const hunter = await api("POST", "/agentes/trend_hunter/ejecuciones", { data_mode: "real", parametros: { fecha_referencia: asOf } });
  const stages = hunter.resultado?.pasos?.clasificacion;
  console.log(`   ejecución ${hunter.estado}${stages ? `, por etapa ${JSON.stringify(stages.por_etapa)}` : ""}`);
  const supervisor = await api("POST", "/agentes/supervisor/ejecuciones", { data_mode: "real", parametros: {} });
  console.log(`7. Agente supervisor: ${supervisor.estado}`);
  console.log("\nListo. Abra la oficina: http://127.0.0.1:3000/tendencias");
}

main().catch((error) => fail(error.message));
