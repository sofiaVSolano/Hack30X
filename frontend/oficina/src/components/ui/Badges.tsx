import {
  Ban,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock,
  FlaskConical,
  Loader,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { ACTIVITY, RUN_STATUS, STAGE, type Tone } from "@/lib/labels";
import type { Activity, AgentRunStatus, DataMode, Stage } from "@/lib/schemas";

const TONE_ICON: Record<Tone, LucideIcon> = {
  neutral: CircleDashed,
  info: Clock,
  ok: CircleCheck,
  warn: TriangleAlert,
  danger: CircleX,
  sim: FlaskConical,
};

export function Badge({
  tone,
  icon,
  children,
  title,
  outline,
}: {
  tone: Tone;
  icon?: LucideIcon | null;
  children: ReactNode;
  title?: string;
  outline?: boolean;
}) {
  const Icon = icon === undefined ? TONE_ICON[tone] : icon;
  return (
    <span className={`badge ${outline ? "badge--outline" : `badge--${tone}`}`} title={title}>
      {Icon ? <Icon size={13} aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

const ACTIVITY_ICON: Record<Activity, LucideIcon> = {
  sin_ejecuciones: CircleDashed,
  pendiente: Clock,
  en_curso: Loader,
  completada: CircleCheck,
  fallida: CircleX,
  bloqueada: Ban,
};

export function ActivityBadge({ activity }: { activity: Activity }) {
  const spec = ACTIVITY[activity];
  return (
    <Badge tone={spec.tone} icon={ACTIVITY_ICON[activity]} title={spec.hint}>
      {spec.text}
    </Badge>
  );
}

const RUN_ICON: Record<AgentRunStatus, LucideIcon> = {
  pending: Clock,
  running: Loader,
  completed: CircleCheck,
  failed: CircleX,
  blocked: Ban,
};

export function RunStatusBadge({ status }: { status: AgentRunStatus }) {
  const spec = RUN_STATUS[status];
  return (
    <Badge tone={spec.tone} icon={RUN_ICON[status]}>
      {spec.text}
    </Badge>
  );
}

/** Etapa como insignia de canal de guía de TV: un cuadro de color lleno con su nombre. */
export function StageBadge({ stage }: { stage: Stage }) {
  const spec = STAGE[stage];
  return (
    <span className="channel" data-stage={stage} title={spec.hint}>
      {spec.text}
    </span>
  );
}

export function ModeBadge({ mode }: { mode: DataMode }) {
  return mode === "simulated" ? (
    <Badge tone="sim">Simulado</Badge>
  ) : (
    <Badge tone="neutral" outline icon={null}>
      Real
    </Badge>
  );
}

export function CalibrationBadge({ calibrated }: { calibrated: boolean }) {
  return calibrated ? (
    <Badge tone="ok" icon={ShieldCheck}>
      Reglas calibradas
    </Badge>
  ) : (
    <Badge tone="warn" icon={ShieldAlert} title="Umbrales provisionales: no validados con datos reales.">
      Sin calibrar
    </Badge>
  );
}

export function ValidationBadge({ validated }: { validated: boolean }) {
  return validated ? (
    <Badge tone="neutral" icon={ShieldCheck}>
      Fuente validada
    </Badge>
  ) : (
    <Badge tone="warn" icon={ShieldAlert} title="La fuente no se ha validado con datos reales; nunca determina la etapa.">
      Fuente no validada
    </Badge>
  );
}
