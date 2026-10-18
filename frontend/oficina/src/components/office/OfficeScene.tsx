import type { Activity, Agent } from "@/lib/schemas";

import { Box, isoEllipse, OnPlane, pts, shade } from "./draw";
import {
  FLOOR,
  iso,
  MONITOR,
  screenOf,
  STATIONS,
  WORLD_H,
  WORLD_W,
  ZONES,
  type ModuleId,
  type Station,
} from "./scene";
import styles from "./OfficeScene.module.css";

const C = {
  floor: "#0a1430",
  corridor: "#08102a",
  zone: { detectar: "#11214a", entender: "#0e1b3e", crear: "#0e1b3e", coordinacion: "#0f1d42", validar: "#0d1a3b" } as Record<ModuleId, string>,
  wallBack: "#16254d",
  wallSide: "#122043",
  cap: "#24376b",
  glass: "#14295c",
  desk: "#2b3d6d",
  cabinet: "#1f2d55",
  leg: "#1a264b",
  monitor: "#0a1122",
  keyboard: "#33467a",
  mug: "#c9d4f0",
  chair: "#2a3a68",
  chairBase: "#151f3f",
  pot: "#2b3d6d",
  leaf: "#2f8a64",
  leafLight: "#3fae7d",
  paper: "#dbe4f8",
};

// --- personas -----------------------------------------------------------------------------

const SKIN = ["#f1c7a0", "#c98d5e", "#8d5a3b", "#e0a979", "#a86b45"];
const HAIR = ["#16130f", "#5a3a22", "#8a5a2b", "#2a2620", "#c9c2b0"];
const PANTS = ["#1b2547", "#2a2620", "#30334a"];
/** Camiseta fija por agente conocido, para distinguirlos; el resto, por su identificador. */
const SHIRT: Record<string, string> = {
  trend_hunter: "#3d7bff",
  format_hunter: "#e07a1f",
  analyst: "#2fae73",
  audience_filter: "#9a6cf0",
  strategist: "#f2c230",
  supervisor: "#e8eefc",
};

function look(who: string) {
  let h = 0;
  for (const c of who) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return {
    skin: SKIN[h % SKIN.length]!,
    hair: HAIR[(h >>> 3) % HAIR.length]!,
    shirt: SHIRT[who] ?? ["#3d7bff", "#e07a1f", "#2fae73", "#9a6cf0"][(h >>> 6) % 4]!,
    pants: PANTS[(h >>> 9) % PANTS.length]!,
    longHair: ((h >>> 12) & 1) === 1,
  };
}

/** Persona sentada, vista de espaldas frente a su monitor. Solo teclea si `working`. */
function Person({ at, who, working }: { at: readonly [number, number]; who: string; working: boolean }) {
  const p = look(who);
  return (
    <g className={styles.person} transform={`translate(${at[0].toFixed(1)} ${at[1].toFixed(1)})`}>
      <path d="M-10.5 0 L-11.5 -22 Q-11.5 -30 -4 -31 L4 -31 Q11.5 -30 11.5 -22 L10.5 0 Z" fill={p.shirt} />
      {working ? (
        <g className={styles.typing}>
          <rect x="-13.5" y="-27" width="5" height="13" rx="2.5" fill={shade(p.shirt, 0.82)} transform="rotate(28 -11 -27)" />
          <rect x="8.5" y="-27" width="5" height="13" rx="2.5" fill={shade(p.shirt, 0.82)} transform="rotate(-28 11 -27)" />
        </g>
      ) : (
        <g>
          <rect x="-14" y="-28" width="5" height="19" rx="2.5" fill={shade(p.shirt, 0.82)} />
          <rect x="9" y="-28" width="5" height="19" rx="2.5" fill={shade(p.shirt, 0.82)} />
        </g>
      )}
      {p.longHair ? <rect x="-7.5" y="-44" width="15" height="17" rx="5" fill={p.hair} /> : null}
      <ellipse cx="-8.3" cy="-41.5" rx="1.6" ry="2.6" fill={p.skin} />
      <ellipse cx="8.3" cy="-41.5" rx="1.6" ry="2.6" fill={p.skin} />
      <circle cx="0" cy="-42.5" r="8.5" fill={p.skin} />
      <circle cx="0" cy="-43.6" r="8.7" fill={p.hair} />
    </g>
  );
}

