import { Power, PowerOff } from "lucide-react";

import { Badge } from "@/components/ui/Badges";
import { Time } from "@/components/ui/Time";
import type { SchedulerStatus } from "@/lib/schemas";

/** Estado operativo del programador. No es el estado de ningún agente. */
export function SchedulerSummary({ status }: { status: SchedulerStatus }) {
  const programmed = status.agentes.filter((a) => a.programado).length;
  const tickMoment = typeof status.ultimo_tick?.momento === "string" ? status.ultimo_tick.momento : null;
  return (
    <div className="stack">
      <div className="row">
        {status.habilitado ? (
          <Badge tone="ok" icon={Power}>
            Habilitado
          </Badge>
        ) : (
          <Badge tone="neutral" icon={PowerOff}>
            Deshabilitado
          </Badge>
        )}
        {status.en_ejecucion ? (
          <Badge tone="info">Bucle en ejecución</Badge>
        ) : (
          <Badge tone="neutral" outline icon={null}>
            Bucle detenido
          </Badge>
        )}
      </div>
      <dl className="dl small">
        <dt>Agentes programados</dt>
        <dd>
          {programmed} de {status.agentes.length}
        </dd>
        <dt>Revisión del plan</dt>
        <dd>cada {status.intervalo_tick_segundos} s</dd>
        <dt>Último tick</dt>
        <dd>{tickMoment ? <Time value={tickMoment} /> : <span className="faint">Ninguno en este proceso</span>}</dd>
      </dl>
    </div>
  );
}
