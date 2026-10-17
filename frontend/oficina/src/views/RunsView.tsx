"use client";

import { useRouter, useSearchParams } from "next/navigation";

import { AgentHistory } from "@/components/agents/AgentPanels";
import { ModeBadge } from "@/components/ui/Badges";
import { QueryView } from "@/components/ui/States";
import { useAgents } from "@/hooks/queries";
import { useDataMode, useModeHref } from "@/hooks/useDataMode";

const LIMITS = [20, 50, 100] as const;

export function RunsView() {
  const mode = useDataMode();
  const href = useModeHref();
  const router = useRouter();
  const params = useSearchParams();
  const agents = useAgents(mode);
  const limitParam = Number(params.get("limite"));
  const limit = (LIMITS as readonly number[]).includes(limitParam) ? limitParam : 20;

  const update = (agent: string, newLimit: number) =>
    router.replace(href("/ejecuciones", { agente: agent, ...(newLimit !== 20 ? { limite: String(newLimit) } : {}) }));

  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="page-title">Historial de ejecuciones</h1>
          <p className="page-lede">
            Ejecuciones registradas en <code>agent_runs</code> para un agente, de la más reciente a la más antigua. Modo{" "}
            <ModeBadge mode={mode} />.
          </p>
        </div>
      </header>
      <QueryView query={agents}>
        {(data) => {
          const ids = data.agentes.map((a) => a.id);
          const requested = params.get("agente");
          const agent = requested && ids.includes(requested) ? requested : (ids[0] ?? null);
          return (
            <section className="panel">
              <div className="filters">
                <label className="field">
                  Agente
                  <select className="select" value={agent ?? ""} onChange={(e) => update(e.target.value, limit)}>
                    {data.agentes.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.nombre} ({a.implementado ? "con tarea" : "sin tarea"})
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  Cantidad
                  <select className="select" value={limit} onChange={(e) => agent && update(agent, Number(e.target.value))}>
                    {LIMITS.map((n) => (
                      <option key={n} value={n}>
                        Últimas {n}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {agent ? <AgentHistory key={`${agent}-${limit}-${mode}`} agentId={agent} mode={mode} limit={limit} /> : null}
            </section>
          );
        }}
      </QueryView>
    </>
  );
}
