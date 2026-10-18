/**
 * Textos legibles de los valores de CREAR. Solo traducen: un valor desconocido se muestra tal cual.
 */
import type { Tone } from "@/lib/labels";

import type { Approach, Origin, SourceResult, Verdict } from "./schemas";

export const VERDICT: Record<Verdict, { text: string; tone: Tone; hint: string }> = {
  brecha_confirmada: {
    text: "Brecha confirmada",
    tone: "ok",
    hint: "Una fuente validada muestra mucha más atención en inglés y ninguna fuente validada lo contradice.",
  },
  brecha_por_confirmar: {
    text: "Brecha por confirmar",
    tone: "info",
    hint: "Hay atención en inglés, pero el lado en español no se midió o solo lo sugiere GDELT (no validada).",
  },
  senales_mixtas: {
    text: "Señales mixtas",
    tone: "warn",
    hint: "Las fuentes validadas apuntan en direcciones opuestas: una al inglés y otra al español.",
  },
  sin_brecha: {
    text: "Sin brecha",
    tone: "neutral",
    hint: "La atención es parecida en ambos idiomas o mayor en español.",
  },
  datos_insuficientes: {
    text: "Datos insuficientes",
    tone: "neutral",
    hint: "No hay mediciones en inglés que permitan comparar.",
  },
};

export const RESULT: Record<SourceResult, { text: string; tone: Tone }> = {
  brecha: { text: "Más atención en inglés", tone: "ok" },
  solo_ingles: { text: "Solo en inglés", tone: "ok" },
  paridad: { text: "Atención parecida", tone: "neutral" },
  mas_fuerte_espanol: { text: "Más atención en español", tone: "warn" },
  sin_medicion_espanol: { text: "Español sin medir", tone: "info" },
  sin_medicion_ingles: { text: "Inglés sin medir", tone: "neutral" },
  insuficiente: { text: "Datos insuficientes", tone: "neutral" },
};

export const APPROACH: Record<Approach, string> = {
  educativo: "Educativo",
  controversial: "Controversial",
  narrativo: "Narrativo",
};

export const ORIGIN: Record<Origin, string> = {
  brecha: "Brecha inglés–español",
  tema: "Tema detectado",
  manual: "Tema escrito a mano",
};

export const CHANGE: Record<string, string> = {
  enfoque: "enfoque",
  audiencia: "audiencia",
  plataforma: "plataforma",
  pais: "país",
  indicacion: "indicación",
  nueva_variante: "otra variante",
};

export const ENGINE: Record<string, string> = {
  "plantillas-v1": "Plantillas (sin IA)",
  claude: "Claude",
};

export const SIDE_STATE: Record<string, string> = {
  medido: "medido",
  insuficiente: "datos insuficientes",
  sin_medicion: "sin medición",
};
