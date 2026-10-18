/**
 * Plano de la oficina de HACK 30X en coordenadas de cuadrícula y su proyección isométrica.
 *
 * Todo es geometría fija y verificable: salas, puestos y pantallas. Qué hay en cada puesto (si
 * hay persona, si trabaja, qué muestra su pantalla) lo decide el estado real de la API, no este
 * archivo. Cada pantalla define la zona que enfoca la cámara y el rectángulo que se convierte en
 * la interfaz del computador.
 */

/** Media baldosa en píxeles del mundo (proporción 2:1) y altura de una unidad vertical. */
export const HALF_W = 28;
export const HALF_H = 14;
export const UNIT_Z = 30;

const FLOOR_X = 28;
const FLOOR_Y = 18;
const WALL = 2.6;
const MARGIN = 56;

export const ORIGIN_X = FLOOR_Y * HALF_W + MARGIN;
export const ORIGIN_Y = WALL * UNIT_Z + MARGIN;
export const WORLD_W = (FLOOR_X + FLOOR_Y) * HALF_W + MARGIN * 2;
export const WORLD_H = ORIGIN_Y + (FLOOR_X + FLOOR_Y) * HALF_H + MARGIN;
export const FLOOR = { x: FLOOR_X, y: FLOOR_Y, wall: WALL };

export type Pt = readonly [number, number];

/** Proyección isométrica: (x, y) en el suelo, z hacia arriba. */
export function iso(x: number, y: number, z = 0): Pt {
  return [ORIGIN_X + (x - y) * HALF_W, ORIGIN_Y + (x + y) * HALF_H - z * UNIT_Z];
}

export type ModuleId = "detectar" | "entender" | "crear" | "validar" | "coordinacion";

