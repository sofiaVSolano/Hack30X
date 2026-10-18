import { CircleCheck, CircleDashed, CircleHelp, Equal, FileText, Sparkles, Split, type LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/Badges";
import { ENGINE, RESULT, VERDICT } from "@/lib/crear/labels";
import type { Engine, SourceResult, Verdict } from "@/lib/crear/schemas";

const VERDICT_ICON: Record<Verdict, LucideIcon> = {
  brecha_confirmada: CircleCheck,
  brecha_por_confirmar: CircleHelp,
  senales_mixtas: Split,
  sin_brecha: Equal,
  datos_insuficientes: CircleDashed,
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const spec = VERDICT[verdict];
  return (
    <Badge tone={spec.tone} icon={VERDICT_ICON[verdict]} title={spec.hint}>
      {spec.text}
    </Badge>
  );
}

export function ResultBadge({ result }: { result: SourceResult }) {
  const spec = RESULT[result];
  return <Badge tone={spec.tone}>{spec.text}</Badge>;
}

/** Motor con el que se generó (o se generará) una propuesta. */
export function EngineBadge({ engine, model }: { engine: string | Engine; model?: string | null }) {
  const id = typeof engine === "string" ? engine : engine.id;
  const modelName = typeof engine === "string" ? model : engine.modelo;
  const isClaude = id === "claude";
  return (
    <Badge tone={isClaude ? "info" : "neutral"} icon={isClaude ? Sparkles : FileText}>
      {ENGINE[id] ?? id}
      {isClaude && modelName ? (
        <span className="mono" translate="no">
          {" "}
          {modelName}
        </span>
      ) : null}
    </Badge>
  );
}
