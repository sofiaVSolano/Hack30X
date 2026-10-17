"use client";

import { useState } from "react";

import { AgentCard, AgentDrawer } from "@/components/agents/AgentPanels";
import { ModeBadge } from "@/components/ui/Badges";
import { QueryView, RefreshControl } from "@/components/ui/States";
import { OPERATIONAL_POLL_MS, useAgents } from "@/hooks/queries";
import { useDataMode } from "@/hooks/useDataMode";
import type { Agent } from "@/lib/schemas";

export function AgentsView() {
  const mode = useDataMode();
  const agents = useAgents(mode, OPERATIONAL_POLL_MS);
  const [selected, setSelected] = useState<Agent | null>(null);
  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="page-title">Agentes</h1>
          <p className="page-lede">
            Seis roles definidos. Solo los que tienen tarea implementada pueden completar ejecuciones; el resto aparece
            como planificado. Modo <ModeBadge mode={mode} />.
          </p>
        </div>
        <RefreshControl queries={[agents]} />
      </header>
      <QueryView query={agents} skeletonLines={8}>
        {(data) => (
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
            {data.agentes.map((agent) => (
              <AgentCard key={agent.id} agent={agent} onOpen={setSelected} />
            ))}
          </div>
        )}
      </QueryView>
      <AgentDrawer agent={selected} mode={mode} onClose={() => setSelected(null)} />
    </>
  );
}
