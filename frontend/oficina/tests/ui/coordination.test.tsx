import "../support/navigation";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { clearTopicNameCache } from "@/hooks/queries";
import { CoordinationView } from "@/views/CoordinationView";

import { mockApi, problem } from "../support/api";
import { agentList, classification, definitions, page, rules, run, scheduler, topic, TOPIC_ID } from "../support/fixtures";
import { nav } from "../support/navigation";

function baseRoutes(overrides: Record<string, unknown> = {}) {
  return {
    "/agentes": agentList(),
    "/programador": scheduler(),
    "/clasificaciones": page([]),
    "/temas": page([]),
    "/metricas": page([]),
    "/metricas/definiciones": definitions,
    "/clasificaciones/reglas": rules,
    ...overrides,
  };
}

beforeEach(() => {
  nav.reset();
  clearTopicNameCache();
});

describe("Centro de agentes (computador de coordinación)", () => {
  it("muestra los seis agentes y distingue implementados de planificados", async () => {
    mockApi(baseRoutes());
    render(<CoordinationView />);
    await screen.findByRole("button", { name: /Agente trend_hunter/ });
    for (const id of ["trend_hunter", "format_hunter", "analyst", "audience_filter", "strategist", "supervisor"]) {
      expect(screen.getByRole("button", { name: new RegExp(`Agente ${id}`) })).toBeInTheDocument();
    }
    expect(screen.getAllByText("Sin tarea implementada")).toHaveLength(4);
  });

  it("los indicadores salen de los campos reales de /agentes", async () => {
    mockApi(
      baseRoutes({
        "/agentes": agentList({
          trend_hunter: { ejecutado: true, actividad: "en_curso", ultima_ejecucion: run({ estado: "running", fin: null }) },
          supervisor: { ejecutado: true, actividad: "fallida", ultima_ejecucion: run({ id: "run_2", agente: "supervisor", estado: "failed" }) },
        }),
      }),
    );
    render(<CoordinationView />);
    await screen.findByRole("button", { name: /Agente trend_hunter/ });
    const kpi = (name: string) => screen.getByText(name, { selector: "span" }).closest("div")!.querySelector("span")!.textContent;
    expect(kpi("Definidos")).toBe("6");
    expect(kpi("Con tarea")).toBe("2");
    expect(kpi("Con ejecuciones")).toBe("2");
    expect(kpi("Activos ahora")).toBe("1");
    expect(kpi("Fallidas o bloqueadas")).toBe("1");
    expect(kpi("Sin actividad")).toBe("4");
    // la actividad en curso se muestra solo en el agente que la tiene registrada
    expect(within(screen.getByRole("button", { name: /Agente trend_hunter/ })).getByText("En curso")).toBeInTheDocument();
    for (const id of ["format_hunter", "analyst", "audience_filter", "strategist", "supervisor"]) {
      expect(within(screen.getByRole("button", { name: new RegExp(`Agente ${id}`) })).queryByText("En curso")).toBeNull();
    }
  });

  it("sin ejecuciones no hay ningún indicador de actividad animado", async () => {
    mockApi(baseRoutes());
    const { container } = render(<CoordinationView />);
    await screen.findByRole("button", { name: /Agente trend_hunter/ });
    expect(screen.getAllByText("Sin ejecuciones").length).toBeGreaterThanOrEqual(6);
    expect(container.textContent).not.toMatch(/En curso|Pendiente/);
    expect(await screen.findByText("Ningún agente tiene ejecuciones registradas")).toBeInTheDocument();
  });

  it("muestra estados vacíos comprensibles y la limitación de calibración", async () => {
    mockApi(baseRoutes());
    render(<CoordinationView />);
    expect(await screen.findByText("Sin clasificaciones")).toBeInTheDocument();
    expect(screen.getByText("Sin temas")).toBeInTheDocument();
    expect(await screen.findByText("Sin calibrar")).toBeInTheDocument();
    expect(screen.getByText(/Deshabilitado/)).toBeInTheDocument();
  });

  it("no muestra puntuaciones de saturación, oportunidad ni confianza", async () => {
    mockApi(baseRoutes({ "/clasificaciones": page([classification()]), "/temas/tpc_0123456789abcdef": { tema: topic(), alias: [], sujetos: [] } }));
    const { container } = render(<CoordinationView />);
    await screen.findByText("Tema de prueba");
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\d+\s*%/);
    expect(text).not.toMatch(/oportunidad:\s*\d|confianza:\s*\d|saturación:\s*\d/i);
  });

  it("resuelve el nombre del tema de una clasificación", async () => {
    mockApi(baseRoutes({ "/clasificaciones": page([classification()]), [`/temas/${TOPIC_ID}`]: { tema: topic(), alias: [], sujetos: [] } }));
    render(<CoordinationView />);
    expect(await screen.findByText("Tema de prueba")).toBeInTheDocument();
    expect(screen.getAllByText("Acelerando").length).toBeGreaterThan(0);
  });

  it("un error de red muestra un mensaje y permite reintentar sin inventar datos", async () => {
    const api = mockApi(baseRoutes({ "/agentes": problem(502, "detectar_no_disponible", "No se pudo conectar con DETECTAR") }));
    render(<CoordinationView />);
    const alerts = await screen.findAllByRole("alert");
    expect(alerts[0]).toHaveTextContent("No se pudo conectar con DETECTAR");
    expect(screen.queryByRole("button", { name: /Agente trend_hunter/ })).toBeNull();

    api.set("/agentes", agentList());
    await userEvent.click(within(alerts[0]!).getByRole("button", { name: /Reintentar/ }));
    expect(await screen.findByRole("button", { name: /Agente trend_hunter/ })).toBeInTheDocument();
  });

  it("la actualización manual vuelve a consultar y conserva los datos si falla", async () => {
    const api = mockApi(baseRoutes());
    render(<CoordinationView />);
    await screen.findByRole("button", { name: /Agente trend_hunter/ });
    const before = api.calls.filter((u) => u.pathname === "/api/oficina/agentes").length;
    api.set("/agentes", problem(504, "tiempo_agotado", "DETECTAR no respondió a tiempo"));
    const refresh = await screen.findByRole("button", { name: "Actualizar" });
    await waitFor(() => expect(refresh).toBeEnabled());
    await userEvent.click(refresh);
    await waitFor(() => expect(api.calls.filter((u) => u.pathname === "/api/oficina/agentes").length).toBeGreaterThan(before));
    expect((await screen.findAllByText(/No se pudo actualizar/)).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Agente trend_hunter/ })).toBeInTheDocument();
  });

  it("abre el detalle de un agente con su historial y lo cierra devolviendo el foco", async () => {
    mockApi(
      baseRoutes({
        "/agentes/supervisor/ejecuciones": { agente: "supervisor", data_mode: "real", limite: 20, ejecuciones: [run({ agente: "supervisor" })] },
      }),
    );
    render(<CoordinationView />);
    const station = await screen.findByRole("button", { name: /Agente supervisor/ });
    await userEvent.click(station);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Agente supervisor" })).toBeInTheDocument();
    expect(await within(dialog).findByText("run_0001")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cerrar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(station).toHaveFocus();
  });

  it("un agente planificado explica que no tiene tarea", async () => {
    mockApi(baseRoutes({ "/agentes/analyst/ejecuciones": { agente: "analyst", data_mode: "real", limite: 20, ejecuciones: [] } }));
    render(<CoordinationView />);
    await userEvent.click(await screen.findByRole("button", { name: /Agente analyst/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/no tiene tarea implementada/)).toBeInTheDocument();
    expect(await within(dialog).findByText("Sin ejecuciones registradas")).toBeInTheDocument();
  });

  it("pide los datos al intermediario con el modo indicado en la URL", async () => {
    nav.reset("/", "modo=simulated");
    const api = mockApi(baseRoutes({ "/agentes": agentList({}, "simulated") }));
    render(<CoordinationView />);
    await screen.findByRole("button", { name: /Agente trend_hunter/ });
    const agentsCall = api.calls.find((u) => u.pathname === "/api/oficina/agentes")!;
    expect(agentsCall.searchParams.get("data_mode")).toBe("simulated");
    expect(api.calls.every((u) => u.pathname.startsWith("/api/oficina/"))).toBe(true);
  });
});
