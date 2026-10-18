import "../support/navigation";

import { render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { clearTopicNameCache } from "@/hooks/queries";
import { AgentsView } from "@/views/AgentsView";
import { ClassificationsView } from "@/views/ClassificationsView";
import { MetricsView } from "@/views/MetricsView";
import { CoordinationView } from "@/views/CoordinationView";
import { StationView, ValidationView } from "@/views/StationView";
import { RunsView } from "@/views/RunsView";
import { SchedulerView } from "@/views/SchedulerView";
import { TopicsView } from "@/views/TopicsView";
import { TrendsView } from "@/views/TrendsView";

import { mockApi } from "../support/api";
import { agentList, classification, definitions, metric, page, rules, scheduler, topic, TOPIC_ID } from "../support/fixtures";
import { nav } from "../support/navigation";

// Endpoints sin modo de datos: estado operativo y definiciones, comunes a ambos modos.
const MODE_AGNOSTIC = new Set(["/api/oficina/programador", "/api/oficina/metricas/definiciones", "/api/oficina/clasificaciones/reglas", "/api/oficina/salud"]);

function routes(mode: "real" | "simulated") {
  return {
    "/agentes": agentList({}, mode),
    "/agentes/trend_hunter/ejecuciones": { agente: "trend_hunter", data_mode: mode, limite: 20, ejecuciones: [] },
    "/programador": scheduler(),
    "/clasificaciones": page([], { data_mode: mode }),
    "/clasificaciones/reglas": rules,
    "/temas": page([], { data_mode: mode }),
    "/temas/vinculos": { data_mode: mode, limite: 50, desplazamiento: 0, items: [] },
    "/metricas": page([], { data_mode: mode }),
    "/metricas/definiciones": definitions,
  };
}

const VIEWS: [string, string, () => ReactElement][] = [
  ["Tendencias", "/tendencias", () => <TrendsView />],
  ["Centro de agentes", "/coordinacion", () => <CoordinationView />],
  ["Puesto de agente", "/puesto/trend_hunter", () => <StationView agentId="trend_hunter" />],
  ["Sala de validación", "/validar", () => <ValidationView />],
  ["Agentes", "/agentes", () => <AgentsView />],
  ["Ejecuciones", "/ejecuciones", () => <RunsView />],
  ["Programador", "/programador", () => <SchedulerView />],
  ["Temas", "/temas", () => <TopicsView />],
  ["Métricas", "/metricas", () => <MetricsView />],
  ["Clasificaciones", "/clasificaciones", () => <ClassificationsView />],
];

beforeEach(() => clearTopicNameCache());

describe.each(["real", "simulated"] as const)("modo %s: ninguna vista mezcla modos", (mode) => {
  it.each(VIEWS)("%s pide todos los datos en el mismo modo", async (_name, path, view) => {
    nav.reset(path, mode === "simulated" ? "modo=simulated" : "");
    const api = mockApi(routes(mode));
    render(view());
    await waitFor(() => expect(api.calls.length).toBeGreaterThan(0));
    await waitFor(() => expect(document.querySelector('[aria-busy="true"]')).toBeNull());
    for (const url of api.calls) {
      if (MODE_AGNOSTIC.has(url.pathname)) {
        expect(url.searchParams.has("data_mode"), url.href).toBe(false);
      } else {
        expect(url.searchParams.get("data_mode"), url.href).toBe(mode);
      }
    }
  });
});

describe("limitaciones y datos insuficientes", () => {
  beforeEach(() => nav.reset());

  it("una clasificación con datos insuficientes muestra la etapa y su motivo, sin inventar otra", async () => {
    mockApi({
      "/clasificaciones/reglas": rules,
      "/clasificaciones": page([
        classification({
          etapa: "datos_insuficientes",
          motivo: "sin_evidencia_temporal_suficiente",
          evidencia: [
            { fuente: "wikimedia", rol: "excluded", fuente_validada: true, etapa_propuesta: null, motivo: "sin métricas utilizables", ambitos: [] },
          ],
        }),
      ]),
      [`/temas/${TOPIC_ID}`]: { tema: topic(), alias: [], sujetos: [] },
    });
    render(<ClassificationsView />);
    const card = (await screen.findByRole("heading", { name: "Tema de prueba" })).closest("article")!;
    expect(within(card).getAllByText("Datos insuficientes").length).toBeGreaterThan(0);
    expect(within(card).getByText("sin_evidencia_temporal_suficiente")).toBeInTheDocument();
    expect(within(card).getByText("Excluida")).toBeInTheDocument();
    expect(within(card).getByText("sin métricas utilizables")).toBeInTheDocument();
    for (const stage of ["Emergente", "Acelerando", "Punto máximo", "Saturada"]) {
      expect(within(card).queryByText(stage)).toBeNull();
    }
  });

  it("si todos los valores son insuficientes, no hay gráfica ni ceros: «sin valor» y el motivo", async () => {
    nav.reset("/metricas", `tema_id=${TOPIC_ID}&metrica=wiki_views_total`);
    mockApi({
      "/metricas/definiciones": definitions,
      "/metricas": page([
        metric({ fecha_referencia: "2026-10-15", valor: null, estado: "insufficient", motivo: "sin días con datos" }),
        metric({ fecha_referencia: "2026-10-14", valor: null, estado: "insufficient", motivo: "sin días con datos" }),
      ]),
      [`/temas/${TOPIC_ID}`]: { tema: topic(), alias: [], sujetos: [] },
    });
    const { container } = render(<MetricsView />);
    expect(await screen.findByText("No se dibuja una serie")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Serie/ })).toBeNull();
    expect(screen.getAllByText("sin valor")).toHaveLength(2);
    expect(screen.getAllByText("sin días con datos")).toHaveLength(2);
    const values = [...container.querySelectorAll("tbody tr td:nth-child(5) .mono")].map((n) => n.textContent);
    expect(values).toEqual(["sin valor", "sin valor"]);
  });

  it("una serie con ventanas distintas no se dibuja", async () => {
    nav.reset("/metricas", `tema_id=${TOPIC_ID}&metrica=wiki_views_total`);
    mockApi({
      "/metricas/definiciones": definitions,
      "/metricas": page([metric({ fecha_referencia: "2026-10-15" }), metric({ fecha_referencia: "2026-10-14", ventana_dias: 14 })]),
      [`/temas/${TOPIC_ID}`]: { tema: topic(), alias: [], sujetos: [] },
    });
    render(<MetricsView />);
    expect(await screen.findByText(/más de una ventana/)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Serie/ })).toBeNull();
  });
});
