/**
 * Construcción de series temporales a partir de valores de métricas ya calculados por DETECTAR.
 *
 * Reglas (E13):
 * - Una serie = una métrica, una fuente, una unidad, una versión y una ventana. Si los datos
 *   mezclan cualquiera de ellas, no se dibuja.
 * - Un ámbito (país, consulta...) es una serie separada; nunca se suman ámbitos.
 * - Solo los valores `ok` con número son puntos. `insufficient` es un hueco marcado.
 * - Días no consecutivos cortan la línea: un día ausente no se convierte en cero ni se interpola.
 */
import type { MetricValue } from "./schemas";

export interface SeriesPoint {
  date: string; // YYYY-MM-DD (fecha_referencia)
  value: number;
}

export interface ScopeSeries {
  scope: string;
  points: SeriesPoint[];
  /** Tramos de días consecutivos con valor; cada tramo se dibuja como una línea independiente. */
  segments: SeriesPoint[][];
  insufficient: string[];
}

export type SeriesResult =
  | { kind: "empty" }
  | { kind: "mixed"; reason: string }
  | { kind: "insufficient"; series: ScopeSeries[] }
  | { kind: "ok"; unit: string; metric: string; source: string; series: ScopeSeries[]; dates: string[] };

const DAY_MS = 86_400_000;

function dayIndex(date: string): number {
  return Math.round(new Date(`${date}T00:00:00Z`).getTime() / DAY_MS);
}

function distinct<T>(values: T[]): T[] {
  return [...new Set(values)];
}

export function buildSeries(values: MetricValue[]): SeriesResult {
  if (values.length === 0) return { kind: "empty" };

  const checks: [string, unknown[]][] = [
    ["métrica", distinct(values.map((v) => v.metrica))],
    ["fuente", distinct(values.map((v) => v.fuente))],
    ["unidad", distinct(values.map((v) => v.unidad))],
    ["versión de métricas", distinct(values.map((v) => v.version))],
    ["ventana", distinct(values.map((v) => v.ventana_dias))],
    ["modo de datos", distinct(values.map((v) => v.data_mode))],
  ];
  for (const [name, found] of checks) {
    if (found.length > 1) return { kind: "mixed", reason: `Los valores mezclan más de una ${name}; no se pueden representar en una sola serie.` };
  }

  const byScope = new Map<string, MetricValue[]>();
  for (const value of values) {
    const list = byScope.get(value.ambito) ?? [];
    list.push(value);
    byScope.set(value.ambito, list);
  }

  const series: ScopeSeries[] = [];
  for (const [scope, list] of [...byScope.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    const sorted = [...list].sort((a, b) => a.fecha_referencia.localeCompare(b.fecha_referencia));
    const points: SeriesPoint[] = [];
    const insufficient: string[] = [];
    const segments: SeriesPoint[][] = [];
    let current: SeriesPoint[] = [];
    let previousDay: number | null = null;
    for (const item of sorted) {
      const day = dayIndex(item.fecha_referencia);
      if (item.estado !== "ok" || item.valor === null) {
        insufficient.push(item.fecha_referencia);
        if (current.length) segments.push(current);
        current = [];
        previousDay = null;
        continue;
      }
      const point = { date: item.fecha_referencia, value: item.valor };
      points.push(point);
      if (previousDay !== null && day - previousDay !== 1 && current.length) {
        segments.push(current);
        current = [];
      }
      current.push(point);
      previousDay = day;
    }
    if (current.length) segments.push(current);
    series.push({ scope, points, segments, insufficient });
  }

  const first = values[0]!;
  if (!series.some((s) => s.points.length >= 2)) return { kind: "insufficient", series };
  const dates = distinct(values.map((v) => v.fecha_referencia)).sort();
  return { kind: "ok", unit: first.unidad, metric: first.metrica, source: first.fuente, series, dates };
}
