"use client";

import { AlertTriangle, Info, RefreshCw, Volume2, VolumeX } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ViewTransition, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { AgentDrawer } from "@/components/agents/AgentPanels";
import { BrandMark } from "@/components/shell/BrandMark";
import { ModeSwitch, SimulatedBanner } from "@/components/shell/ModeSwitch";
import { OPERATIONAL_POLL_MS, useAgents, useScheduler } from "@/hooks/queries";
import { useDataMode, useModeHref } from "@/hooks/useDataMode";
import { ACTIVITY } from "@/lib/labels";
import type { Agent, SchedulerStatus } from "@/lib/schemas";

import { Computer } from "./Computer";
import { MotionToggle } from "./MotionToggle";
import { useElementSize, useReducedMotion, useSound } from "./hooks";
import { OfficeScene, stationView } from "./OfficeScene";
import {
  isOfficePath,
  iso,
  screenCenter,
  screenOf,
  STATION,
  stationForPath,
  STATIONS,
  WORLD_H,
  WORLD_W,
  ZONE,
  zoneAnchor,
  zoneBox,
  ZONES,
  type ModuleId,
  type Station,
} from "./scene";
import styles from "./OfficeWorld.module.css";

type Focus =
  | { kind: "overview" }
  | { kind: "zone"; id: ModuleId }
  | { kind: "approach"; id: string }
  | { kind: "station"; id: string };

/**
 * Coreografía de la cámara al entrar a un computador: planos con pausas (acercamiento → pausa →
 * empuje → la pantalla se convierte en el computador). Es un momento poco frecuente e inmersivo,
 * así que va despacio; un clic o Enter lo salta y con movimiento reducido no hay acercamiento.
 * La salida es más corta y sutil que la entrada.
 */
export const SHOT = {
  /** De la vista general a un plano medio del puesto (persona, mesa y monitor). */
  approach: 3800,
  /** Pausa en el plano medio: el monitor se enciende. */
  hold: 900,
  /** Empuje lento hacia la pantalla. */
  push: 2800,
  /** La pantalla se convierte en el computador (::view-transition, ver globals.css). */
  morph: 1600,
  /** Al volver: pausa en el monitor antes de alejarse. */
  backHold: 400,
  /** Al volver: de la pantalla a la vista general. */
  pullBack: 2400,
  /** Saltar la secuencia: llegada rápida a la pantalla. */
  skip: 450,
} as const;
export const ENTRY_MS = SHOT.approach + SHOT.hold + SHOT.push;
export const MORPH_MS = SHOT.morph;

const EASE = {
  approach: "cubic-bezier(0.45, 0, 0.2, 1)",
  push: "cubic-bezier(0.55, 0, 0.25, 1)",
  pullBack: "cubic-bezier(0.3, 0, 0.15, 1)",
  skip: "cubic-bezier(0.22, 1, 0.36, 1)",
  ui: "cubic-bezier(0.45, 0, 0.15, 1)",
};
type Move = { ms: number; ease: string };
const DEFAULT_MOVE: Move = { ms: 1100, ease: EASE.ui };
type Phase = "acercando" | "pausa" | "empujando" | "saltando" | null;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Cámara: punto del mundo que queda en el centro del escenario y escala. */
export function cameraFor(focus: Focus, width: number, height: number, insetLeft = 0) {
  const w = Math.max(width, 1);
  const h = Math.max(height, 1);
  const base = Math.min(w / WORLD_W, h / WORLD_H) * 0.98;
  if (focus.kind === "zone") {
    // La sala se encuadra en el espacio libre junto al panel de la sala (insetLeft).
    const b = zoneBox(ZONE[focus.id]);
    const free = Math.max(w - insetLeft, w * 0.5);
    const s = clamp(Math.min(free / (b.right - b.left + 90), h / (b.bottom - b.top + 90)), base, 2.4);
    return { s, x: (b.left + b.right) / 2 - insetLeft / 2 / s, y: (b.top + b.bottom) / 2 };
  }
  if (focus.kind === "approach" && STATION[focus.id]) {
    // Plano medio: el puesto entero (persona, mesa y monitor) ocupa algo menos de media pantalla.
    const b = stationBox(STATION[focus.id]!);
    const s = clamp(Math.min((w * 0.42) / b.width, (h * 0.55) / b.height), base, 3.2);
    return { s, x: b.left + b.width / 2, y: b.top + b.height / 2 };
  }
  if (focus.kind === "station" && STATION[focus.id]) {
    const sc = screenOf(STATION[focus.id]!);
    const [x, y] = screenCenter(sc);
    const s = clamp(Math.min((w * 0.3) / sc.width, (h * 0.34) / (sc.height + sc.width * 0.5)), base, 6);
    return { s, x, y };
  }
  return { s: base, x: WORLD_W / 2, y: WORLD_H / 2 };
}

