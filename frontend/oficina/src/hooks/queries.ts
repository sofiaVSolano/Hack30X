"use client";

import { useEffect, useState } from "react";

import { buildUrl, getJson, type QueryParams } from "@/lib/api-client";
import {
  AgentList,
  AgentRunList,
  ClassificationPage,
  CollectionPage,
  LinkPage,
  MetricDefinitions,
  MetricPage,
  SchedulerStatus,
  StageRules,
  TopicDetail,
  TopicPage,
  type DataMode,
} from "@/lib/schemas";

import { useOficinaQuery } from "./useOficinaQuery";

/** Frecuencia de sondeo de las vistas operativas. */
export const OPERATIONAL_POLL_MS = 30_000;

export const useAgents = (mode: DataMode, pollMs?: number) =>
  useOficinaQuery({ path: "/agentes", params: { data_mode: mode }, schema: AgentList, pollMs });

export const useAgentRuns = (agentId: string | null, mode: DataMode, limit = 20, pollMs?: number) =>
  useOficinaQuery({
    path: `/agentes/${encodeURIComponent(agentId ?? "_")}/ejecuciones`,
    params: { data_mode: mode, limite: limit },
    schema: AgentRunList,
    pollMs,
    enabled: agentId !== null,
  });

export const useScheduler = (pollMs?: number) =>
  useOficinaQuery({ path: "/programador", schema: SchedulerStatus, pollMs });

export const useCollections = (mode: DataMode, limit = 5, pollMs?: number) =>
  useOficinaQuery({ path: "/recolecciones", params: { data_mode: mode, limite: limit }, schema: CollectionPage, pollMs });

export const useTopics = (mode: DataMode, params: QueryParams = {}) =>
  useOficinaQuery({ path: "/temas", params: { data_mode: mode, ...params }, schema: TopicPage });

export const useTopic = (topicId: string | null, mode: DataMode) =>
  useOficinaQuery({
    path: `/temas/${encodeURIComponent(topicId ?? "_")}`,
    params: { data_mode: mode },
    schema: TopicDetail,
    enabled: topicId !== null,
  });

export const useLinks = (mode: DataMode, params: QueryParams = {}, enabled = true) =>
  useOficinaQuery({ path: "/temas/vinculos", params: { data_mode: mode, ...params }, schema: LinkPage, enabled });

export const useMetricDefinitions = () => useOficinaQuery({ path: "/metricas/definiciones", schema: MetricDefinitions });

export const useMetrics = (mode: DataMode, params: QueryParams = {}, enabled = true) =>
  useOficinaQuery({ path: "/metricas", params: { data_mode: mode, ...params }, schema: MetricPage, enabled });

export const useClassifications = (mode: DataMode, params: QueryParams = {}, enabled = true) =>
  useOficinaQuery({ path: "/clasificaciones", params: { data_mode: mode, ...params }, schema: ClassificationPage, enabled });

export const useStageRules = () => useOficinaQuery({ path: "/clasificaciones/reglas", schema: StageRules });

// --- nombres de temas ------------------------------------------------------------------------

const topicNames = new Map<string, Promise<string | null>>();

/**
 * Resuelve el nombre de los temas con `GET /temas/{id}` (una vez por tema y modo). Si falla,
 * el nombre queda vacío y se muestra el identificador: nunca se inventa un nombre.
 */
export function useTopicNames(ids: string[], mode: DataMode): Record<string, string | null> {
  const [names, setNames] = useState<Record<string, string | null>>({});
  const key = [...new Set(ids)].sort().join(",");
  useEffect(() => {
    let alive = true;
    const unique = key ? key.split(",") : [];
    for (const id of unique) {
      const cacheKey = `${mode}:${id}`;
      let pending = topicNames.get(cacheKey);
      if (!pending) {
        pending = getJson(buildUrl(`/temas/${encodeURIComponent(id)}`, { data_mode: mode }), TopicDetail)
          .then((detail) => detail.tema.nombre)
          .catch(() => {
            topicNames.delete(cacheKey);
            return null;
          });
        topicNames.set(cacheKey, pending);
      }
      void pending.then((name) => {
        if (alive) setNames((prev) => (prev[id] === name ? prev : { ...prev, [id]: name }));
      });
    }
    return () => {
      alive = false;
    };
  }, [key, mode]);
  return names;
}

export function clearTopicNameCache(): void {
  topicNames.clear();
}