// --- pantallas ----------------------------------------------------------------------------

export type ScreenState = "vacante" | "trabajando" | Activity | "desconocido" | "consulta" | "preparacion";

/** Contenido de una pantalla en coordenadas locales (w × h). Nunca simula datos. */
function ScreenFace({ w, h, state, glyph }: { w: number; h: number; state: ScreenState; glyph?: string }) {
  const cx = w / 2;
  const cy = h / 2;
  const k = Math.min(w, h) / 22;
  return (
    <g className={styles.screen} data-state={state}>
      <rect className={styles.glass} x="0" y="0" width={w} height={h} rx="1" />
      {state === "trabajando" ? (
        <g className={styles.code}>
          <rect className={styles.line} x={w * 0.14} y={h * 0.24} width={w * 0.5} height={h * 0.11} rx={h * 0.05} />
          <rect className={styles.line} x={w * 0.14} y={h * 0.45} width={w * 0.68} height={h * 0.11} rx={h * 0.05} />
          <rect className={styles.line} x={w * 0.14} y={h * 0.66} width={w * 0.36} height={h * 0.11} rx={h * 0.05} />
        </g>
      ) : null}
      {state === "completada" ? (
        <path className={styles.glyph} data-tone="ok" d={`M${cx - 5 * k} ${cy} l${3.5 * k} ${3.5 * k} l${7 * k} ${-7 * k}`} strokeWidth={1.6 * k} />
      ) : null}
      {state === "fallida" ? (
        <path className={styles.glyph} data-tone="danger" d={`M${cx - 4 * k} ${cy - 4 * k} l${8 * k} ${8 * k} M${cx + 4 * k} ${cy - 4 * k} l${-8 * k} ${8 * k}`} strokeWidth={1.6 * k} />
      ) : null}
      {state === "bloqueada" ? (
        <g className={styles.glyph} data-tone="warn" strokeWidth={1.5 * k}>
          <circle cx={cx} cy={cy} r={5 * k} />
          <path d={`M${cx - 3.5 * k} ${cy + 3.5 * k} l${7 * k} ${-7 * k}`} />
        </g>
      ) : null}
      {state === "pendiente" ? <circle className={styles.dotPending} cx={cx} cy={cy} r={2 * k} /> : null}
      {state === "sin_ejecuciones" || state === "preparacion" ? <circle className={styles.standby} cx={cx} cy={cy} r={1.4 * k} /> : null}
      {state === "desconocido" ? (
        <path className={styles.glyph} data-tone="muted" strokeWidth={1.4 * k} d={`M${cx - 3 * k} ${cy - 3 * k} q0 ${-3 * k} ${3 * k} ${-3 * k} q${3 * k} 0 ${3 * k} ${3 * k} q0 ${2.4 * k} ${-3 * k} ${3.4 * k} v${1.6 * k}`} />
      ) : null}
      {state === "consulta" && glyph ? <Glyph kind={glyph} w={w} h={h} /> : null}
    </g>
  );
}