/** Caja de un puesto en el mundo: zona de clic sobre el escritorio, la persona y la pantalla. */
function stationBox(station: Station) {
  const points =
    station.kind === "desk"
      ? [
          iso(station.x, station.y, 1.75),
          iso(station.x + 2, station.y, 1.75),
          iso(station.x + 2, station.y, 0),
          iso(station.x, station.y + 2.3, 0),
          iso(station.x, station.y + 2.3, 2),
          iso(station.x + 2, station.y + 2.3, 0),
        ]
      : station.plane === "y0"
        ? [iso(station.from, 0, station.z1 + 0.1), iso(station.to, 0, station.z1 + 0.1), iso(station.from, 0, station.z0 - 0.1), iso(station.to, 0, station.z0 - 0.1)]
        : [iso(0, station.from, station.z1 + 0.1), iso(0, station.to, station.z1 + 0.1), iso(0, station.from, station.z0 - 0.1), iso(0, station.to, station.z0 - 0.1)];
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const left = Math.min(...xs) - 4;
  const top = Math.min(...ys) - 4;
  return { left, top, width: Math.max(...xs) - left + 4, height: Math.max(...ys) - top + 4 };
}

function tagAnchor(station: Station) {
  if (station.kind === "desk") return iso(station.x + 1, station.y + 0.2, 2.1);
  const mid = (station.from + station.to) / 2;
  return station.plane === "y0" ? iso(mid, 0, station.z1 + 0.2) : iso(0, mid, station.z1 + 0.2);
}

function focusVisible(el: Element) {
  try {
    return el.matches(":focus-visible");
  } catch {
    return true;
  }
}

export interface StationInfo {
  title: string;
  status: string;
  agent: Agent | null;
}

/** Nombre y estado de un puesto según la API (sin inventar nada cuando no hay datos). */
export function describeStation(station: Station, agents: Map<string, Agent> | null, scheduler?: SchedulerStatus): StationInfo {
  if (station.kind === "wall") {
    if (station.id === "programador" && scheduler) {
      const status = scheduler.habilitado ? (scheduler.en_ejecucion ? "Programador en marcha" : "Habilitado, detenido") : "Programador apagado";
      return { title: station.label, status, agent: null };
    }
    return { title: station.label, status: "Pantalla de consulta", agent: null };
  }
  if (!station.agent) return { title: station.label, status: `${ZONE[station.zone].module} en preparación`, agent: null };
  const agent = agents?.get(station.agent) ?? null;
  if (!agent) return { title: station.label, status: agents === null ? "Estado no disponible" : "Agente no registrado", agent: null };
  if (!agent.implementado) return { title: agent.nombre, status: "Sin tarea implementada", agent };
  return { title: agent.nombre, status: ACTIVITY[agent.actividad].text, agent };
}

function SoundToggle({ enabled, onToggle }: { enabled: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      className={styles.iconBtn}
      aria-pressed={enabled}
      onClick={onToggle}
      title={enabled ? "Sonido activado" : "Sonido desactivado"}
    >
      {enabled ? <Volume2 size={17} aria-hidden="true" /> : <VolumeX size={17} aria-hidden="true" />}
      <span className="visually-hidden">Sonido al entrar y salir del computador</span>
    </button>
  );
}