export interface Zone {
  id: ModuleId;
  /** Nombre de la sala en la oficina. */
  room: string;
  /** Nombre del módulo de HACK 30X. */
  module: string;
  /** Estado real del módulo en el producto: solo DETECTAR y la coordinación funcionan hoy. */
  ready: boolean;
  /** Qué hará (o hace) el módulo, en una frase. */
  purpose: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export const ZONES: Zone[] = [
  {
    id: "detectar",
    room: "Sala de tendencias",
    module: "DETECTAR",
    ready: true,
    purpose: "Recoge señales públicas, agrupa los temas, mide su evolución y clasifica su etapa.",
    x0: 0,
    y0: 0,
    x1: 12,
    y1: 8,
  },
  {
    id: "entender",
    room: "Sala de análisis",
    module: "ENTENDER",
    ready: false,
    purpose: "Decidirá si un tema encaja con la audiencia de cada creador. Todavía no está implementado.",
    x0: 12,
    y0: 0,
    x1: 20,
    y1: 8,
  },
  {
    id: "crear",
    room: "Estudio creativo",
    module: "CREAR",
    ready: false,
    purpose: "Propondrá piezas de contenido a partir de un tema. Todavía no está implementado.",
    x0: 20,
    y0: 0,
    x1: 28,
    y1: 8,
  },
  {
    id: "coordinacion",
    room: "Centro de agentes",
    module: "Coordinación",
    ready: true,
    purpose: "Estado real de los agentes, sus ejecuciones y el programador.",
    x0: 0,
    y0: 10,
    x1: 14,
    y1: 18,
  },
  {
    id: "validar",
    room: "Sala de validación",
    module: "VALIDAR",
    ready: false,
    purpose: "Comprobará las ideas y el contenido antes de publicarlos. Todavía no está implementado.",
    x0: 14,
    y0: 10,
    x1: 28,
    y1: 18,
  },
];

export const ZONE = Object.fromEntries(ZONES.map((z) => [z.id, z])) as Record<ModuleId, Zone>;

/**
 * Un puesto con computador:
 * - `desk`: escritorio con monitor; si `agent` está definido, es el puesto de ese agente;
 * - `wall`: pantalla de pared (consulta, sin persona) en el muro del fondo (`y0`) o el lateral (`x0`).
 */
export type Station =
  | {
      id: string;
      kind: "desk";
      zone: ModuleId;
      label: string;
      href: string;
      agent?: string;
      /** Esquina trasera izquierda del escritorio (2 × 1,1 unidades). */
      x: number;
      y: number;
    }
  | {
      id: string;
      kind: "wall";
      zone: ModuleId;
      label: string;
      href: string;
      plane: "y0" | "x0";
      /** Tramo del muro que ocupa la pantalla y su altura. */
      from: number;
      to: number;
      z0: number;
      z1: number;
      glyph: "tags" | "bars" | "stages" | "runs" | "clock";
    };

export const STATIONS: Station[] = [
  { id: "trend_hunter", kind: "desk", zone: "detectar", agent: "trend_hunter", label: "Puesto del Cazador de tendencias", href: "/tendencias", x: 3, y: 3.6 },
  { id: "format_hunter", kind: "desk", zone: "detectar", agent: "format_hunter", label: "Puesto del Cazador de formatos", href: "/puesto/format_hunter", x: 7.4, y: 3.6 },
  { id: "temas", kind: "wall", zone: "detectar", plane: "y0", from: 1, to: 3.6, z0: 0.95, z1: 2.15, glyph: "tags", label: "Pantalla de temas", href: "/temas" },
  { id: "metricas", kind: "wall", zone: "detectar", plane: "y0", from: 4.6, to: 7.2, z0: 0.95, z1: 2.15, glyph: "bars", label: "Pantalla de métricas", href: "/metricas" },
  { id: "clasificaciones", kind: "wall", zone: "detectar", plane: "y0", from: 8.2, to: 10.8, z0: 0.95, z1: 2.15, glyph: "stages", label: "Pantalla de clasificaciones y evidencias", href: "/clasificaciones" },
  { id: "analyst", kind: "desk", zone: "entender", agent: "analyst", label: "Puesto del Analista", href: "/puesto/analyst", x: 13.4, y: 3.6 },
  { id: "audience_filter", kind: "desk", zone: "entender", agent: "audience_filter", label: "Puesto del Filtro de audiencia", href: "/puesto/audience_filter", x: 16.8, y: 3.6 },
  { id: "strategist", kind: "desk", zone: "crear", agent: "strategist", label: "Puesto del Estratega", href: "/puesto/strategist", x: 21.6, y: 3.6 },
  { id: "supervisor", kind: "desk", zone: "coordinacion", agent: "supervisor", label: "Puesto del Supervisor", href: "/coordinacion", x: 5.2, y: 12.6 },
  { id: "ejecuciones", kind: "wall", zone: "coordinacion", plane: "x0", from: 10.9, to: 13.5, z0: 0.95, z1: 2.15, glyph: "runs", label: "Pantalla de ejecuciones", href: "/ejecuciones" },
  { id: "programador", kind: "wall", zone: "coordinacion", plane: "x0", from: 14.5, to: 17.1, z0: 0.95, z1: 2.15, glyph: "clock", label: "Pantalla del programador", href: "/programador" },
  { id: "validar", kind: "desk", zone: "validar", label: "Puesto de validación", href: "/validar", x: 19.4, y: 14 },
];

export const STATION = Object.fromEntries(STATIONS.map((s) => [s.id, s])) as Record<string, Station>;

/** Monitor de escritorio: tramo sobre la mesa y altura de la pantalla. */
export const MONITOR = { from: 0.45, to: 1.55, face: 0.24, z0: 0.86, z1: 1.62 };

/**
 * Pantalla de un puesto: paralelogramo en el mundo, descrito por su esquina superior izquierda,
 * su ancho y alto en píxeles y la inclinación (pendiente vertical por píxel horizontal).
 */
export interface Screen {
  left: number;
  top: number;
  width: number;
  height: number;
  /** +0,5 en caras que miran a +y (muro del fondo, monitores); −0,5 en el muro lateral. */
  slope: 0.5 | -0.5;
}

export function screenOf(station: Station): Screen {
  if (station.kind === "desk") {
    const [left, top] = iso(station.x + MONITOR.from, station.y + MONITOR.face, MONITOR.z1);
    return { left, top, width: (MONITOR.to - MONITOR.from) * HALF_W, height: (MONITOR.z1 - MONITOR.z0) * UNIT_Z, slope: 0.5 };
  }
  if (station.plane === "y0") {
    const [left, top] = iso(station.from, 0, station.z1);
    return { left, top, width: (station.to - station.from) * HALF_W, height: (station.z1 - station.z0) * UNIT_Z, slope: 0.5 };
  }
  const [left, top] = iso(0, station.to, station.z1);
  return { left, top, width: (station.to - station.from) * HALF_W, height: (station.z1 - station.z0) * UNIT_Z, slope: -0.5 };
}

/** Centro de la pantalla en el mundo: el punto al que se acerca la cámara. */
export function screenCenter(s: Screen): Pt {
  return [s.left + s.width / 2, s.top + s.height / 2 + (s.slope * s.width) / 2];
}

/** Caja que rodea una sala proyectada (para encuadrarla). */
export function zoneBox(zone: Zone) {
  const pts = [
    iso(zone.x0, zone.y0, WALL),
    iso(zone.x1, zone.y0, WALL),
    iso(zone.x0, zone.y1, 0),
    iso(zone.x1, zone.y1, 0),
    iso(zone.x1, zone.y0, 0),
    iso(zone.x0, zone.y1, WALL),
  ];
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  return { left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys) };
}

