"use client";

import { Bot, CircleHelp } from "lucide-react";
import { useState } from "react";

import { ActivityBadge, Badge, ModeBadge, RunStatusBadge } from "@/components/ui/Badges";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState, QueryView } from "@/components/ui/States";
import { Time } from "@/components/ui/Time";
import { useAgentRuns } from "@/hooks/queries";
import { formatMinutes } from "@/lib/format";
import { ASSIGNMENT, IMPLEMENTATION, label, RUN_STATUS, SCOPE, SOURCE } from "@/lib/labels";
import { AGENT_RUN_STATUSES, type Agent, type AgentRun, type AgentRunStatus, type DataMode } from "@/lib/schemas";

import { RunDetail } from "./RunDetail";
import { RunsTable } from "./RunsTable";

export function ImplementationBadge({ agent }: { agent: Agent }) {
  return agent.implementado ? (
    <Badge tone="ok" icon={Bot}>
      {label(IMPLEMENTATION, agent.estado_implementacion)}
    </Badge>
  ) : (
    <Badge tone="neutral" outline icon={CircleHelp}>
      {label(IMPLEMENTATION, agent.estado_implementacion)}
    </Badge>
  );
}

export function AgentCard({ agent, onOpen }: { agent: Agent; onOpen: (agent: Agent) => void }) {
  const last = agent.ultima_ejecucion;
  return (
    <article className="panel stack" aria-labelledby={`agente-${agent.id}`} style={{ gap: 14 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <h3 id={`agente-${agent.id}`} style={{ fontSize: 18 }}>
            {agent.nombre}
          </h3>
          <p className="faint small mono" translate="no">
            {agent.id} · {label(SCOPE, agent.alcance)}
          </p>
        </div>
        <ImplementationBadge agent={agent} />
      </div>
      <p className="muted small">{agent.descripcion}</p>
      <dl className="dl small">
        <dt>Actividad</dt>
        <dd>
          <ActivityBadge activity={agent.actividad} />
        </dd>
        <dt>Última ejecución</dt>
        <dd>
          {last ? (
            <span className="row">
              <RunStatusBadge status={last.estado} /> <Time value={last.solicitado} />
            </span>
          ) : (
            <span className="faint">Ninguna registrada</span>
          )}
        </dd>
        <dt>Frecuencia</dt>
        <dd>{agent.frecuencia_minutos === null ? <span className="faint">Sin programar</span> : formatMinutes(agent.frecuencia_minutos)}</dd>
      </dl>
      <div>
        <button type="button" className="btn" onClick={() => onOpen(agent)}>
          Detalle e historial<span className="visually-hidden"> de {agent.nombre}</span>
        </button>
      </div>
    </article>
  );
}

function Chips({ items, map }: { items: string[]; map?: Record<string, string> }) {
  if (!items.length) return <span className="faint">Ninguna</span>;
  return (
    <ul className="chips">
      {items.map((item) => (
        <li key={item}>
          <Badge tone="neutral" outline icon={null}>
            {map ? label(map, item) : item}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

/** Historial de un agente con filtro de estado sobre las ejecuciones cargadas. */
export function AgentHistory({ agentId, mode, limit = 20 }: { agentId: string; mode: DataMode; limit?: number }) {
  const runs = useAgentRuns(agentId, mode, limit);
  const [status, setStatus] = useState<AgentRunStatus | "">("");
  const [selected, setSelected] = useState<AgentRun | null>(null);
  return (
    <QueryView query={runs}>
      {(data) => {
        const visible = status ? data.ejecuciones.filter((r) => r.estado === status) : data.ejecuciones;
        return (
          <div className="stack">
            <div className="filters" style={{ marginBottom: 0 }}>
              <label className="field">
                Estado
                <select className="select" value={status} onChange={(e) => setStatus(e.target.value as AgentRunStatus | "")}>
                  <option value="">Todos</option>
                  {AGENT_RUN_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {RUN_STATUS[s].text}
                    </option>
                  ))}
                </select>
              </label>
              <p className="faint small">
                Ejecuciones cargadas: {data.ejecuciones.length} (máximo {data.limite}, más recientes primero)
              </p>
            </div>
            {data.ejecuciones.length === 0 ? (
              <EmptyState title="Sin ejecuciones registradas">
                Este agente no tiene ejecuciones en modo {mode === "real" ? "real" : "simulado"}.
              </EmptyState>
            ) : visible.length === 0 ? (
              <EmptyState title="Ninguna ejecución con ese estado">Entre las {data.ejecuciones.length} cargadas.</EmptyState>
            ) : (
              <RunsTable runs={visible} onSelect={setSelected} />
            )}
            <Dialog
              open={selected !== null}
              onClose={() => setSelected(null)}
              title="Ejecución"
              subtitle={selected ? <span className="mono">{selected.id}</span> : null}
              variant="modal"
            >
              {selected ? <RunDetail run={selected} /> : null}
            </Dialog>
          </div>
        );
      }}
    </QueryView>
  );
}

/** Ficha completa de un agente (datos de la API) con su historial de ejecuciones. */
export function AgentDetails({ agent, mode }: { agent: Agent; mode: DataMode }) {
  return (
    <>
          <div className="row">
            <ImplementationBadge agent={agent} />
            <ActivityBadge activity={agent.actividad} />
            <Badge tone="neutral" outline icon={null}>
              {label(ASSIGNMENT, agent.estado_asignacion)}
            </Badge>
          </div>
          <p>{agent.descripcion}</p>
          <dl className="dl">
            <dt>Responsabilidad</dt>
            <dd>{agent.responsabilidad}</dd>
            <dt>Módulo</dt>
            <dd>{label(SCOPE, agent.alcance)}</dd>
            <dt>Colabora con</dt>
            <dd>
              <Chips items={agent.colabora_con} map={SCOPE} />
            </dd>
            <dt>Fuentes permitidas</dt>
            <dd>
              <Chips items={agent.fuentes_permitidas} map={SOURCE} />
            </dd>
            <dt>Herramientas</dt>
            <dd>
              <Chips items={agent.herramientas_permitidas} />
            </dd>
            <dt>Frecuencia</dt>
            <dd>{agent.frecuencia_minutos === null ? "Sin programar" : formatMinutes(agent.frecuencia_minutos)}</dd>
          </dl>
          {agent.preguntas_abiertas.length ? (
            <section className="stack">
              <h3 className="panel__title">Preguntas abiertas</h3>
              <ul className="structured__list">
                {agent.preguntas_abiertas.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </section>
          ) : null}
          {!agent.implementado ? (
            <div className="notice notice--info">
              <CircleHelp size={18} aria-hidden="true" color="var(--info)" />
              <p>
                Este rol está definido pero <strong>no tiene tarea implementada</strong>. Si se solicitara una ejecución,
                quedaría registrada como bloqueada.
              </p>
            </div>
          ) : null}
          <section className="stack">
            <h3 className="panel__title">Historial de ejecuciones</h3>
            <AgentHistory agentId={agent.id} mode={mode} />
          </section>
    </>
  );
}

export function AgentDrawer({ agent, mode, onClose }: { agent: Agent | null; mode: DataMode; onClose: () => void }) {
  return (
    <Dialog
      open={agent !== null}
      onClose={onClose}
      title={agent?.nombre ?? ""}
      subtitle={
        agent ? (
          <span className="row">
            <span className="mono">{agent.id}</span>
            <ModeBadge mode={mode} />
          </span>
        ) : null
      }
    >
      {agent ? <AgentDetails agent={agent} mode={mode} /> : null}
    </Dialog>
  );
}
