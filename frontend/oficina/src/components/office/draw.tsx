import type { ReactNode } from "react";

import { HALF_H, HALF_W, iso, type Pt } from "./scene";

/** Mezcla un color hex con blanco (f > 1) o negro (f < 1). */
export function shade(hex: string, f: number): string {
  const n = parseInt(hex.slice(1), 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) =>
    Math.round(f >= 1 ? c + (255 - c) * (f - 1) : c * f),
  );
  return `#${ch.map((c) => Math.max(0, Math.min(255, c)).toString(16).padStart(2, "0")).join("")}`;
}

export const pts = (list: Pt[]) => list.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");

/**
 * Caja isométrica: se ven la tapa, la cara que mira a +y (izquierda) y la que mira a +x (derecha).
 * La luz llega desde arriba a la izquierda: tapa clara, cara derecha en sombra.
 */
export function Box({
  x,
  y,
  z = 0,
  dx,
  dy,
  dz,
  color,
  className,
}: {
  x: number;
  y: number;
  z?: number;
  dx: number;
  dy: number;
  dz: number;
  color: string;
  className?: string;
}) {
  const t = z + dz;
  return (
    <g className={className}>
      <polygon points={pts([iso(x, y + dy, z), iso(x + dx, y + dy, z), iso(x + dx, y + dy, t), iso(x, y + dy, t)])} fill={color} />
      <polygon points={pts([iso(x + dx, y, z), iso(x + dx, y + dy, z), iso(x + dx, y + dy, t), iso(x + dx, y, t)])} fill={shade(color, 0.72)} />
      <polygon points={pts([iso(x, y, t), iso(x + dx, y, t), iso(x + dx, y + dy, t), iso(x, y + dy, t)])} fill={shade(color, 1.16)} />
    </g>
  );
}

/** Elipse de un círculo horizontal de radio r (en unidades) a la altura z. */
export function isoEllipse(cx: number, cy: number, r: number, z = 0) {
  const [x, y] = iso(cx, cy, z);
  return { cx: x, cy: y, rx: r * HALF_W * Math.SQRT2, ry: r * HALF_H * Math.SQRT2 };
}

/**
 * Grupo que dibuja en el plano de una pantalla: coordenadas locales (u a la derecha, v hacia
 * abajo) sobre una cara que mira a +y (pendiente 0,5) o a +x (pendiente −0,5).
 */
export function OnPlane({ left, top, slope, children }: { left: number; top: number; slope: number; children: ReactNode }) {
  return <g transform={`matrix(1 ${slope} 0 1 ${left.toFixed(1)} ${top.toFixed(1)})`}>{children}</g>;
}
