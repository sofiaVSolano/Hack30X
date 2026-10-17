import { TriangleAlert } from "lucide-react";

import { ModeBadge, RunStatusBadge } from "@/components/ui/Badges";
import { Structured } from "@/components/ui/Structured";
import { Time } from "@/components/ui/Time";
import { durationMs, formatDuration } from "@/lib/format";
import { label, TRIGGER } from "@/lib/labels";
import type { AgentRun } from "@/lib/schemas";

/** Lista de limitaciones del resultado, si la tarea las declara (trend_hunter y supervisor lo hacen). */
function limitationsOf(result: Record<string, unknown> | null): string[] {
  const value = result?.limitaciones;
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

export function RunDetail({ run }: { run: AgentRun }) {
  const limitations = limitationsOf(run.resultado);
  const duration = durationMs(run.inicio, run.fin);
  return (
    <>
      <div className="row">
        <RunStatusBadge status={run.estado} />
        <ModeBadge mode={run.data_mode} />
      </div>
      <dl className="dl">
        <dt>Identificador</dt>
        <dd className="mono">{run.id}</dd>
        <dt>Agente</dt>
        <dd className="mono">{run.agente}</dd>
        <dt>Disparador</dt>
        <dd>{label(TRIGGER, run.disparador)}</dd>
        <dt>Solicitada</dt>
        <dd>
          <Time value={run.solicitado} />
        </dd>
        <dt>Inicio</dt>
        <dd>
          <Time value={run.inicio} />
        </dd>
        <dt>Fin</dt>
        <dd>
          <Time value={run.fin} />
        </dd>
        <dt>Duración</dt>
        <dd>{duration === null ? <span className="faint">No calculable: falta inicio o fin</span> : formatDuration(duration)}</dd>
      </dl>

      {run.codigo_error || run.detalle_error ? (
        <div className="notice notice--danger">
          <TriangleAlert size={18} aria-hidden="true" color="var(--danger)" />
          <div className="stack" style={{ gap: 4 }}>
            <p className="notice__title">Error registrado{run.codigo_error ? `: ${run.codigo_error}` : ""}</p>
            {run.detalle_error ? <p className="muted">{run.detalle_error}</p> : null}
          </div>
        </div>
      ) : null}

      {limitations.length ? (
        <section className="stack" aria-label="Limitaciones declaradas">
          <h3 className="panel__title">Limitaciones declaradas por la tarea</h3>
          <ul className="structured__list">
            {limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="stack">
        <h3 className="panel__title">Resultado registrado</h3>
        {run.resultado ? (
          <div className="code-block">
            <Structured value={run.resultado} />
          </div>
        ) : (
          <p className="muted">Esta ejecución no tiene resultado registrado.</p>
        )}
      </section>
    </>
  );
}