/** Icono de la sección a la que da acceso una pantalla de pared (ilustración, no datos). */
function Glyph({ kind, w, h }: { kind: string; w: number; h: number }) {
  const g = styles.icon;
  if (kind === "bars") {
    return (
      <g className={g}>
        {[0.32, 0.55, 0.42, 0.72, 0.5].map((v, i) => (
          <rect key={i} x={w * (0.14 + i * 0.15)} y={h * (0.82 - v * 0.7)} width={w * 0.09} height={h * v * 0.7} rx="1" />
        ))}
      </g>
    );
  }
  if (kind === "tags") {
    return (
      <g className={g}>
        {[
          [0.12, 0.22, 0.34],
          [0.5, 0.22, 0.38],
          [0.12, 0.45, 0.46],
          [0.62, 0.45, 0.26],
          [0.12, 0.68, 0.3],
          [0.46, 0.68, 0.4],
        ].map(([x, y, ww], i) => (
          <rect key={i} x={w * x!} y={h * y!} width={w * ww!} height={h * 0.13} rx={h * 0.065} />
        ))}
      </g>
    );
  }
  if (kind === "stages") {
    return (
      <g>
        {[
          [styles.stageLime, 0.2],
          [styles.stageBlue, 0.44],
          [styles.stageAmber, 0.68],
        ].map(([cls, y], i) => (
          <g key={i}>
            <rect className={cls as string} x={w * 0.12} y={h * (y as number)} width={w * 0.2} height={h * 0.13} rx="1" />
            <rect className={g} x={w * 0.38} y={h * ((y as number) + 0.035)} width={w * (0.48 - i * 0.08)} height={h * 0.06} rx="1" />
          </g>
        ))}
      </g>
    );
  }
  if (kind === "runs") {
    return (
      <g className={g}>
        {[0.22, 0.42, 0.62, 0.82].map((y, i) => (
          <g key={i}>
            <circle cx={w * 0.16} cy={h * y - h * 0.04} r={h * 0.045} />
            <rect x={w * 0.26} y={h * y - h * 0.075} width={w * (0.6 - (i % 2) * 0.16)} height={h * 0.07} rx="1" />
          </g>
        ))}
      </g>
    );
  }
  // reloj
  return (
    <g className={g}>
      <circle cx={w / 2} cy={h / 2} r={h * 0.3} fill="none" strokeWidth={h * 0.06} className={styles.iconStroke} />
      <path d={`M${w / 2} ${h / 2} v${-h * 0.18} M${w / 2} ${h / 2} h${h * 0.14}`} fill="none" strokeWidth={h * 0.06} className={styles.iconStroke} />
    </g>
  );
}

// --- puestos ------------------------------------------------------------------------------

export interface StationView {
  state: ScreenState;
  person: boolean;
  working: boolean;
}

/** Estado visible de un puesto a partir de la API. `agents === null`: estado desconocido. */
export function stationView(station: Station, agents: Map<string, Agent> | null): StationView {
  if (station.kind === "wall") return { state: "consulta", person: false, working: false };
  if (!station.agent) return { state: "preparacion", person: false, working: false };
  if (agents === null) return { state: "desconocido", person: false, working: false };
  const agent = agents.get(station.agent);
  if (!agent) return { state: "desconocido", person: false, working: false };
  if (!agent.implementado) return { state: "vacante", person: false, working: false };
  const working = agent.actividad === "pendiente" || agent.actividad === "en_curso";
  return { state: working ? "trabajando" : agent.actividad, person: true, working };
}