/**
 * La oficina persistente: el escenario isométrico con su cámara y, encima, el computador del
 * puesto elegido. Las rutas de la aplicación son los computadores: `/oficina` es la vista general
 * y `/tendencias`, `/temas`… abren la pantalla del puesto que les corresponde.
 */
export function OfficeWorld({ children }: { children: ReactNode }) {
  const path = usePathname() ?? "/oficina";
  const router = useRouter();
  const mode = useDataMode();
  const href = useModeHref();
  const reduced = useReducedMotion();
  const sound = useSound();
  const [stageRef, size] = useElementSize<HTMLDivElement>();

  const inOffice = isOfficePath(path);
  const routeStation = inOffice ? null : stationForPath(path);

  const agentsQ = useAgents(mode, OPERATIONAL_POLL_MS);
  const schedulerQ = useScheduler(OPERATIONAL_POLL_MS);
  const agents = useMemo(() => (agentsQ.data ? new Map(agentsQ.data.agentes.map((a) => [a.id, a])) : null), [agentsQ.data]);

  const [focus, setFocus] = useState<Focus>(() => (routeStation ? { kind: "station", id: routeStation.id } : { kind: "overview" }));
  const [origin, setOrigin] = useState<string | null>(routeStation?.id ?? null);
  const [last, setLast] = useState<string | null>(null);
  const [hot, setHot] = useState<string | null>(null);
  const [zoneHot, setZoneHot] = useState<ModuleId | null>(null);
  const [entering, setEntering] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>(null);
  const [move, setMove] = useState<Move>(DEFAULT_MOVE);
  const [instant, setInstant] = useState(true);
  const [ficha, setFicha] = useState<Agent | null>(null);
  // Al entrar desde la oficina el foco pasa a la pantalla; con un enlace directo se respeta el orden normal.
  const enteredFromOffice = useRef(false);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const prevPath = useRef(path);
  const timers = useRef<number[]>([]);

  const later = useCallback((fn: () => void, ms: number) => {
    timers.current.push(window.setTimeout(fn, ms));
  }, []);
  // Temporizadores de la secuencia de entrada: se cancelan al saltarla o al pulsar Escape.
  const shots = useRef<number[]>([]);
  const atShot = useCallback((fn: () => void, ms: number) => {
    shots.current.push(window.setTimeout(fn, ms));
  }, []);
  const clearShots = useCallback(() => {
    shots.current.forEach((t) => window.clearTimeout(t));
    shots.current = [];
  }, []);
  useEffect(
    () => () => {
      timers.current.forEach((t) => window.clearTimeout(t));
      shots.current.forEach((t) => window.clearTimeout(t));
    },
    [],
  );

  // Primer encuadre y cambios de tamaño: sin transición (la cámara no "viaja" al redimensionar).
  useEffect(() => {
    setInstant(true);
    const frame = requestAnimationFrame(() => requestAnimationFrame(() => setInstant(false)));
    return () => cancelAnimationFrame(frame);
  }, [size.width, size.height]);

  // Navegación: entrar al computador, cambiar de sección o volver a la oficina.
  useEffect(() => {
    const prev = prevPath.current;
    prevPath.current = path;
    if (prev === path) return;
    if (!inOffice) {
      setEntering(null);
      setPhase(null);
      const station = routeStation;
      if (!station) return;
      setOrigin((current) => (current && STATION[current] && STATION[current]!.zone === station.zone ? current : station.id));
      setFocus((current) => (current.kind === "station" && STATION[current.id]?.zone === station.zone ? current : { kind: "station", id: station.id }));
      return;
    }
    if (!isOfficePath(prev)) {
      // Regreso: la pantalla vuelve al monitor y, después, la cámara se aleja.
      const from = origin ?? stationForPath(prev)?.id ?? null;
      setLast(from);
      setEntering(null);
      setPhase(null);
      later(
        () => {
          setMove({ ms: SHOT.pullBack, ease: EASE.pullBack });
          setFocus({ kind: "overview" });
          if (from) buttons.current.get(from)?.focus({ preventScroll: true });
        },
        reduced ? 0 : SHOT.morph + SHOT.backHold,
      );
    }
  }, [path, inOffice, routeStation, origin, reduced, later]);

  const enter = useCallback(
    (station: Station) => {
      if (entering) return;
      setEntering(station.id);
      enteredFromOffice.current = true;
      setOrigin(station.id);
      setHot(null);
      sound.play("entrar");
      const go = () => router.push(href(station.href), { transitionTypes: ["entrar-computador"] });
      if (reduced) {
        setFocus({ kind: "station", id: station.id });
        atShot(go, 0);
        return;
      }
      // 1. Acercamiento lento a un plano medio del puesto.
      setPhase("acercando");
      setMove({ ms: SHOT.approach, ease: EASE.approach });
      setFocus({ kind: "approach", id: station.id });
      // 2. Pausa: el monitor se enciende.
      atShot(() => setPhase("pausa"), SHOT.approach);
      // 3. Empuje lento hacia la pantalla.
      atShot(() => {
        setPhase("empujando");
        setMove({ ms: SHOT.push, ease: EASE.push });
        setFocus({ kind: "station", id: station.id });
      }, SHOT.approach + SHOT.hold);
      // 4. La pantalla se convierte en el computador.
      atShot(go, ENTRY_MS);
    },
    [atShot, entering, href, reduced, router, sound],
  );

  /** Saltar la secuencia: llegada rápida a la pantalla y entrada. */
  const skip = useCallback(() => {
    const id = entering;
    if (!id || phase === "saltando" || phase === null) return;
    const station = STATION[id];
    if (!station) return;
    clearShots();
    setPhase("saltando");
    setMove({ ms: SHOT.skip, ease: EASE.skip });
    setFocus({ kind: "station", id });
    atShot(() => router.push(href(station.href), { transitionTypes: ["entrar-computador"] }), SHOT.skip + 30);
  }, [atShot, clearShots, entering, href, phase, router]);

  /** Cancelar la entrada (Escape): la cámara vuelve a la vista general. */
  const cancelEntry = useCallback(() => {
    if (!entering || phase === null) return;
    clearShots();
    setEntering(null);
    setPhase(null);
    setMove({ ms: SHOT.pullBack, ease: EASE.pullBack });
    setFocus({ kind: "overview" });
  }, [clearShots, entering, phase]);

  // Durante la secuencia: clic o Enter/Espacio la saltan.
  useEffect(() => {
    if (!phase || phase === "saltando") return;
    const onPointer = (e: PointerEvent) => {
      const target = e.target instanceof Element ? e.target : null;
      if (target?.closest("header, [role='group'][aria-label='Modo de datos']")) return;
      skip();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        skip();
      }
    };
    window.addEventListener("pointerdown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("keydown", onKey);
    };
  }, [phase, skip]);

  const exit = useCallback(() => {
    sound.play("salir");
    router.push(href("/oficina"), { transitionTypes: ["salir-computador"] });
  }, [href, router, sound]);

  // Escape: en el computador vuelve a la oficina; en la oficina vuelve a la vista general.
  // Nunca interfiere con diálogos abiertos ni con la escritura en formularios.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (document.querySelector("dialog[open]")) return;
      const target = e.target instanceof Element ? e.target : null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      if (!inOffice) exit();
      else if (entering) cancelEntry();
      else if (focus.kind !== "overview") {
        setMove(DEFAULT_MOVE);
        setFocus({ kind: "overview" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [inOffice, exit, focus.kind, entering, cancelEntry]);

  const cam = cameraFor(focus, size.width, size.height, focus.kind === "zone" && size.width > 760 ? 400 : 0);
  const worldStyle = {
    transition: `transform ${move.ms}ms ${move.ease}`,
    transform: `translate(${(size.width / 2 - cam.x * cam.s).toFixed(2)}px, ${(size.height / 2 - cam.y * cam.s).toFixed(2)}px) scale(${cam.s.toFixed(4)})`,
  };
  // Etiquetas y placas: tamaño constante en pantalla (contraescala) y ancladas por su centro.
  const k = (1 / cam.s).toFixed(4);
  const tagStyle = { transform: `scale(${k}) translate(-50%, -10px)` };
  const plaqueStyle = { transform: `scale(${k}) translate(-50%, -50%)` };
  const computerStation = !inOffice ? (STATION[origin ?? ""] ?? routeStation) : null;
  const overlayStation = inOffice && focus.kind === "station" ? STATION[focus.id] : null;
  const zone = focus.kind === "zone" ? ZONE[focus.id] : null;

  return (
    <div
      className={styles.root}
      data-cursor={inOffice ? "oficina" : "computador"}
      data-view={inOffice ? "oficina" : "computador"}
      data-entering={entering !== null}
      data-phase={phase ?? undefined}
    >
      <a className="skip-link" href="#contenido">
        Saltar al contenido
      </a>
      <div
        ref={stageRef}
        id={inOffice ? "contenido" : undefined}
        role={inOffice ? "main" : undefined}
        aria-label={inOffice ? "Oficina" : undefined}
        tabIndex={inOffice ? -1 : undefined}
        className={styles.stage}
        data-zoomed={focus.kind !== "overview"}
        inert={!inOffice || undefined}
        aria-hidden={!inOffice || undefined}
      >
        <div className={styles.world} data-instant={instant || reduced} style={worldStyle}>
            <OfficeScene
              agents={agents}
              hot={hot}
              selected={focus.kind === "station" || focus.kind === "approach" ? focus.id : null}
              lit={phase === "pausa" || phase === "empujando" || phase === "saltando" ? entering : null}
              last={last}
              zoneHot={zoneHot ?? (focus.kind === "zone" ? focus.id : null)}
              onZone={(id) => setFocus({ kind: "zone", id })}
              onZoneHover={setZoneHot}
            />

            {/* Placas de las salas (solo en la vista general): entran a cada sala con la cámara */}
            {(focus.kind === "overview" ? ZONES : []).map((z) => {
              const [ax, ay] = zoneAnchor(z);
              return (
                <div key={z.id} className={styles.plaqueAnchor} style={{ left: ax, top: ay }}>
                  <button
                    type="button"
                    className={styles.plaque}
                    style={plaqueStyle}
                    data-active={focus.kind === "zone" && focus.id === z.id}
                    onClick={() => setFocus({ kind: "zone", id: z.id })}
                    onMouseEnter={() => setZoneHot(z.id)}
                    onMouseLeave={() => setZoneHot(null)}
                    onFocus={() => setZoneHot(z.id)}
                    onBlur={() => setZoneHot(null)}
                    aria-label={`${z.room}, ${z.module}: ${z.ready ? "funcional" : "en preparación"}. Ver la sala`}
                  >
                    <span className={styles.plaqueName}>{z.room}</span>
                    <span className={styles.plaqueModule} data-ready={z.ready}>
                      <span className={styles.plaqueCode}>{z.module}</span> · {z.ready ? "funcional" : "en preparación"}
                    </span>
                  </button>
                </div>
              );
            })}

            {/* Puestos: cada uno es un botón con su etiqueta de estado real */}
            <div id="puestos" className={styles.hotspots} role="group" aria-label="Puestos de la oficina">
              {STATIONS.map((station) => {
                const box = stationBox(station);
                const info = describeStation(station, agents, schedulerQ.data);
                const view = stationView(station, agents);
                const [tx, ty] = tagAnchor(station);
                // La etiqueta solo con el puntero encima o con foco de teclado.
                const shown = hot === station.id && !entering;
                return (
                  <div
                    key={station.id}
                    className={styles.spot}
                    style={{ left: box.left, top: box.top, width: box.width, height: box.height }}
                    onMouseEnter={() => setHot(station.id)}
                    onMouseLeave={() => setHot((h) => (h === station.id ? null : h))}
                    onFocus={(e) => {
                      // Solo con foco de teclado: el foco que se devuelve al volver no abre la etiqueta.
                      if (focusVisible(e.target)) setHot(station.id);
                    }}
                    onBlur={(e) => {
                      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setHot((h) => (h === station.id ? null : h));
                    }}
                  >
                    <button
                      ref={(el) => {
                        if (el) buttons.current.set(station.id, el);
                        else buttons.current.delete(station.id);
                      }}
                      type="button"
                      className={styles.spotBtn}
                      data-state={view.state}
                      onClick={() => enter(station)}
                      aria-label={`${info.title} (${ZONE[station.zone].room}): ${info.status}. Entrar al computador`}
                    />
                    <div className={styles.tagAnchor} style={{ left: tx - box.left, top: ty - box.top }} data-shown={shown}>
                      <div className={styles.tag} style={tagStyle}>
                        <span className={styles.tagTitle}>{info.title}</span>
                        <span className={styles.tagStatus} data-state={view.state}>
                          {info.status}
                        </span>
                        <span className={styles.tagHint}>Clic para entrar al computador</span>
                        {info.agent ? (
                          <button type="button" className={styles.tagLink} onClick={() => setFicha(info.agent)}>
                            Ficha del agente
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

        {/* Pantalla del puesto enfocado, en coordenadas de pantalla (sin la escala de la cámara):
            es la mitad «de origen» de la transición compartida con el computador. */}
        {overlayStation ? (
          <div className={styles.screenLayer} aria-hidden="true">
            <ViewTransition name="pantalla-computador" share="pantalla" default="none">
              <div
                className={styles.screenOverlay}
                // En la oficina la pantalla solo existe al entrar o justo al volver del computador.
                data-on={phase === "saltando" ? "directo" : entering === overlayStation.id ? "entrando" : "volviendo"}
                style={(() => {
                  const s = screenOf(overlayStation);
                  return {
                    left: size.width / 2 + (s.left - cam.x) * cam.s,
                    top: size.height / 2 + (s.top - cam.y) * cam.s,
                    width: s.width * cam.s,
                    height: s.height * cam.s,
                    transform: `skewY(${s.slope > 0 ? 26.565 : -26.565}deg)`,
                  };
                })()}
              />
            </ViewTransition>
          </div>
        ) : null}

        {entering && phase && phase !== "saltando" ? (
          <p className={styles.entryHint} role="status">
            Entrando al computador · <kbd>clic</kbd> o <kbd>Enter</kbd> para saltar · <kbd>Esc</kbd> para cancelar
          </p>
        ) : null}

        {inOffice ? (
          <>
            <header className={styles.hud}>
              <Link href="/" className={styles.brand} aria-label="HACK 30X: portada">
                <BrandMark size={34} />
                <span>HACK 30X</span>
              </Link>
              <nav aria-label="Ubicación" className={styles.crumbs}>
                <ol>
                  <li>
                    {focus.kind === "overview" ? (
                      <span aria-current="page">Oficina</span>
                    ) : (
                      <button type="button" className={styles.crumbBtn} onClick={() => setFocus({ kind: "overview" })}>
                        Oficina
                      </button>
                    )}
                  </li>
                  {zone ? (
                    <li>
                      <span aria-current="page">{zone.room}</span>
                    </li>
                  ) : null}
                </ol>
              </nav>
              <div className={styles.tools}>
                <ModeSwitch />
                <MotionToggle />
                <SoundToggle enabled={sound.enabled} onToggle={sound.toggle} />
              </div>
            </header>
            <SimulatedBanner />
            <h1 className="visually-hidden">Oficina de HACK 30X</h1>
            {agentsQ.error ? (
              <div className={styles.alert} role="alert">
                <AlertTriangle size={16} aria-hidden="true" />
                <span>No se pudo leer el estado de los agentes: los puestos se muestran sin estado. {agentsQ.error.message}</span>
                <button type="button" className={styles.alertBtn} onClick={agentsQ.refetch}>
                  <RefreshCw size={14} aria-hidden="true" /> Reintentar
                </button>
              </div>
            ) : null}

            {zone ? (
              <aside className={styles.zonePanel} aria-labelledby="sala-titulo">
                <h2 id="sala-titulo" className={styles.zoneTitle}>
                  {zone.room}
                </h2>
                <p className={styles.zoneModule} data-ready={zone.ready}>
                  {zone.module} · {zone.ready ? "funcional" : "en preparación"}
                </p>
                <p className={styles.zonePurpose}>{zone.purpose}</p>
                <ul className={styles.zoneList}>
                  {STATIONS.filter((s) => s.zone === zone.id).map((s) => {
                    const info = describeStation(s, agents, schedulerQ.data);
                    return (
                      <li key={s.id}>
                        <button type="button" className={styles.zoneItem} onClick={() => enter(s)} onMouseEnter={() => setHot(s.id)} onMouseLeave={() => setHot(null)}>
                          <span>{info.title}</span>
                          <span className={styles.zoneItemStatus}>{info.status}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
                <button type="button" className={styles.backBtn} onClick={() => setFocus({ kind: "overview" })}>
                  Ver toda la oficina
                </button>
              </aside>
            ) : (
              <details className={styles.legend}>
                <summary>
                  <Info size={15} aria-hidden="true" /> Cómo leer la oficina
                </summary>
                <ul>
                  <li>Una persona en su puesto es un agente con tarea implementada; una silla vacía, un rol que todavía no la tiene.</li>
                  <li>La pantalla muestra el resultado de la última ejecución registrada. Solo teclea, con la luz lima encendida, si hay una ejecución pendiente o en curso.</li>
                  <li>Las pantallas de pared dan acceso a temas, métricas, clasificaciones, ejecuciones y programador.</li>
                  <li>ENTENDER, CREAR y VALIDAR todavía no están implementados: sus salas están en preparación.</li>
                </ul>
              </details>
            )}
          </>
        ) : null}
      </div>

      {inOffice ? (
        <section className={styles.directory} aria-labelledby="directorio">
          <h2 id="directorio" className={styles.directoryTitle}>
            Puestos de la oficina
          </h2>
          {ZONES.map((z) => (
            <div key={z.id} className={styles.directoryZone}>
              <h3>
                {z.room} <span data-ready={z.ready}>{z.module} · {z.ready ? "funcional" : "en preparación"}</span>
              </h3>
              <ul>
                {STATIONS.filter((s) => s.zone === z.id).map((s) => {
                  const info = describeStation(s, agents, schedulerQ.data);
                  return (
                    <li key={s.id}>
                      <button type="button" className={styles.directoryItem} onClick={() => enter(s)}>
                        <span>{info.title}</span>
                        <span className={styles.zoneItemStatus}>{info.status}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
          <div className={styles.officeChildren}>{children}</div>
        </section>
      ) : null}

      {computerStation ? (
        <ViewTransition name="pantalla-computador" share="pantalla" default="none">
          <Computer
            station={computerStation}
            info={describeStation(computerStation, agents, schedulerQ.data)}
            onExit={exit}
            focusOnMount={enteredFromOffice.current}
            sound={
              <>
                <MotionToggle />
                <SoundToggle enabled={sound.enabled} onToggle={sound.toggle} />
              </>
            }
          >
            {children}
          </Computer>
        </ViewTransition>
      ) : !inOffice ? (
        <div className={styles.fallback}>{children}</div>
      ) : null}

      <AgentDrawer agent={ficha} mode={mode} onClose={() => setFicha(null)} />
    </div>
  );
}
