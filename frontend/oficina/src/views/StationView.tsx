"use client";

import { Hourglass } from "lucide-react";

import { AgentDetails } from "@/components/agents/AgentPanels";
import { ZONE, type ModuleId } from "@/components/office/scene";
import { ModeBadge } from "@/components/ui/Badges";
import { EmptyState, QueryView, RefreshControl } from "@/components/ui/States";
import { OPERATIONAL_POLL_MS, useAgents } from "@/hooks/queries";
import { useDataMode } from "@/hooks/useDataMode";
import type { Agent } from "@/lib/schemas";

/** Aviso honesto de un módulo que todavía no existe: qué hará y qué no hay. */
export function ModulePending({ module }: { module: ModuleId }) {
  const zone = ZONE[module];
  return (
    <div className="notice notice--info" role="note">
      <Hourglass size={18} aria-hidden="true" color="var(--info)" />
      <div>
        <p className="notice__title">{zone.module} está en preparación</p>
        <p>
          {zone.purpose} Este computador no tiene todavía herramientas propias: no muestra análisis, resultados ni
          puntuaciones, porque el módulo no los produce.
        </p>
      </div>
    </div>
  );
}

const MODULE_OF: Record<string, ModuleId> = {
  detectar: "detectar",
  entender: "entender",
  crear: "crear",
  validar: "validar",
  transversal: "coordinacion",
};

/** Computador del puesto de un agente: su ficha real y su historial, sin inventar actividad. */
export function StationView({ agentId }: { agentId: string }) {
  const mode = useDataMode();
  const agents = useAgents(mode, OPERATIONAL_POLL_MS);
  return (
    <QueryView query={agents} skeletonLines={6}>
      {(data) => {
        const agent: Agent | undefined = data.agentes.find((a) => a.id === agentId);
        if (!agent) {
          return (
            <EmptyState title="Este puesto no tiene un agente registrado">
              La API no devuelve ningún agente con el identificador <code>{agentId}</code> en este modo.
            </EmptyState>
          );
        }
        const module = MODULE_OF[agent.alcance];
        return (
          <div className="stack" style={{ gap: 18, maxWidth: 980 }}>
            <header className="page-head">
              <div>
                <h1 className="page-title">{agent.nombre}</h1>
                <p className="page-lede">
                  Puesto de <span className="mono">{agent.id}</span> en {module ? ZONE[module].room : "la oficina"}. Ficha y
                  ejecuciones registradas por la API. Modo <ModeBadge mode={mode} />.
                </p>
              </div>
              <RefreshControl queries={[agents]} />
            </header>
            {module && !ZONE[module].ready ? <ModulePending module={module} /> : null}
            <AgentDetails agent={agent} mode={mode} />
          </div>
        );
      }}
    </QueryView>
  );
}

/** Puesto de VALIDAR: no hay módulo ni agentes asignados; se dice lo que dice la API. */
export function ValidationView() {
  const mode = useDataMode();
  const agents = useAgents(mode);
  return (
    <div className="stack" style={{ gap: 18, maxWidth: 820 }}>
      <header className="page-head">
        <div>
          <h1 className="page-title">Sala de validación</h1>
          <p className="page-lede">Puesto de VALIDAR, el último paso de HACK 30X: DETECTAR → ENTENDER → CREAR → VALIDAR.</p>
        </div>
      </header>
      <ModulePending module="validar" />
      <section className="panel" aria-labelledby="validar-agentes">
        <h2 id="validar-agentes" className="panel__title">
          Agentes asignados a VALIDAR
        </h2>
        <QueryView query={agents} skeletonLines={2}>
          {(data) => {
            const assigned = data.agentes.filter((a) => a.alcance === "validar");
            return assigned.length ? (
              <ul className="structured__list" style={{ marginTop: 10 }}>
                {assigned.map((a) => (
                  <li key={a.id}>
                    {a.nombre} (<span className="mono">{a.id}</span>)
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted" style={{ marginTop: 8 }}>
                El registro de agentes no tiene ningún agente asignado a VALIDAR todavía.
              </p>
            );
          }}
        </QueryView>
      </section>
    </div>
  );
}