function DeskStation({ station, view }: { station: Extract<Station, { kind: "desk" }>; view: StationView }) {
  const { x, y } = station;
  const s = screenOf(station);
  const seat = view.person ? { cx: x + 0.95, cy: y + 1.72 } : { cx: x + 1.3, cy: y + 1.98 };
  const ring = isoEllipse(x + 1.05, y + 1.2, 1.55, 0.01);
  return (
    <>
      <ellipse className={styles.ring} {...ring} />
      {[
        [0.06, 0.06],
        [1.86, 0.06],
        [0.06, 0.96],
      ].map(([lx, ly], i) => (
        <Box key={i} x={x + lx!} y={y + ly!} dx={0.08} dy={0.08} dz={0.72} color={C.leg} />
      ))}
      <Box x={x + 1.35} y={y + 0.12} dx={0.55} dy={0.85} dz={0.66} color={C.cabinet} />
      <Box x={x + 0.06} y={y + 0.96} dx={0.08} dy={0.08} dz={0.72} color={C.leg} />
      <Box x={x} y={y} z={0.72} dx={2} dy={1.1} dz={0.07} color={C.desk} />
      <Box x={x + 0.8} y={y + 0.14} z={0.79} dx={0.42} dy={0.22} dz={0.02} color={C.monitor} />
      <Box x={x + 0.95} y={y + 0.18} z={0.8} dx={0.12} dy={0.08} dz={0.1} color={C.monitor} />
      <Box
        x={x + MONITOR.from - 0.04}
        y={y + 0.12}
        z={MONITOR.z0 - 0.05}
        dx={MONITOR.to - MONITOR.from + 0.08}
        dy={MONITOR.face - 0.12}
        dz={MONITOR.z1 - MONITOR.z0 + 0.1}
        color={C.monitor}
      />
      {view.state === "trabajando" ? <ellipse className={styles.glow} {...isoEllipse(x + 1, y + 0.9, 0.9, 0.8)} /> : null}
      <OnPlane left={s.left} top={s.top} slope={s.slope}>
        <ScreenFace w={s.width} h={s.height} state={view.state} />
      </OnPlane>
      {view.working ? (
        <circle className={styles.live} cx={iso(x + MONITOR.to - 0.08, y + MONITOR.face, MONITOR.z0 - 0.025)[0]} cy={iso(x + MONITOR.to - 0.08, y + MONITOR.face, MONITOR.z0 - 0.025)[1]} r="1.7" />
      ) : null}
      <Box x={x + 0.62} y={y + 0.5} z={0.79} dx={0.78} dy={0.24} dz={0.025} color={C.keyboard} />
      <Box x={x + 1.68} y={y + 0.56} z={0.79} dx={0.12} dy={0.12} dz={0.13} color={C.mug} />
      <g className={styles.chair} data-vacant={!view.person}>
        <ellipse {...isoEllipse(seat.cx, seat.cy, 0.34, 0.02)} fill={C.chairBase} />
        <Box x={seat.cx - 0.04} y={seat.cy - 0.04} z={0.05} dx={0.08} dy={0.08} dz={0.36} color={C.chairBase} />
        <Box x={seat.cx - 0.32} y={seat.cy - 0.3} z={0.41} dx={0.64} dy={0.6} dz={0.08} color={C.chair} />
      </g>
      {view.person ? <Person at={iso(seat.cx, seat.cy + 0.12, 0.49)} who={station.agent ?? station.id} working={view.working} /> : null}
      <g className={styles.chair} data-vacant={!view.person}>
        <Box x={seat.cx - 0.32} y={seat.cy + 0.26} z={0.49} dx={0.64} dy={0.08} dz={0.62} color={C.chair} />
      </g>
    </>
  );
}

function WallStation({ station }: { station: Extract<Station, { kind: "wall" }> }) {
  const s = screenOf(station);
  const frame = station.plane === "y0"
    ? [iso(station.from - 0.08, 0.02, station.z1 + 0.08), iso(station.to + 0.08, 0.02, station.z1 + 0.08), iso(station.to + 0.08, 0.02, station.z0 - 0.08), iso(station.from - 0.08, 0.02, station.z0 - 0.08)]
    : [iso(0.02, station.to + 0.08, station.z1 + 0.08), iso(0.02, station.from - 0.08, station.z1 + 0.08), iso(0.02, station.from - 0.08, station.z0 - 0.08), iso(0.02, station.to + 0.08, station.z0 - 0.08)];
  const anchor = station.plane === "y0" ? [(station.from + station.to) / 2, 1.2] : [1.2, (station.from + station.to) / 2];
  return (
    <>
      <ellipse className={styles.ring} {...isoEllipse(anchor[0]!, anchor[1]!, 1.3, 0.01)} />
      <polygon className={styles.frame} points={pts(frame)} />
      <OnPlane left={s.left} top={s.top} slope={s.slope}>
        <ScreenFace w={s.width} h={s.height} state="consulta" glyph={station.glyph} />
      </OnPlane>
    </>
  );
}

// --- decorado -----------------------------------------------------------------------------

function Plant({ x, y }: { x: number; y: number }) {
  const [px, py] = iso(x, y, 0.55);
  return (
    <>
      <Box x={x - 0.22} y={y - 0.22} dx={0.44} dy={0.44} dz={0.42} color={C.pot} />
      <circle cx={px - 7} cy={py - 6} r="8" fill={C.leaf} />
      <circle cx={px + 6} cy={py - 9} r="9" fill={C.leaf} />
      <circle cx={px} cy={py - 17} r="8" fill={C.leafLight} />
    </>
  );
}

