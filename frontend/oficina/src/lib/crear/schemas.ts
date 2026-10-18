/**
 * Esquemas de las respuestas de CREAR, transcritos de los modelos Pydantic reales
 * (backend/app/modules/crear/api/schemas.py y api/router.py).
 *
 * Igual que con DETECTAR: un campo obligatorio ausente o de otro tipo invalida la respuesta y
 * el intermediario responde 502 en lugar de mostrar datos incompletos. El veredicto de brechas
 * es una categoría con reglas explícitas, no una puntuación.
 */
import { z } from "zod";

import { DataMode, Source, Stage } from "@/lib/schemas";

export const VERDICTS = [
  "brecha_confirmada",
  "brecha_por_confirmar",
  "senales_mixtas",
  "sin_brecha",
  "datos_insuficientes",
] as const;
export const Verdict = z.enum(VERDICTS);
export type Verdict = z.infer<typeof Verdict>;

export const RESULTS = [
  "brecha",
  "solo_ingles",
  "paridad",
  "mas_fuerte_espanol",
  "sin_medicion_espanol",
  "sin_medicion_ingles",
  "insuficiente",
] as const;
export const SourceResult = z.enum(RESULTS);
export type SourceResult = z.infer<typeof SourceResult>;

export const APPROACHES = ["educativo", "controversial", "narrativo"] as const;
export const Approach = z.enum(APPROACHES);
export type Approach = z.infer<typeof Approach>;

export const ORIGINS = ["tema", "brecha", "manual"] as const;
export const Origin = z.enum(ORIGINS);
export type Origin = z.infer<typeof Origin>;

// --- opciones y salud ----------------------------------------------------------------------

export const Engine = z.object({ id: z.string(), nombre: z.string(), modelo: z.string().nullable(), detalle: z.string() });
export type Engine = z.infer<typeof Engine>;

export const CrearOptions = z.object({
  enfoques: z.array(z.object({ id: Approach, nombre: z.string(), descripcion: z.string() })),
  plataformas: z.array(z.object({ id: z.string(), nombre: z.string(), formato: z.string(), pautas: z.array(z.string()) })),
  audiencias: z.array(z.object({ id: z.string(), nombre: z.string(), descripcion: z.string(), tono: z.string() })),
  audiencia_por_defecto: z.string(),
  paises: z.array(z.object({ id: z.string(), nombre: z.string() })),
  motor: Engine,
});
export type CrearOptions = z.infer<typeof CrearOptions>;

export const CrearHealth = z.object({
  status: z.literal("ok"),
  module: z.literal("crear"),
  version: z.string(),
  reglas_brechas: z.string(),
  motor: Engine,
  time: z.string(),
});

// --- etapas, temas y brechas -----------------------------------------------------------------

export const StageInfo = z.object({
  etapa: Stage,
  motivo: z.string().nullable(),
  fecha_referencia: z.string(),
  version: z.string(),
  calibrado: z.boolean(),
});
export type StageInfo = z.infer<typeof StageInfo>;

const Scope = z.object({
  ambito: z.string(),
  valor: z.number().nullable(),
  crecimiento: z.number().nullable(),
  motivo: z.string().nullable(),
  capturas_con_tema: z.number().int().nullable(),
  capturas_conocidas: z.number().int().nullable(),
});

const Side = z.object({
  idioma: z.enum(["en", "es"]),
  estado: z.enum(["medido", "insuficiente", "sin_medicion"]),
  valor: z.number().nullable(),
  ambitos: z.array(Scope),
});

export const Comparison = z.object({
  fuente: Source,
  fuente_validada: z.boolean(),
  metrica: z.string(),
  unidad: z.string(),
  ingles: Side,
  espanol: Side,
  razon: z.number().nullable(),
  resultado: SourceResult,
  explicacion: z.string(),
  tendencia: z.string().nullable(),
});
export type Comparison = z.infer<typeof Comparison>;

export const GapOut = z.object({
  tema_id: z.string(),
  tema_nombre: z.string(),
  veredicto: Verdict,
  resumen: z.string(),
  etapa: StageInfo.nullable(),
  comparaciones: z.array(Comparison),
  notas: z.array(z.string()),
});
export type GapOut = z.infer<typeof GapOut>;

