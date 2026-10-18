import "server-only";

import { z, type ZodType } from "zod";

import {
  BatchOut,
  CrearHealth,
  CrearOptions,
  CrearTopicPage,
  GapOut,
  GapPage,
  GapRules,
  ProposalDetail,
  ProposalOut,
  ProposalPage,
  VERDICTS,
} from "@/lib/crear/schemas";
import { DATA_MODES } from "@/lib/schemas";

/**
 * Lista CERRADA de operaciones de CREAR que el navegador puede pedir: ruta del backend,
 * método, segmentos y parámetros admitidos, cuerpo (solo POST) y esquema de la respuesta.
 * Lo que no está aquí no se puede consultar ni enviar.
 */
type Rule = (value: string) => boolean;

export interface CrearEndpoint {
  method: "GET" | "POST";
  /** Ruta bajo /api/crear; `{nombre}` se sustituye por el segmento validado. */
  path: string;
  segments: Record<string, RegExp>;
  query: Record<string, Rule>;
  /** Esquema estricto del cuerpo JSON (solo POST). */
  body?: ZodType;
  /** Documento binario en vez de JSON (solo el PDF de un lote). */
  binary?: "application/pdf";
  schema: ZodType;
}

const oneOf =
  (values: readonly string[]): Rule =>
  (value) =>
    values.includes(value);

const intIn =
  (min: number, max: number): Rule =>
  (value) =>
    /^\d{1,6}$/.test(value) && Number(value) >= min && Number(value) <= max;

const matches =
  (pattern: RegExp): Rule =>
  (value) =>
    pattern.test(value);

const isoDate: Rule = (value) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(value);
};

const searchText: Rule = (value) => value.trim().length >= 2 && value.length <= 100 && !/[\u0000-\u001f\u007f]/.test(value);

export const TOPIC_ID = /^tpc_[0-9a-f]{16}$/;
export const PROPOSAL_ID = /^prp_[0-9a-f]{16}$/;
export const BATCH_ID = /^lot_[0-9a-f]{16}$/;
const CATALOG_ID = /^[a-z_]{2,40}$/;
const COUNTRY = /^[A-Z]{2}$/;

const dataMode = oneOf(DATA_MODES);
const offset = intIn(0, 10_000);

// Texto libre: sin caracteres de control. El backend vuelve a validar todo con su catálogo.
const freeText = (max: number) => z.string().max(max).regex(/^[^\u0000-\u001f\u007f]*$/);

export const BatchBody = z
  .object({
    data_mode: z.enum(DATA_MODES),
    origen: z.enum(["tema", "brecha", "manual"]),
    tema_id: z.string().regex(TOPIC_ID).nullish(),
    tema_texto: freeText(120).nullish(),
    fecha_referencia: z.string().refine(isoDate).nullish(),
    audiencia: z.string().regex(CATALOG_ID).optional(),
    audiencia_detalle: freeText(200).nullish(),
    plataforma: z.string().regex(CATALOG_ID),
    pais: z.string().regex(COUNTRY).nullish(),
  })
  .strict();
export type BatchBody = z.infer<typeof BatchBody>;

export const RegenerationBody = z
  .object({
    data_mode: z.enum(DATA_MODES),
    enfoque: z.enum(["educativo", "controversial", "narrativo"]).optional(),
    audiencia: z.string().regex(CATALOG_ID).optional(),
    audiencia_detalle: freeText(200).nullish(),
    plataforma: z.string().regex(CATALOG_ID).optional(),
    pais: z.string().regex(COUNTRY).nullish(),
    indicacion: freeText(300).nullish(),
  })
  .strict();
export type RegenerationBody = z.infer<typeof RegenerationBody>;

export const CREAR_ENDPOINTS = {
  salud: { method: "GET", path: "/health", segments: {}, query: {}, schema: CrearHealth },
  opciones: { method: "GET", path: "/opciones", segments: {}, query: {}, schema: CrearOptions },
  temas: {
    method: "GET",
    path: "/temas",
    segments: {},
    query: { data_mode: dataMode, q: searchText, limite: intIn(1, 100), desplazamiento: offset },
    schema: CrearTopicPage,
  },
  brechas: {
    method: "GET",
    path: "/brechas",
    segments: {},
    query: {
      data_mode: dataMode,
      fecha_referencia: isoDate,
      veredicto: oneOf(VERDICTS),
      limite: intIn(1, 100),
      desplazamiento: offset,
    },
    schema: GapPage,
  },
  reglas: { method: "GET", path: "/brechas/reglas", segments: {}, query: {}, schema: GapRules },
  brecha: {
    method: "GET",
    path: "/brechas/{tema}",
    segments: { tema: TOPIC_ID },
    query: { data_mode: dataMode, fecha_referencia: isoDate },
    schema: GapOut,
  },
  propuestas: {
    method: "GET",
    path: "/propuestas",
    segments: {},
    query: {
      data_mode: dataMode,
      tema_id: matches(TOPIC_ID),
      lote_id: matches(BATCH_ID),
      limite: intIn(1, 100),
      desplazamiento: offset,
    },
    schema: ProposalPage,
  },
  propuesta: {
    method: "GET",
    path: "/propuestas/{propuesta}",
    segments: { propuesta: PROPOSAL_ID },
    query: { data_mode: dataMode },
    schema: ProposalDetail,
  },
  pdf: {
    method: "GET",
    path: "/lotes/{lote}/pdf",
    segments: { lote: BATCH_ID },
    query: { data_mode: dataMode },
    binary: "application/pdf",
    schema: z.unknown(),
  },
  generar: { method: "POST", path: "/propuestas", segments: {}, query: {}, body: BatchBody, schema: BatchOut },
  regenerar: {
    method: "POST",
    path: "/propuestas/{propuesta}/regeneraciones",
    segments: { propuesta: PROPOSAL_ID },
    query: {},
    body: RegenerationBody,
    schema: ProposalOut,
  },
} satisfies Record<string, CrearEndpoint>;

export type CrearEndpointId = keyof typeof CREAR_ENDPOINTS;
