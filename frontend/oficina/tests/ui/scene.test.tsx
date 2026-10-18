import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OfficeScene, stationView } from "@/components/office/OfficeScene";
import { cameraFor, describeStation } from "@/components/office/OfficeWorld";
import { iso, screenCenter, screenOf, STATION, stationForPath, STATIONS, WORLD_H, WORLD_W, ZONES } from "@/components/office/scene";
import type { Agent } from "@/lib/schemas";

import { agent, agentList, run, scheduler } from "../support/fixtures";

const byId = (agents: Agent[]) => new Map(agents.map((a) => [a.id, a]));

describe("plano de la oficina", () => {
  it("tiene las cinco salas de HACK 30X y solo DETECTAR y la coordinación están listas", () => {
    expect(ZONES.map((z) => z.module)).toEqual(["DETECTAR", "ENTENDER", "CREAR", "Coordinación", "VALIDAR"]);
    expect(ZONES.filter((z) => z.ready).map((z) => z.id)).toEqual(["detectar", "coordinacion"]);
    for (const z of ZONES.filter((z) => !z.ready)) expect(z.purpose).toMatch(/no está implementado/);
  });

  it("cada agente del registro tiene un puesto en la sala de su módulo", () => {
    const desks = STATIONS.filter((s) => s.kind === "desk" && s.agent);
    expect(desks.map((s) => (s.kind === "desk" ? s.agent : null)).sort()).toEqual(
      ["analyst", "audience_filter", "format_hunter", "strategist", "supervisor", "trend_hunter"],
    );
    expect(STATION.trend_hunter!.zone).toBe("detectar");
    expect(STATION.analyst!.zone).toBe("entender");
    expect(STATION.strategist!.zone).toBe("crear");
    expect(STATION.supervisor!.zone).toBe("coordinacion");
  });

  it("cada ruta del computador corresponde a un puesto; la oficina no abre ninguno", () => {
    expect(stationForPath("/tendencias")?.id).toBe("trend_hunter");
    expect(stationForPath("/temas")?.id).toBe("temas");
    expect(stationForPath("/metricas")?.id).toBe("metricas");
    expect(stationForPath("/clasificaciones")?.id).toBe("clasificaciones");
    expect(stationForPath("/coordinacion")?.id).toBe("supervisor");
    expect(stationForPath("/ejecuciones")?.id).toBe("ejecuciones");
    expect(stationForPath("/programador")?.id).toBe("programador");
    expect(stationForPath("/puesto/analyst")?.id).toBe("analyst");
    expect(stationForPath("/validar")?.id).toBe("validar");
    expect(stationForPath("/oficina")).toBeNull();
    expect(stationForPath("/puesto/inexistente")).toBeNull();
  });

  it("la pantalla de un monitor es el paralelogramo de su cara frontal", () => {
    const desk = STATION.trend_hunter!;
    const s = screenOf(desk);
    expect(s.slope).toBe(0.5);
    expect(s.width).toBeCloseTo(1.1 * 28);
    expect(s.height).toBeCloseTo(0.76 * 30);
    // la esquina inferior derecha cae sobre la proyección del borde del monitor
    const corner = iso(3 + 1.55, 3.6 + 0.24, 0.86);
    expect(s.left + s.width).toBeCloseTo(corner[0]);
    expect(s.top + s.height + s.width * 0.5).toBeCloseTo(corner[1]);
  });
});

