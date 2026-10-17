"use client";

import { useState } from "react";

import { formatDay, formatMetricValue, unitLabel } from "@/lib/format";
import type { ScopeSeries } from "@/lib/series";

import styles from "./MetricChart.module.css";

const COLORS = ["#b6e36b", "#6cc8f4", "#f2b85a", "#c9adff", "#58d6a0", "#ff8a7d"];
// Además del color, cada ámbito tiene su trazo (accesible sin color y en blanco y negro).
const DASHES = ["", "6 4", "2 4", "10 4 2 4", "1 3", "14 6"];
const W = 720;
const H = 280;
const PAD = { left: 64, right: 56, top: 30, bottom: 36 };
const DAY = 86_400_000;

const axisNumber = new Intl.NumberFormat("es", { maximumFractionDigits: 3 });

const toDay = (d: string) => Math.round(new Date(`${d}T00:00:00Z`).getTime() / DAY);

/**
 * Serie temporal de UNA métrica (una fuente, una unidad). Cada ámbito es una línea. Los
 * tramos sin días consecutivos no se unen; los días insuficientes se marcan en el eje con ×.
 */
export function MetricChart({
  series,
  unit,
  metric,
  source,
  synthetic = false,
}: {
  series: ScopeSeries[];
  unit: string;
  metric: string;
  source?: string;
  synthetic?: boolean;
}) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [hover, setHover] = useState<{ scope: string; date: string; value: number } | null>(null);
  const visible = series.filter((s) => !hidden.has(s.scope));

  const allDates = series.flatMap((s) => [...s.points.map((p) => p.date), ...s.insufficient]);
  const days = allDates.map(toDay);
  const minDay = Math.min(...days);
  const maxDay = Math.max(...days);
  const values = visible.flatMap((s) => s.points.map((p) => p.value));
  let lo = values.length ? Math.min(...values) : 0;
  let hi = values.length ? Math.max(...values) : 1;
  if (lo === hi) {
    lo -= Math.abs(lo) * 0.1 || 1;
    hi += Math.abs(hi) * 0.1 || 1;
  }
  const pad = (hi - lo) * 0.08;
  lo -= pad;
  hi += pad;

  const x = (date: string) =>
    PAD.left + (maxDay === minDay ? 0.5 : (toDay(date) - minDay) / (maxDay - minDay)) * (W - PAD.left - PAD.right);
  const y = (value: number) => PAD.top + (1 - (value - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => lo + (hi - lo) * t);
  const firstDate = allDates.length ? allDates.reduce((a, b) => (a < b ? a : b)) : "";
  const lastDate = allDates.length ? allDates.reduce((a, b) => (a > b ? a : b)) : "";

  return (
    <figure className={styles.figure}>
      <div className={styles.legend} role="group" aria-label="Ámbitos de la serie">
        {series.map((s, i) => (
          <button
            key={s.scope}
            type="button"
            className={styles.legendItem}
            aria-pressed={!hidden.has(s.scope)}
            onClick={() =>
              setHidden((prev) => {
                const next = new Set(prev);
                if (next.has(s.scope)) next.delete(s.scope);
                else next.add(s.scope);
                return next;
              })
            }
          >
            <svg className={styles.swatch} viewBox="0 0 24 8" aria-hidden="true">
              <line x1="1" y1="4" x2="23" y2="4" stroke={COLORS[i % COLORS.length]} strokeWidth="2.5" strokeDasharray={DASHES[i % DASHES.length]} />
            </svg>
            {s.scope}
            <span className="faint small">({s.points.length} valores)</span>
          </button>
        ))}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className={styles.svg}
        role="img"
        aria-label={`Serie de ${metric} en ${unitLabel(unit)}, del ${formatDay(firstDate)} al ${formatDay(lastDate)}. Los valores exactos están en la tabla.`}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className={styles.grid} />
            <text x={PAD.left - 8} y={y(t) + 4} className={styles.axisText} textAnchor="end">
              {axisNumber.format(t)}
            </text>
          </g>
        ))}
        <text x={PAD.left - 8} y={14} className={styles.axisText} textAnchor="end">
          {unitLabel(unit)}
        </text>
        {lo < 0 && hi > 0 ? <line x1={PAD.left} x2={W - PAD.right} y1={y(0)} y2={y(0)} className={styles.zero} /> : null}
        <text x={PAD.left} y={H - 10} className={styles.axisText}>
          {formatDay(firstDate)}
        </text>
        <text x={W - PAD.right} y={H - 10} className={styles.axisText} textAnchor="end">
          {formatDay(lastDate)}
        </text>
        {series.map((s, i) =>
          hidden.has(s.scope) ? null : (
            <g key={s.scope} style={{ color: COLORS[i % COLORS.length] }}>
              {s.segments
                .filter((segment) => segment.length > 1)
                .map((segment) => (
                  <polyline
                    key={segment[0]!.date}
                    points={segment.map((p) => `${x(p.date)},${y(p.value)}`).join(" ")}
                    className={styles.line}
                    strokeDasharray={DASHES[i % DASHES.length] || undefined}
                  />
                ))}
              {s.points.map((p) => (
                <circle
                  key={p.date}
                  cx={x(p.date)}
                  cy={y(p.value)}
                  r={hover?.scope === s.scope && hover.date === p.date ? 5.5 : 3.5}
                  className={styles.point}
                  onMouseEnter={() => setHover({ scope: s.scope, ...p })}
                  onMouseLeave={() => setHover(null)}
                >
                  <title>{`${s.scope} · ${formatDay(p.date)}: ${formatMetricValue(p.value, unit)} ${unitLabel(unit)}`}</title>
                </circle>
              ))}
              {s.points.length ? (
                <text
                  x={x(s.points.at(-1)!.date) + 8}
                  y={y(s.points.at(-1)!.value) + 4}
                  className={styles.endLabel}
                >
                  {formatMetricValue(s.points.at(-1)!.value, unit)}
                </text>
              ) : null}
              {s.insufficient.map((d) => (
                <text key={d} x={x(d)} y={H - PAD.bottom + 14} className={styles.gap} textAnchor="middle">
                  ×<title>{`${s.scope} · ${formatDay(d)}: datos insuficientes (sin valor)`}</title>
                </text>
              ))}
            </g>
          ),
        )}
      </svg>
      <figcaption className={styles.caption}>
        {hover ? (
          <span>
            <strong>{hover.scope}</strong> · {formatDay(hover.date)}: {formatMetricValue(hover.value, unit)} {unitLabel(unit)}
          </span>
        ) : (
          <span>
            {source ? `Fuente: ${source}. ` : ""}Del {formatDay(firstDate)} al {formatDay(lastDate)}, en {unitLabel(unit)}.
            {synthetic ? " Valores sintéticos de demostración." : ""} Una línea solo une días consecutivos; × marca días
            con datos insuficientes y los días sin registro no se rellenan.
          </span>
        )}
      </figcaption>
    </figure>
  );
}
