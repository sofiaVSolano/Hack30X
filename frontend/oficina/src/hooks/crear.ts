"use client";

import { buildUrl, getJson, type QueryParams } from "@/lib/api-client";
import { postJson } from "@/lib/crear/client";
import {
  BatchOut,
  CrearOptions,
  CrearTopicPage,
  GapPage,
  ProposalDetail,
  ProposalOut,
  ProposalPage,
  type CreativeContext,
} from "@/lib/crear/schemas";
import type { DataMode } from "@/lib/schemas";

import { useOficinaQuery } from "./useOficinaQuery";

export const useCrearOptions = () => useOficinaQuery({ path: "/crear/opciones", schema: CrearOptions });

export const useGaps = (mode: DataMode, params: QueryParams = {}) =>
  useOficinaQuery({ path: "/crear/brechas", params: { data_mode: mode, limite: 100, ...params }, schema: GapPage });

export const useCrearTopics = (mode: DataMode, params: QueryParams = {}, enabled = true) =>
  useOficinaQuery({ path: "/crear/temas", params: { data_mode: mode, limite: 20, ...params }, schema: CrearTopicPage, enabled });

export const useProposalHistory = (mode: DataMode) =>
  useOficinaQuery({ path: "/crear/propuestas", params: { data_mode: mode, limite: 100 }, schema: ProposalPage });

export interface BatchRequest {
  data_mode: DataMode;
  origen: "tema" | "brecha" | "manual";
  tema_id?: string | null;
  tema_texto?: string | null;
  audiencia: string;
  audiencia_detalle?: string | null;
  plataforma: string;
  pais?: string | null;
}

export interface RegenerationRequest {
  data_mode: DataMode;
  enfoque?: string;
  audiencia?: string;
  audiencia_detalle?: string | null;
  plataforma?: string;
  pais?: string | null;
  indicacion?: string | null;
}

export const generateBatch = (body: BatchRequest) => postJson("/crear/propuestas", body, BatchOut);

export const regenerateProposal = (id: string, body: RegenerationRequest) =>
  postJson(`/crear/propuestas/${encodeURIComponent(id)}/regeneraciones`, body, ProposalOut);

/** Un lote completo (todas sus versiones) y el contexto con que se creó, para reabrirlo. */
export async function loadBatch(
  mode: DataMode,
  batchId: string,
): Promise<{ proposals: ProposalOut[]; context: CreativeContext | null }> {
  const page = await getJson(buildUrl("/crear/propuestas", { data_mode: mode, lote_id: batchId, limite: 100 }), ProposalPage);
  const first = page.items[0];
  if (!first) return { proposals: [], context: null };
  const detail = await getJson(buildUrl(`/crear/propuestas/${encodeURIComponent(first.id)}`, { data_mode: mode }), ProposalDetail);
  return { proposals: page.items, context: detail.contexto };
}