/**
 * Centro de la placa de cada sala: en el pasillo (y = 9), la única franja sin muebles, repartidas
 * a lo largo de x para que ninguna placa tape a otra ni a un puesto (comprobado con la prueba de
 * solapes en el navegador).
 */
const PLAQUE_X: Record<ModuleId, number> = { detectar: 3.5, coordinacion: 9.5, entender: 16, validar: 21, crear: 26 };
export function zoneAnchor(zone: Zone): Pt {
  return iso(PLAQUE_X[zone.id], 9, 0);
}

// --- rutas del computador ------------------------------------------------------------------

export interface ModuleTab {
  href: string;
  label: string;
}

/** Secciones de cada computador funcional. Las rutas son las de la aplicación existente. */
export const MODULE_TABS: Partial<Record<ModuleId, ModuleTab[]>> = {
  detectar: [
    { href: "/tendencias", label: "Tendencias" },
    { href: "/temas", label: "Temas" },
    { href: "/metricas", label: "Métricas" },
    { href: "/clasificaciones", label: "Clasificaciones y evidencias" },
  ],
  coordinacion: [
    { href: "/coordinacion", label: "Resumen" },
    { href: "/ejecuciones", label: "Ejecuciones" },
    { href: "/agentes", label: "Agentes" },
    { href: "/programador", label: "Programador" },
  ],
};

const ROUTE_STATION: Record<string, string> = {
  "/tendencias": "trend_hunter",
  "/temas": "temas",
  "/metricas": "metricas",
  "/clasificaciones": "clasificaciones",
  "/coordinacion": "supervisor",
  "/agentes": "supervisor",
  "/ejecuciones": "ejecuciones",
  "/programador": "programador",
  "/validar": "validar",
};

/** Puesto que corresponde a una ruta del computador; `null` en la oficina o rutas ajenas. */
export function stationForPath(path: string): Station | null {
  const clean = path.replace(/\/+$/, "") || "/";
  const direct = ROUTE_STATION[clean];
  if (direct) return STATION[direct] ?? null;
  const match = /^\/puesto\/([^/]+)$/.exec(clean);
  if (match) return STATION[decodeURIComponent(match[1]!)] ?? null;
  return null;
}

/** ¿La ruta es la oficina (vista general) y no un computador? */
export function isOfficePath(path: string): boolean {
  return (path.replace(/\/+$/, "") || "/") === "/oficina";
}
