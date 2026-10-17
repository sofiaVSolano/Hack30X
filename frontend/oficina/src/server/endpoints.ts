import "server-only";

import type { ZodType } from "zod";

import {
  AgentList,
  AgentRunList,
  ClassificationPage,
  COLLECTION_STATUSES,
  CollectionPage,
  DATA_MODES,
  Health,
  LINK_STATUSES,
  LinkPage,
  METRIC_STATUSES,
  MetricDefinitions,
  MetricPage,
  SchedulerStatus,
  SOURCES,
  STAGES,
  StageRules,
  TopicDetail,
  TopicPage,
} from "@/lib/schemas";

/**
 * Lista CERRADA de lecturas que el navegador puede pedir. Cada entrada fija la ruta de
 * DETECTAR, los segmentos y parámetros admitidos (con su validación) y el esquema de la
 * respuesta. No hay ruta comodín: lo que no está aquí no se puede consultar.
 */
type Rule = (value: string) => boolean;

export interface EndpointSpec {
  /** Ruta bajo /api/detectar; `{nombre}` se sustituye por el segmento validado. */
  path: string;
  segments: Record<string, RegExp>;
  query: Record<string, Rule>;
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

// Texto libre de búsqueda: 2-100 caracteres imprimibles, sin caracteres de control.
const searchText: Rule = (value) => value.trim().length >= 2 && value.length <= 100 && !/[\u0000-\u001f\u007f]/.test(value);

export const AGENT_ID = /^[a-z][a-z0-9_]{2,63}$/;
export const TOPIC_ID = /^tpc_[0-9a-f]{16}$/;

const dataMode = oneOf(DATA_MODES);
const offset = intIn(0, 10_000);
const topicId = matches(TOPIC_ID);

export const ENDPOINTS = {
  salud: { path: "/health", segments: {}, query: {}, schema: Health },
  agentes: { path: "/agentes", segments: {}, query: { data_mode: dataMode }, schema: AgentList },
  agenteEjecuciones: {
    path: "/agentes/{agente}/ejecuciones",
    segments: { agente: AGENT_ID },
    query: { data_mode: dataMode, limite: intIn(1, 100) },
    schema: AgentRunList,
  },
  programador: { path: "/agentes/programador", segments: {}, query: {}, schema: SchedulerStatus },
  recolecciones: {
    path: "/recolecciones",
    segments: {},
    query: { data_mode: dataMode, estado: oneOf(COLLECTION_STATUSES), limite: intIn(1, 100), desplazamiento: offset },
    schema: CollectionPage,
  },
  temas: {
    path: "/temas",
    segments: {},
    query: { data_mode: dataMode, q: searchText, limite: intIn(1, 100), desplazamiento: offset },
    schema: TopicPage,
  },
  tema: { path: "/temas/{tema}", segments: { tema: TOPIC_ID }, query: { data_mode: dataMode }, schema: TopicDetail },
  vinculos: {
    path: "/temas/vinculos",
    segments: {},
    query: {
      data_mode: dataMode,
      estado: oneOf(LINK_STATUSES),
      fuente: oneOf(SOURCES),
      tema_id: topicId,
      limite: intIn(1, 100),
      desplazamiento: offset,
    },
    schema: LinkPage,
  },
  metricas: {
    path: "/metricas",
    segments: {},
    query: {
      data_mode: dataMode,
      tema_id: topicId,
      fuente: oneOf(SOURCES),
      metrica: matches(/^[a-z0-9_]{1,64}$/),
      estado: oneOf(METRIC_STATUSES),
      fecha_referencia: isoDate,
      limite: intIn(1, 200),
      desplazamiento: offset,
    },
    schema: MetricPage,
  },
  definiciones: { path: "/metricas/definiciones", segments: {}, query: {}, schema: MetricDefinitions },
  clasificaciones: {
    path: "/clasificaciones",
    segments: {},
    query: {
      data_mode: dataMode,
      tema_id: topicId,
      fuente: oneOf(SOURCES),
      etapa: oneOf(STAGES),
      version: matches(/^[a-z0-9.-]{1,40}$/),
      fecha_referencia: isoDate,
      incluir_reemplazadas: oneOf(["true", "false"]),
      limite: intIn(1, 100),
      desplazamiento: offset,
    },
    schema: ClassificationPage,
  },
  reglas: { path: "/clasificaciones/reglas", segments: {}, query: {}, schema: StageRules },
} satisfies Record<string, EndpointSpec>;

export type EndpointId = keyof typeof ENDPOINTS;
