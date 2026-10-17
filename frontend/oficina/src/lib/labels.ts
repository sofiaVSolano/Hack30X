/**
 * Textos legibles de los valores que devuelve la API. Solo traducen: no agrupan, no
 * reinterpretan ni crean estados. Un valor desconocido se muestra tal cual.
 */
import type { Activity, AgentRunStatus, DataMode, Stage } from "./schemas";

export type Tone = "neutral" | "info" | "ok" | "warn" | "danger" | "sim";

export function label(map: Record<string, string>, value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return map[value] ?? value;
}

export const DATA_MODE_LABEL: Record<DataMode, string> = { real: "Real", simulated: "Simulado" };

export const ACTIVITY: Record<Activity, { text: string; tone: Tone; hint: string }> = {
  sin_ejecuciones: { text: "Sin ejecuciones", tone: "neutral", hint: "No hay ejecuciones registradas en este modo." },
  pendiente: { text: "Pendiente", tone: "info", hint: "La última ejecución registrada está pendiente." },
  en_curso: { text: "En curso", tone: "info", hint: "La última ejecución registrada está en curso." },
  completada: { text: "Completada", tone: "ok", hint: "La última ejecución registrada terminó como completada." },
  fallida: { text: "Fallida", tone: "danger", hint: "La última ejecución registrada falló." },
  bloqueada: { text: "Bloqueada", tone: "warn", hint: "La última ejecución registrada quedó bloqueada." },
};

export const RUN_STATUS: Record<AgentRunStatus, { text: string; tone: Tone }> = {
  pending: { text: "Pendiente", tone: "info" },
  running: { text: "En curso", tone: "info" },
  completed: { text: "Completada", tone: "ok" },
  failed: { text: "Fallida", tone: "danger" },
  blocked: { text: "Bloqueada", tone: "warn" },
};

export const STAGE: Record<Stage, { text: string; tone: Tone; hint: string }> = {
  emergente: { text: "Emergente", tone: "info", hint: "Etapa asignada por DETECTAR (stages-v1)." },
  acelerando: { text: "Acelerando", tone: "ok", hint: "Etapa asignada por DETECTAR (stages-v1)." },
  punto_maximo: { text: "Punto máximo", tone: "warn", hint: "Etapa asignada por DETECTAR (stages-v1)." },
  saturada: { text: "Saturada", tone: "danger", hint: "Etapa definida en el modelo; stages-v1 no la asigna." },
  datos_insuficientes: {
    text: "Datos insuficientes",
    tone: "neutral",
    hint: "DETECTAR no tiene evidencia suficiente para asignar una etapa.",
  },
};

export const SOURCE: Record<string, string> = {
  google_trends_rss: "Google Trends (RSS)",
  wikimedia: "Wikimedia",
  gdelt: "GDELT",
  youtube: "YouTube",
  instagram: "Instagram",
  x: "X",
};

export const SCOPE: Record<string, string> = {
  detectar: "DETECTAR",
  entender: "ENTENDER",
  crear: "CREAR",
  validar: "VALIDAR",
  transversal: "Transversal",
};

export const IMPLEMENTATION: Record<string, string> = {
  available: "Tarea implementada",
  planned: "Planificado (sin tarea)",
};

export const ASSIGNMENT: Record<string, string> = {
  provisional: "Asignación provisional",
  agreed: "Asignación acordada",
};

export const TRIGGER: Record<string, string> = {
  manual: "Manual",
  scheduled: "Programada",
  coordinator: "Coordinador",
};

export const SKIP_REASON: Record<string, string> = {
  sin_frecuencia: "Sin frecuencia configurada",
  no_implementado: "Sin tarea implementada",
  sin_data_mode: "Sin modo de datos configurado",
  recoleccion_no_permitida: "Recolección no permitida",
  fuente_no_habilitada: "Fuente no habilitada",
  recoleccion_solo_real: "La recolección solo admite modo real",
};

export const LINK_STATUS: Record<string, { text: string; tone: Tone }> = {
  linked: { text: "Vinculada", tone: "ok" },
  needs_review: { text: "Requiere revisión", tone: "warn" },
  unlinked: { text: "Sin vincular", tone: "neutral" },
  rejected: { text: "Rechazada", tone: "danger" },
};

export const LINK_RULE: Record<string, string> = {
  exact_normalized: "Coincidencia exacta normalizada",
  alias: "Alias registrado",
  new_topic: "Tema nuevo",
  manual_precedent: "Precedente manual",
  ambiguous_topic: "Tema ambiguo",
  disambiguation_base: "Base de desambiguación",
  insufficient_data: "Datos insuficientes",
  manual_correction: "Corrección manual",
};

export const EVIDENCE_ROLE: Record<string, { text: string; hint: string }> = {
  primary: { text: "Principal", hint: "Fuente validada que puede determinar la etapa." },
  complementary: { text: "Complementaria", hint: "Fuente no validada: solo se informa, nunca determina la etapa." },
  excluded: { text: "Excluida", hint: "No aporta: sin métricas utilizables o señal contradictoria." },
};

export const METRIC_STATUS: Record<string, { text: string; tone: Tone }> = {
  ok: { text: "Calculada", tone: "ok" },
  insufficient: { text: "Insuficiente", tone: "neutral" },
};

export const COLLECTION_STATUS: Record<string, { text: string; tone: Tone }> = {
  queued: { text: "En cola", tone: "info" },
  running: { text: "En curso", tone: "info" },
  ok: { text: "Correcta", tone: "ok" },
  partial: { text: "Parcial", tone: "warn" },
  failed: { text: "Fallida", tone: "danger" },
};

/** Unidad original de cada métrica (MetricUnit). El valor nunca se convierte. */
export const UNIT: Record<string, { text: string; decimals: number; signed?: boolean; prefix?: string }> = {
  captures: { text: "capturas", decimals: 0 },
  ratio: { text: "fracción (0–1)", decimals: 3 },
  ratio_difference: { text: "diferencia de fracciones", decimals: 3, signed: true },
  searches_lower_bound: { text: "búsquedas (cota inferior)", decimals: 0, prefix: "≥ " },
  views: { text: "visitas", decimals: 0 },
  views_per_day: { text: "visitas/día", decimals: 1 },
  articles: { text: "artículos", decimals: 0 },
  articles_per_day: { text: "artículos/día", decimals: 1 },
  growth_rate: { text: "tasa de crecimiento (fracción)", decimals: 3, signed: true },
  growth_rate_difference: { text: "diferencia de tasas", decimals: 3, signed: true },
  countries: { text: "países", decimals: 0 },
};
