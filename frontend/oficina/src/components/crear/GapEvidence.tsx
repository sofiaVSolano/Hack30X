import { ValidationBadge } from "@/components/ui/Badges";
import { SIDE_STATE } from "@/lib/crear/labels";
import type { Comparison } from "@/lib/crear/schemas";
import { label, SOURCE } from "@/lib/labels";

import { ResultBadge } from "./CrearBadges";

const integer = new Intl.NumberFormat("es", { maximumFractionDigits: 0 });

type Side = Comparison["ingles"];

/** Valor de un idioma en su unidad original; un idioma sin medir nunca se muestra como cero. */
function SideValue({ side, unit }: { side: Side; unit: string }) {
  if (side.estado !== "medido" || side.valor === null) {
    return <span className="faint">{SIDE_STATE[side.estado] ?? side.estado}</span>;
  }
  if (unit === "ratio") {
    const best = [...side.ambitos].filter((s) => s.valor !== null).sort((a, b) => (b.valor ?? 0) - (a.valor ?? 0))[0];
    return best && best.capturas_con_tema !== null && best.capturas_conocidas !== null ? (
      <span>
        {best.capturas_con_tema} de {best.capturas_conocidas} capturas{" "}
        <span className="faint mono" translate="no">
          {best.ambito}
        </span>
      </span>
    ) : (
      <span>{side.valor.toFixed(3)}</span>
    );
  }
  const noun = unit === "views" ? "visitas" : unit === "articles" ? "artículos" : unit;
  return (
    <span>
      {integer.format(side.valor)} {noun}
      {side.ambitos.length > 1 ? <span className="faint small"> ({side.ambitos.length} ámbitos)</span> : null}
    </span>
  );
}

export function GapEvidence({ comparisons }: { comparisons: Comparison[] }) {
  return (
    <div className="table-wrap" tabIndex={0}>
      <table className="table">
        <caption className="visually-hidden">Comparación inglés–español por fuente (7 días)</caption>
        <thead>
          <tr>
            <th scope="col">Fuente</th>
            <th scope="col">Inglés</th>
            <th scope="col">Español</th>
            <th scope="col">Resultado</th>
          </tr>
        </thead>
        <tbody>
          {comparisons.map((c) => (
            <tr key={c.fuente}>
              <td>
                <div className="stack" style={{ gap: 4 }}>
                  <span>{label(SOURCE, c.fuente)}</span>
                  {c.fuente_validada ? null : <ValidationBadge validated={false} />}
                </div>
              </td>
              <td>
                <SideValue side={c.ingles} unit={c.unidad} />
              </td>
              <td>
                <SideValue side={c.espanol} unit={c.unidad} />
              </td>
              <td>
                <div className="stack" style={{ gap: 4 }}>
                  <ResultBadge result={c.resultado} />
                  <span className="small">{c.explicacion}</span>
                  {c.tendencia ? <span className="small faint">{c.tendencia}</span> : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