function MeetingTable({ x, y }: { x: number; y: number }) {
  const top = isoEllipse(x, y, 1.05, 0.72);
  const edge = isoEllipse(x, y, 1.05, 0.66);
  return (
    <>
      {[
        [x - 1.45, y],
        [x, y - 1.45],
      ].map(([sx, sy], i) => (
        <Box key={i} x={sx! - 0.22} y={sy! - 0.22} dx={0.44} dy={0.44} dz={0.42} color={C.chair} />
      ))}
      <Box x={x - 0.1} y={y - 0.1} dx={0.2} dy={0.2} dz={0.66} color={C.leg} />
      <ellipse {...edge} fill={shade(C.desk, 0.7)} />
      <ellipse {...top} fill={shade(C.desk, 1.12)} />
      {[
        [x + 1.45, y],
        [x, y + 1.45],
      ].map(([sx, sy], i) => (
        <Box key={i} x={sx! - 0.22} y={sy! - 0.22} dx={0.44} dy={0.44} dz={0.42} color={C.chair} />
      ))}
    </>
  );
}

function SketchTable({ x, y }: { x: number; y: number }) {
  return (
    <>
      <Box x={x + 0.1} y={y + 0.1} dx={0.1} dy={0.1} dz={0.74} color={C.leg} />
      <Box x={x + 2.3} y={y + 0.1} dx={0.1} dy={0.1} dz={0.74} color={C.leg} />
      <Box x={x + 0.1} y={y + 1.6} dx={0.1} dy={0.1} dz={0.74} color={C.leg} />
      <Box x={x} y={y} z={0.74} dx={2.5} dy={1.8} dz={0.06} color={C.desk} />
      <polygon points={pts([iso(x + 0.3, y + 0.3, 0.81), iso(x + 1.2, y + 0.3, 0.81), iso(x + 1.2, y + 1.0, 0.81), iso(x + 0.3, y + 1.0, 0.81)])} fill={C.paper} opacity="0.82" />
      <polygon points={pts([iso(x + 1.4, y + 0.6, 0.81), iso(x + 2.2, y + 0.6, 0.81), iso(x + 2.2, y + 1.5, 0.81), iso(x + 1.4, y + 1.5, 0.81)])} fill={C.paper} opacity="0.6" />
      <Box x={x + 2.4} y={y + 1.6} dx={0.1} dy={0.1} dz={0.74} color={C.leg} />
    </>
  );
}

// --- muros y suelo ------------------------------------------------------------------------

