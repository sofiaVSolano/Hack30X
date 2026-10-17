"use client";

import { RunStatusBadge, ModeBadge } from "@/components/ui/Badges";
import { SortHeader, useSort } from "@/components/ui/SortHeader";
import { Time } from "@/components/ui/Time";
import { durationMs, formatDuration } from "@/lib/format";
import { label, TRIGGER } from "@/lib/labels";
import type { AgentRun } from "@/lib/schemas";

type Column = "solicitado" | "estado" | "disparador" | "duracion";

export function RunsTable({
  runs,
  onSelect,
  showAgent = false,
}: {
  runs: AgentRun[];
  onSelect: (run: AgentRun) => void;
  showAgent?: boolean;
}) {
  const { sorted, sort, toggle } = useSort<AgentRun, Column>(
    runs,
    {
      solicitado: (r) => r.solicitado,
      estado: (r) => r.estado,
      disparador: (r) => r.disparador,
      duracion: (r) => durationMs(r.inicio, r.fin),
    },
    { key: "solicitado", direction: "desc" },
  );
  return (
    <div className="table-wrap" tabIndex={0}>
      <table className="table">
        <caption className="visually-hidden">Ejecuciones registradas</caption>
        <thead>
          <tr>
            <SortHeader label="Solicitada" column="solicitado" sort={sort} onToggle={toggle} />
            {showAgent ? <th scope="col">Agente</th> : null}
            <SortHeader label="Estado" column="estado" sort={sort} onToggle={toggle} />
            <SortHeader label="Disparador" column="disparador" sort={sort} onToggle={toggle} />
            <SortHeader label="Duración" column="duracion" sort={sort} onToggle={toggle} />
            <th scope="col">Detalle</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((run) => (
            <tr key={run.id}>
              <td>
                <Time value={run.solicitado} />
                <div className="faint small mono">{run.id}</div>
              </td>
              {showAgent ? <td className="mono small">{run.agente}</td> : null}
              <td>
                <div className="row">
                  <RunStatusBadge status={run.estado} />
                  {run.data_mode === "simulated" ? <ModeBadge mode="simulated" /> : null}
                </div>
                {run.codigo_error ? <div className="faint small mono">{run.codigo_error}</div> : null}
              </td>
              <td>{label(TRIGGER, run.disparador)}</td>
              <td title={durationMs(run.inicio, run.fin) === null ? "Sin inicio o fin registrados" : undefined}>
                {formatDuration(durationMs(run.inicio, run.fin))}
              </td>
              <td>
                <button type="button" className="btn" onClick={() => onSelect(run)}>
                  Ver
                  <span className="visually-hidden"> ejecución {run.id}</span>
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