describe("estado visible de cada puesto (solo lo que dice la API)", () => {
  it("un rol sin tarea es una silla vacía; uno con tarea tiene a su persona", () => {
    const agents = byId(agentList().agentes);
    expect(stationView(STATION.analyst!, agents)).toEqual({ state: "vacante", person: false, working: false });
    expect(stationView(STATION.trend_hunter!, agents)).toEqual({ state: "sin_ejecuciones", person: true, working: false });
  });

  it("solo trabaja con una ejecución pendiente o en curso registrada", () => {
    for (const actividad of ["pendiente", "en_curso"] as const) {
      const agents = byId([agent("trend_hunter", { actividad, ejecutado: true, ultima_ejecucion: run({ estado: "running", fin: null }) })]);
      expect(stationView(STATION.trend_hunter!, agents)).toMatchObject({ state: "trabajando", working: true });
    }
    for (const actividad of ["completada", "fallida", "bloqueada", "sin_ejecuciones"] as const) {
      const agents = byId([agent("trend_hunter", { actividad })]);
      expect(stationView(STATION.trend_hunter!, agents)).toMatchObject({ state: actividad, working: false });
    }
  });

  it("sin respuesta de la API el estado es desconocido y no aparece nadie", () => {
    expect(stationView(STATION.trend_hunter!, null)).toEqual({ state: "desconocido", person: false, working: false });
    expect(describeStation(STATION.trend_hunter!, null).status).toBe("Estado no disponible");
  });

  it("el puesto de VALIDAR está en preparación y no tiene agente", () => {
    expect(stationView(STATION.validar!, byId(agentList().agentes))).toEqual({ state: "preparacion", person: false, working: false });
    expect(describeStation(STATION.validar!, byId(agentList().agentes)).status).toBe("VALIDAR en preparación");
  });

  it("la pantalla del programador muestra su estado real", () => {
    expect(describeStation(STATION.programador!, null, scheduler()).status).toBe("Programador apagado");
    expect(describeStation(STATION.programador!, null, scheduler({ habilitado: true, en_ejecucion: true })).status).toBe("Programador en marcha");
    expect(describeStation(STATION.programador!, null).status).toBe("Pantalla de consulta");
  });

  it("la escena solo dibuja tecleo y luz de actividad para el agente en curso", () => {
    const agents = byId([
      agent("trend_hunter", { ejecutado: true, actividad: "en_curso", ultima_ejecucion: run({ estado: "running", fin: null }) }),
      agent("supervisor", { ejecutado: true, actividad: "completada", ultima_ejecucion: run({ agente: "supervisor" }) }),
      agent("analyst"),
    ]);
    const { container } = render(<OfficeScene agents={agents} />);
    const working = container.querySelectorAll('[data-state="trabajando"]');
    expect([...working].map((n) => n.closest("[data-station]")?.getAttribute("data-station"))).toEqual(["trend_hunter", "trend_hunter"]);
    expect(container.querySelector('[data-station="supervisor"]')?.getAttribute("data-state")).toBe("completada");
    expect(container.querySelector('[data-station="analyst"]')?.getAttribute("data-state")).toBe("vacante");
    // una sola luz de actividad y un solo par de brazos tecleando
    expect(container.querySelectorAll("circle[class*='live']")).toHaveLength(1);
    expect(container.querySelectorAll("g[class*='typing']")).toHaveLength(1);
  });

  it("sin ejecuciones activas no hay ningún movimiento de actividad", () => {
    const { container } = render(<OfficeScene agents={byId(agentList().agentes)} />);
    expect(container.querySelectorAll("circle[class*='live'], g[class*='typing'], g[class*='code']")).toHaveLength(0);
    // personas solo en los dos puestos con tarea implementada
    expect(container.querySelectorAll("g[class*='person']")).toHaveLength(2);
  });
});

describe("cámara", () => {
  it("la vista general encuadra el mundo entero", () => {
    const cam = cameraFor({ kind: "overview" }, 1440, 900);
    expect(cam.s * WORLD_W).toBeLessThanOrEqual(1440);
    expect(cam.s * WORLD_H).toBeLessThanOrEqual(900);
    expect(cam.x).toBe(WORLD_W / 2);
  });

  it("se acerca al centro de la pantalla del puesto elegido, sea cual sea", () => {
    for (const id of ["trend_hunter", "supervisor", "temas", "ejecuciones", "validar"]) {
      const cam = cameraFor({ kind: "station", id }, 1440, 900);
      const [cx, cy] = screenCenter(screenOf(STATION[id]!));
      expect(cam.x).toBeCloseTo(cx);
      expect(cam.y).toBeCloseTo(cy);
      expect(cam.s).toBeGreaterThan(cameraFor({ kind: "overview" }, 1440, 900).s * 2);
      expect(cam.s).toBeLessThanOrEqual(6);
    }
  });

  it("en móvil el acercamiento se adapta al ancho", () => {
    const phone = cameraFor({ kind: "station", id: "trend_hunter" }, 390, 520);
    const desktop = cameraFor({ kind: "station", id: "trend_hunter" }, 1440, 900);
    expect(phone.s).toBeLessThan(desktop.s);
    expect(screenOf(STATION.trend_hunter!).width * phone.s).toBeLessThanOrEqual(390 * 0.31);
  });
});