function Shell({
  zoneHot,
  onZone,
  onZoneHover,
  interactive,
}: {
  zoneHot: ModuleId | null;
  onZone?: (id: ModuleId) => void;
  onZoneHover?: (id: ModuleId | null) => void;
  interactive: boolean;
}) {
  const W = FLOOR.wall;
  const windowsY0 = [
    [13.2, 15.6],
    [16.4, 18.8],
    [21, 23.4],
    [24.6, 27],
  ];
  const windowsX0 = [
    [1.2, 3.6],
    [4.6, 7],
  ];
  return (
    <g>
      <polygon points={pts([iso(0, 0), iso(FLOOR.x, 0), iso(FLOOR.x, FLOOR.y), iso(0, FLOOR.y)])} fill={C.floor} />
      <polygon points={pts([iso(0, 8), iso(FLOOR.x, 8), iso(FLOOR.x, 10), iso(0, 10)])} fill={C.corridor} />
      {ZONES.map((z) => (
        <polygon
          key={z.id}
          className={styles.zoneFloor}
          data-zone={z.id}
          data-hot={zoneHot === z.id}
          data-ready={z.ready}
          points={pts([iso(z.x0 + 0.06, z.y0 + 0.06), iso(z.x1 - 0.06, z.y0 + 0.06), iso(z.x1 - 0.06, z.y1 - 0.06), iso(z.x0 + 0.06, z.y1 - 0.06)])}
          fill={C.zone[z.id]}
          onClick={interactive && onZone ? () => onZone(z.id) : undefined}
          onMouseEnter={interactive && onZoneHover ? () => onZoneHover(z.id) : undefined}
          onMouseLeave={interactive && onZoneHover ? () => onZoneHover(null) : undefined}
        />
      ))}
      {/* Juntas de las baldosas: el suelo de la oficina, cada dos unidades. */}
      <g className={styles.seams}>
        {Array.from({ length: Math.floor(FLOOR.x / 2) - 1 }, (_, i) => (i + 1) * 2).map((gx) => (
          <line key={`x${gx}`} x1={iso(gx, 0)[0]} y1={iso(gx, 0)[1]} x2={iso(gx, FLOOR.y)[0]} y2={iso(gx, FLOOR.y)[1]} />
        ))}
        {Array.from({ length: Math.floor(FLOOR.y / 2) - 1 }, (_, i) => (i + 1) * 2).map((gy) => (
          <line key={`y${gy}`} x1={iso(0, gy)[0]} y1={iso(0, gy)[1]} x2={iso(FLOOR.x, gy)[0]} y2={iso(FLOOR.x, gy)[1]} />
        ))}
      </g>
      {/* Luz ambiental de cada sala */}
      {ZONES.map((z) => (
        <ellipse key={z.id} className={styles.pool} data-ready={z.ready} {...isoEllipse((z.x0 + z.x1) / 2, (z.y0 + z.y1) / 2, Math.min(z.x1 - z.x0, z.y1 - z.y0) * 0.55)} />
      ))}
      {/* Muro del fondo (y = 0) y muro lateral (x = 0) */}
      <polygon points={pts([iso(0, 0, 0), iso(FLOOR.x, 0, 0), iso(FLOOR.x, 0, W), iso(0, 0, W)])} fill={C.wallBack} />
      <polygon points={pts([iso(0, 0, 0), iso(0, FLOOR.y, 0), iso(0, FLOOR.y, W), iso(0, 0, W)])} fill={C.wallSide} />
      <polygon points={pts([iso(-0.25, -0.25, W), iso(FLOOR.x, -0.25, W), iso(FLOOR.x, 0, W), iso(0, 0, W), iso(0, FLOOR.y, W), iso(-0.25, FLOOR.y, W)])} fill={C.cap} />
      {windowsY0.map(([a, b]) => (
        <g key={`wy${a}`} className={styles.window}>
          <polygon points={pts([iso(a!, 0.01, 0.9), iso(b!, 0.01, 0.9), iso(b!, 0.01, 2.15), iso(a!, 0.01, 2.15)])} />
          <line x1={iso((a! + b!) / 2, 0.01, 0.9)[0]} y1={iso((a! + b!) / 2, 0.01, 0.9)[1]} x2={iso((a! + b!) / 2, 0.01, 2.15)[0]} y2={iso((a! + b!) / 2, 0.01, 2.15)[1]} />
        </g>
      ))}
      {windowsX0.map(([a, b]) => (
        <g key={`wx${a}`} className={styles.window}>
          <polygon points={pts([iso(0.01, a!, 0.9), iso(0.01, b!, 0.9), iso(0.01, b!, 2.15), iso(0.01, a!, 2.15)])} />
          <line x1={iso(0.01, (a! + b!) / 2, 0.9)[0]} y1={iso(0.01, (a! + b!) / 2, 0.9)[1]} x2={iso(0.01, (a! + b!) / 2, 2.15)[0]} y2={iso(0.01, (a! + b!) / 2, 2.15)[1]} />
        </g>
      ))}
      {/* Puerta de entrada al pasillo */}
      <polygon className={styles.door} points={pts([iso(0.01, 8.3, 0), iso(0.01, 9.7, 0), iso(0.01, 9.7, 1.9), iso(0.01, 8.3, 1.9)])} />
      {/* Mamparas de vidrio bajas entre salas, con hueco de paso */}
      {[
        [12, 0, 2.8],
        [12, 5.2, 8],
        [20, 0, 2.8],
        [20, 5.2, 8],
        [14, 10, 12.6],
        [14, 15.4, 18],
      ].map(([px, a, b]) => (
        <polygon key={`p${px}${a}`} className={styles.partition} points={pts([iso(px!, a!, 0), iso(px!, b!, 0), iso(px!, b!, 1.05), iso(px!, a!, 1.05)])} />
      ))}
    </g>
  );
}

