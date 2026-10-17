import "../support/navigation";

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearTopicNameCache } from "@/hooks/queries";
import { ClassificationsView } from "@/views/ClassificationsView";
import { MetricsView } from "@/views/MetricsView";
import { RunsView } from "@/views/RunsView";
import { SchedulerView } from "@/views/SchedulerView";
import { TopicsView } from "@/views/TopicsView";

import { mockApi } from "../support/api";
import { agentList, classification, definitions, metric, page, rules, run, scheduler, topic, TOPIC_ID } from "../support/fixtures";
import { nav } from "../support/navigation";

beforeEach(() => {
  nav.reset();
  clearTopicNameCache();
});

const topicDetail = { tema: topic(), alias: [], sujetos: [] };

describe("Clasificaciones", () => {
  it("muestra calibrado=false y fuente_validada=false sin elevar la evidencia", async () => {
    mockApi({ "/clasificaciones/reglas": rules, "/clasificaciones": page([classification()]), [`/temas/${TOPIC_ID}`]: topicDetail });
    render(<ClassificationsView />);
    const card = (await screen.findByRole("heading", { name: "Tema de prueba" })).closest("article")!;
    expect(within(card).getByText("Sin calibrar")).toBeInTheDocument();
    const gdeltRow = within(card).getByText("GDELT").closest("tr")!;
    expect(within(gdeltRow).getByText("Fuente no validada")).toBeInTheDocument();
    expect(within(gdeltRow).getByText("Complementaria")).toBeInTheDocument();
    expect(screen.getByText(/umbrales de las etapas son provisionales/)).toBeInTheDocument();
  });

  it("marca las clasificaciones simuladas", async () => {
    nav.reset("/clasificaciones", "modo=simulated");
    mockApi({
      "/clasificaciones/reglas": rules,
      "/clasificaciones": page([classification({ data_mode: "simulated" })], { data_mode: "simulated" }),
      [`/temas/${TOPIC_ID}`]: { ...topicDetail, tema: topic({ data_mode: "simulated" }) },
    });
    render(<ClassificationsView />);
    const card = (await screen.findByRole("heading", { name: "Tema de prueba" })).closest("article")!;
    expect(within(card).getByText("Simulado")).toBeInTheDocument();
  });

  it("filtra por etapa a través de la URL", async () => {
    const api = mockApi({ "/clasificaciones/reglas": rules, "/clasificaciones": page([]) });
    render(<ClassificationsView />);
    await screen.findByText("Sin clasificaciones");
    await userEvent.selectOptions(screen.getByLabelText("Etapa"), "emergente");
    expect(nav.replace).toHaveBeenLastCalledWith("/clasificaciones?etapa=emergente");
    expect(api.calls[0]!.searchParams.get("etapa")).toBeNull();
  });

  it("muestra la explicación completa bajo demanda", async () => {
    mockApi({ "/clasificaciones/reglas": rules, "/clasificaciones": page([classification()]), [`/temas/${TOPIC_ID}`]: topicDetail });
    render(<ClassificationsView />);
    const toggle = await screen.findByRole("button", { name: /Ver explicación completa/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("explicacion")).toBeInTheDocument();
  });
});

describe("Temas", () => {
  it("busca con el texto escrito (con espera) y muestra el estado vacío", async () => {
    const api = mockApi({ "/temas": (url: URL) => (url.searchParams.get("q") ? page([]) : page([topic()])) });
    render(<TopicsView />);
    expect(await screen.findByRole("button", { name: "Tema de prueba" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Buscar tema"), "xyz");
    expect(await screen.findByText("Ningún tema coincide con la búsqueda", {}, { timeout: 2000 })).toBeInTheDocument();
    expect(api.calls.some((u) => u.searchParams.get("q") === "xyz")).toBe(true);
    expect(api.calls.some((u) => u.searchParams.get("q") === "x")).toBe(false);
  });

  it("abre el detalle del tema con alias, sujetos y vínculos", async () => {
    mockApi({
      "/temas": page([topic({ ambiguo: true, motivo_ambiguedad: "nombre compartido" })]),
      [`/temas/${TOPIC_ID}`]: {
        tema: topic({ ambiguo: true, motivo_ambiguedad: "nombre compartido" }),
        alias: [{ texto: "TdP", normalizado: "tdp", tipo: "acronym", origen: "manual:ana", creado: "2026-10-10T10:00:00Z" }],
        sujetos: [{ fuente: "wikimedia", sujeto_original: "Tema_de_prueba", observaciones: 3 }],
      },
      "/temas/vinculos": { data_mode: "real", limite: 50, desplazamiento: 0, items: [] },
      "/clasificaciones": page([]),
    });
    render(<TopicsView />);
    expect(await screen.findByText("Ambiguo")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Tema de prueba" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("TdP")).toBeInTheDocument();
    expect(within(dialog).getByText("Tema_de_prueba")).toBeInTheDocument();
    expect(within(dialog).getByText("Marcado como ambiguo")).toBeInTheDocument();
    expect(await within(dialog).findByText("Sin vínculos vigentes.")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Ver métricas" })).toHaveAttribute("href", `/metricas?tema_id=${TOPIC_ID}`);
  });

  it("la cola de revisión consulta needs_review", async () => {
    const api = mockApi({ "/temas": page([]), "/temas/vinculos": { data_mode: "real", limite: 50, desplazamiento: 0, items: [] } });
    render(<TopicsView />);
    await userEvent.click(screen.getByRole("tab", { name: "Cola de revisión" }));
    expect(await screen.findByText("Nada pendiente de revisión")).toBeInTheDocument();
    expect(api.calls.find((u) => u.pathname.endsWith("/vinculos"))!.searchParams.get("estado")).toBe("needs_review");
  });
});

describe("Métricas", () => {
  it("dibuja una serie solo con tema y métrica, y deja los insuficientes como huecos", async () => {
    nav.reset("/metricas", `tema_id=${TOPIC_ID}&metrica=wiki_views_total`);
    mockApi({
      "/metricas/definiciones": definitions,
      "/metricas": page([
        metric({ fecha_referencia: "2026-10-15", valor: 140 }),
        metric({ fecha_referencia: "2026-10-14", valor: null, estado: "insufficient", motivo: "sin días suficientes" }),
        metric({ fecha_referencia: "2026-10-13", valor: 120 }),
        metric({ fecha_referencia: "2026-10-12", valor: 100 }),
      ]),
      [`/temas/${TOPIC_ID}`]: topicDetail,
    });
    const { container } = render(<MetricsView />);
    expect(await screen.findByRole("img", { name: /Serie de wiki_views_total/ })).toBeInTheDocument();
    const chart = screen.getByRole("img", { name: /Serie de wiki_views_total/ });
    expect(chart.querySelectorAll("circle")).toHaveLength(3);
    expect(container.textContent).toContain("×");
    expect(screen.getAllByText("sin valor").length).toBe(1);
    expect(screen.getByText("sin días suficientes")).toBeInTheDocument();
  });

  it("con un solo valor válido no dibuja una serie", async () => {
    nav.reset("/metricas", `tema_id=${TOPIC_ID}&metrica=wiki_views_total`);
    mockApi({ "/metricas/definiciones": definitions, "/metricas": page([metric()]), [`/temas/${TOPIC_ID}`]: topicDetail });
    render(<MetricsView />);
    expect(await screen.findByText("No se dibuja una serie")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Serie/ })).toBeNull();
  });

  it("muestra la fuente no validada y el estado vacío sin ceros", async () => {
    mockApi({
      "/metricas/definiciones": definitions,
      "/metricas": page([metric({ fuente: "gdelt", metrica: "gdelt_articles_total", unidad: "articles", fuente_validada: false })]),
      [`/temas/${TOPIC_ID}`]: topicDetail,
    });
    render(<MetricsView />);
    expect(await screen.findByText("Fuente no validada")).toBeInTheDocument();
  });

  it("estado vacío explícito", async () => {
    mockApi({ "/metricas/definiciones": definitions, "/metricas": page([]) });
    render(<MetricsView />);
    expect(await screen.findByText("Sin valores calculados")).toBeInTheDocument();
    expect(screen.getByText(/Ausencia de datos no equivale a cero/)).toBeInTheDocument();
  });
});

describe("Ejecuciones", () => {
  it("filtra por estado y abre el detalle con el error registrado", async () => {
    nav.reset("/ejecuciones", "agente=trend_hunter");
    mockApi({
      "/agentes": agentList(),
      "/agentes/trend_hunter/ejecuciones": {
        agente: "trend_hunter",
        data_mode: "real",
        limite: 20,
        ejecuciones: [
          run(),
          run({ id: "run_0002", estado: "failed", codigo_error: "task_error", detalle_error: "La recolección falló.", fin: null }),
        ],
      },
    });
    render(<RunsView />);
    expect(await screen.findByText("run_0002")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Estado"), "failed");
    expect(screen.queryByText("run_0001")).toBeNull();
    // sin fin registrado no se calcula duración
    const row = screen.getByText("run_0002").closest("tr")!;
    expect(within(row).getByText("—")).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: /Ver/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Error registrado: task_error")).toBeInTheDocument();
    expect(within(dialog).getByText("No calculable: falta inicio o fin")).toBeInTheDocument();
  });

  it("ordena por columna con aria-sort", async () => {
    nav.reset("/ejecuciones", "agente=trend_hunter");
    mockApi({
      "/agentes": agentList(),
      "/agentes/trend_hunter/ejecuciones": {
        agente: "trend_hunter",
        data_mode: "real",
        limite: 20,
        ejecuciones: [run({ id: "run_a", solicitado: "2026-10-16T10:00:00Z" }), run({ id: "run_b", solicitado: "2026-10-16T12:00:00Z" })],
      },
    });
    render(<RunsView />);
    await screen.findByText("run_a");
    const header = screen.getByRole("columnheader", { name: /Solicitada/ });
    expect(header).toHaveAttribute("aria-sort", "descending");
    const ids = () => screen.getAllByText(/^run_[ab]$/).map((n) => n.textContent);
    expect(ids()).toEqual(["run_b", "run_a"]);
    await userEvent.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "ascending");
    expect(ids()).toEqual(["run_a", "run_b"]);
  });

  it("cambiar de agente actualiza la URL", async () => {
    nav.reset("/ejecuciones");
    mockApi({ "/agentes": agentList(), "/agentes/trend_hunter/ejecuciones": { agente: "trend_hunter", data_mode: "real", limite: 20, ejecuciones: [] } });
    render(<RunsView />);
    expect(await screen.findByText("Sin ejecuciones registradas")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Agente"), "supervisor");
    expect(nav.replace).toHaveBeenLastCalledWith("/ejecuciones?agente=supervisor");
  });
});

describe("Programador", () => {
  it("muestra motivos de omisión y no ofrece controles para activarlo", async () => {
    mockApi({ "/programador": scheduler() });
    render(<SchedulerView />);
    expect((await screen.findAllByText("Sin tarea implementada")).length).toBe(4);
    expect(screen.getAllByText("Sin frecuencia configurada")).toHaveLength(2);
    expect(screen.getByText("Sin ticks en este proceso")).toBeInTheDocument();
    const names = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    expect(names.some((n) => /activar|desactivar|ejecutar|iniciar/i.test(n))).toBe(false);
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("muestra el último tick real con sus errores", async () => {
    mockApi({
      "/programador": scheduler({
        habilitado: true,
        en_ejecucion: true,
        ultimo_tick: { momento: "2026-10-16T21:00:00Z", recuperacion: null, lanzadas: ["supervisor"], no_vencidas: [], ocupadas: [], errores: [{ agente: "trend_hunter", error: "AgentBusyError" }] },
      }),
    });
    render(<SchedulerView />);
    expect(await screen.findByText("Errores del tick")).toBeInTheDocument();
    const tick = screen.getByRole("heading", { name: "Último tick" }).closest("section")!;
    expect(within(tick).getByText("supervisor")).toBeInTheDocument();
    expect(screen.getByText("Habilitado")).toBeInTheDocument();
  });
});

describe("Sondeo", () => {
  it("no consulta con la pestaña oculta y reanuda al volver", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = mockApi({ "/programador": scheduler() });
    let visibility: DocumentVisibilityState = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
    render(<SchedulerView />);
    await screen.findByText("Sin ticks en este proceso");
    const count = () => api.calls.filter((u) => u.pathname === "/api/oficina/programador").length;
    await waitFor(() => expect(count()).toBeGreaterThanOrEqual(1));
    const initial = count();

    visibility = "hidden";
    await act(async () => {
      vi.advanceTimersByTime(65_000);
    });
    expect(count()).toBe(initial);

    visibility = "visible";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await waitFor(() => expect(count()).toBe(initial + 1));
  });
});
