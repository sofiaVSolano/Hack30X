/**
 * Lenguaje simple para la página «Tendencias». Solo traduce lo que devuelve la API (etapa,
 * motivo y regla aplicada por fuente); no crea juicios propios ni puntuaciones.
 */
import type { Classification, Stage } from "./schemas";

export const STAGE_PLAIN: Record<Stage, { title: string; sentence: string }> = {
  acelerando: { title: "Creciendo cada vez más rápido", sentence: "Su interés sube y además sube más rápido que la semana anterior." },
  emergente: { title: "Empezando a crecer", sentence: "Su interés empezó a subir hace poco, pero todavía no se acelera." },
  punto_maximo: { title: "En su punto más alto", sentence: "Subió la semana anterior y ahora se mantiene: probablemente ya no es temprano." },
  saturada: { title: "Saturada", sentence: "Las reglas actuales no asignan esta etapa." },
  datos_insuficientes: { title: "Sin señal clara", sentence: "No hay evidencia suficiente para decir en qué etapa está." },
};

// Reglas de stages-v1 por ámbito (backend/app/modules/detectar/stages/engine.py), en palabras simples.
const RULE_PLAIN: Record<string, string> = {
  W0: "No hay suficientes días de visitas en Wikipedia para medirlo.",
  W4: "Sus visitas suben, pero cada vez más despacio.",
  W6: "Sus visitas en Wikipedia están estables: ni suben ni bajan.",
  W7: "Sus visitas en Wikipedia están bajando.",
  W8: "Sus visitas suben poco, por debajo del umbral de crecimiento.",
};

const REASON_PLAIN: Record<string, string> = {
  sin_evidencia_temporal_suficiente: "No hay suficiente historial para medir su evolución.",
  solo_fuente_no_validada: "Solo aparece en una fuente que todavía no está validada.",
  senales_contradictorias: "Las fuentes dicen cosas distintas.",
};

/** Por qué un tema no tiene etapa clara, según la regla que aplicó el backend a Wikipedia. */
export function plainReason(item: Classification): string {
  const wiki = item.evidencia.find((e) => e.fuente === "wikimedia");
  const rules = (wiki?.ambitos ?? []).map((a) => a.rule).filter((r): r is string => typeof r === "string");
  const known = rules.find((r) => r in RULE_PLAIN);
  if (known) return RULE_PLAIN[known]!;
  return REASON_PLAIN[item.motivo ?? ""] ?? STAGE_PLAIN.datos_insuficientes.sentence;
}

/** Nombre para mostrar: los temas de Google Trends llegan en minúsculas. Solo cambia la primera letra. */
export function displayName(name: string): string {
  return name ? name.charAt(0).toLocaleUpperCase("es") + name.slice(1) : name;
}

const SOURCE_PLAIN: Record<string, string> = {
  google_trends_rss: "Google Trends",
  wikimedia: "Wikipedia",
  gdelt: "noticias (GDELT)",
};

export function plainSources(counts: Record<string, number>): string {
  const names = Object.keys(counts)
    .filter((k) => (counts[k] ?? 0) > 0)
    .map((k) => SOURCE_PLAIN[k] ?? k);
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} y ${names.at(-1)}`;
}