export const GapPage = z.object({
  data_mode: DataMode,
  fecha_referencia: z.string().nullable(),
  version: z.string(),
  calibrado: z.boolean(),
  total: z.number().int(),
  limite: z.number().int(),
  desplazamiento: z.number().int(),
  por_veredicto: z.record(z.string(), z.number().int()),
  items: z.array(GapOut),
  limitaciones: z.array(z.string()),
});
export type GapPage = z.infer<typeof GapPage>;

export const GapRules = z.object({
  version: z.string(),
  provisional: z.boolean(),
  calibrado: z.boolean(),
  parametros: z.record(z.string(), z.unknown()),
  parametros_sha256: z.string(),
  veredictos: z.record(z.string(), z.string()),
  resultados: z.record(z.string(), z.string()),
  metricas_usadas: z.record(z.string(), z.array(z.string())),
  limitaciones: z.array(z.string()),
});
export type GapRules = z.infer<typeof GapRules>;

export const CrearTopic = z.object({
  id: z.string(),
  nombre: z.string(),
  data_mode: DataMode,
  ambiguo: z.boolean(),
  vinculos_por_fuente: z.record(z.string(), z.number().int()),
  etapa: StageInfo.nullable(),
  veredicto_brecha: Verdict.nullable(),
});
export type CrearTopic = z.infer<typeof CrearTopic>;

export const CrearTopicPage = z.object({
  data_mode: DataMode,
  fecha_referencia: z.string().nullable(),
  total: z.number().int(),
  limite: z.number().int(),
  desplazamiento: z.number().int(),
  items: z.array(CrearTopic),
});
export type CrearTopicPage = z.infer<typeof CrearTopicPage>;

// --- propuestas --------------------------------------------------------------------------------

export const Fact = z.object({ clave: z.string(), texto: z.string(), fuente: z.string() });
export type Fact = z.infer<typeof Fact>;

export const CreativeContext = z.object({
  origen: Origin,
  data_mode: DataMode,
  tema_id: z.string().nullable(),
  tema_nombre: z.string(),
  fecha_referencia: z.string().nullable(),
  etapa: Stage.nullable(),
  etapa_calibrada: z.boolean().nullable(),
  veredicto_brecha: Verdict.nullable(),
  resumen_brecha: z.string().nullable(),
  hechos: z.array(Fact),
  limitaciones: z.array(z.string()),
});
export type CreativeContext = z.infer<typeof CreativeContext>;

export const ProposalContent = z.object({
  titulo: z.string(),
  gancho: z.string(),
  idea_central: z.string(),
  estructura: z.array(z.string()),
  formato: z.string(),
  llamado_a_la_accion: z.string(),
  adaptacion_latam: z.array(z.string()),
  palabras_clave: z.array(z.string()),
  precauciones: z.array(z.string()),
});
export type ProposalContent = z.infer<typeof ProposalContent>;

export const ProposalOut = z.object({
  id: z.string(),
  lote_id: z.string(),
  raiz_id: z.string(),
  padre_id: z.string().nullable(),
  version: z.number().int(),
  data_mode: DataMode,
  origen: Origin,
  tema_id: z.string().nullable(),
  tema_nombre: z.string(),
  enfoque: Approach,
  audiencia: z.string(),
  audiencia_detalle: z.string().nullable(),
  plataforma: z.string(),
  pais: z.string().nullable(),
  indicacion: z.string().nullable(),
  cambios: z.array(z.string()),
  contenido: ProposalContent,
  motor: z.string(),
  modelo: z.string().nullable(),
  aviso_motor: z.string().nullable(),
  cifras_sin_respaldo: z.array(z.string()),
  creado: z.string(),
});
export type ProposalOut = z.infer<typeof ProposalOut>;

export const BatchOut = z.object({
  lote_id: z.string(),
  data_mode: DataMode,
  contexto: CreativeContext,
  propuestas: z.array(ProposalOut),
});
export type BatchOut = z.infer<typeof BatchOut>;

export const ProposalDetail = z.object({
  propuesta: ProposalOut,
  versiones: z.array(ProposalOut),
  contexto: CreativeContext,
});
export type ProposalDetail = z.infer<typeof ProposalDetail>;

export const ProposalPage = z.object({
  data_mode: DataMode,
  total: z.number().int(),
  limite: z.number().int(),
  desplazamiento: z.number().int(),
  items: z.array(ProposalOut),
});
export type ProposalPage = z.infer<typeof ProposalPage>;
