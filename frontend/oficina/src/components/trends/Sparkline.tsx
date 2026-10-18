import type { SeriesPoint } from "@/lib/series";

/**
 * Minigráfica de una serie real. Solo une días consecutivos (los tramos ya vienen cortados) y
 * no rellena huecos. Es decorativa para lectores de pantalla: el valor va en texto al lado.
 */
export function Sparkline({ segments, width = 132, height = 36 }: { segments: SeriesPoint[][]; width?: number; height?: number }) {
  const points = segments.flat();
  if (points.length < 2) return null;
  const days = points.map((p) => Date.parse(`${p.date}T00:00:00Z`));
  const values = points.map((p) => p.value);
  const [d0, d1] = [Math.min(...days), Math.max(...days)];
  const [v0, v1] = [Math.min(...values), Math.max(...values)];
  const x = (date: string) => 2 + ((Date.parse(`${date}T00:00:00Z`) - d0) / (d1 - d0 || 1)) * (width - 4);
  const y = (value: number) => height - 3 - ((value - v0) / (v1 - v0 || 1)) * (height - 6);
  const last = points.at(-1)!;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false">
      {segments
        .filter((s) => s.length > 1)
        .map((s) => (
          <polyline
            key={s[0]!.date}
            points={s.map((p) => `${x(p.date)},${y(p.value)}`).join(" ")}
            fill="none"
            stroke="var(--electric-text)"
            strokeWidth="2"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
      <circle cx={x(last.date)} cy={y(last.value)} r="3" fill="var(--electric-text)" />
    </svg>
  );
}