/**
 * La oficina completa en un SVG. `agents`: mapa por identificador (null = no se pudo leer la API).
 * El orden de dibujo sigue la profundidad (x + y) para que lo cercano tape a lo lejano.
 */
export function OfficeScene({
  agents,
  hot = null,
  selected = null,
  last = null,
  lit = null,
  zoneHot = null,
  onZone,
  onZoneHover,
  interactive = true,
  crop,
  className,
}: {
  agents: Map<string, Agent> | null;
  hot?: string | null;
  selected?: string | null;
  last?: string | null;
  /** Puesto cuyo monitor se enciende al entrar (mismo aspecto que el computador). */
  lit?: string | null;
  zoneHot?: ModuleId | null;
  onZone?: (id: ModuleId) => void;
  onZoneHover?: (id: ModuleId | null) => void;
  interactive?: boolean;
  /** Recorte del mundo (viewBox) para mostrar solo una parte de la oficina; llena su contenedor. */
  crop?: { x: number; y: number; width: number; height: number };
  className?: string;
}) {
  const items: { depth: number; key: string; node: React.ReactNode }[] = [];
  for (const station of STATIONS) {
    const view = stationView(station, agents);
    const node = (
      <g
        className={styles.station}
        data-station={station.id}
        data-state={view.state}
        data-hot={hot === station.id}
        data-selected={selected === station.id}
        data-last={last === station.id && selected !== station.id}
        data-lit={lit === station.id}
      >
        {station.kind === "desk" ? <DeskStation station={station} view={view} /> : <WallStation station={station} />}
      </g>
    );
    const depth = station.kind === "desk" ? station.x + station.y + 4 : station.plane === "y0" ? station.from : station.from;
    items.push({ depth, key: station.id, node });
  }
  items.push({ depth: 1.6, key: "plant-d2", node: <Plant x={0.8} y={0.8} /> });
  items.push({ depth: 9.4, key: "plant-e", node: <Plant x={19.2} y={0.9} /> });
  items.push({ depth: 27, key: "sketch", node: <SketchTable x={24.6} y={3.4} /> });
  items.push({ depth: 24, key: "meeting", node: <MeetingTable x={10.2} y={14} /> });
  items.push({ depth: 18.6, key: "plant-co", node: <Plant x={0.9} y={17.4} /> });
  items.push({ depth: 42, key: "plant-v", node: <Plant x={26.8} y={16.8} /> });
  items.sort((a, b) => a.depth - b.depth);

  return (
    <svg
      className={`${styles.scene} ${className ?? ""}`}
      viewBox={crop ? `${crop.x} ${crop.y} ${crop.width} ${crop.height}` : `0 0 ${WORLD_W} ${WORLD_H}`}
      width={crop ? "100%" : WORLD_W}
      height={crop ? "100%" : WORLD_H}
      preserveAspectRatio={crop ? "xMidYMid slice" : undefined}
      aria-hidden="true"
      focusable="false"
      data-interactive={interactive}
    >
      <defs>
        <radialGradient id="ofi-pool">
          <stop offset="0" stopColor="#3d7bff" stopOpacity="0.2" />
          <stop offset="1" stopColor="#3d7bff" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="ofi-glow">
          <stop offset="0" stopColor="#9fc0ff" stopOpacity="0.45" />
          <stop offset="1" stopColor="#9fc0ff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <Shell zoneHot={zoneHot} onZone={onZone} onZoneHover={onZoneHover} interactive={interactive} />
      {items.map((item) => (
        <g key={item.key} data-item={item.key}>
          {item.node}
        </g>
      ))}
    </svg>
  );
}
