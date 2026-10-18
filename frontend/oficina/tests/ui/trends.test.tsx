import "../support/navigation";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { clearTopicNameCache } from "@/hooks/queries";
import { plainReason } from "@/lib/plain";
import { TrendsView } from "@/views/TrendsView";

import { mockApi } from "../support/api";
import { classification, metric, page, topic } from "../support/fixtures";
import { nav } from "../support/navigation";

const A = "tpc_aaaaaaaaaaaaaaaa";
const B = "tpc_bbbbbbbbbbbbbbbb";
const C = "tpc_cccccccccccccccc";
const D = "tpc_dddddddddddddddd";
const AS_OF = "2026-10-15";

const wikiEvidence = (rule: string) => ({
  fuente: "wikimedia" as const,
  rol: "excluded" as const,
  fuente_validada: true,
  etapa_propuesta: null,
  motivo: "ningún ámbito aporta señal",
  ambitos: [{ scope: "es.wikipedia.org:X", proposed_stage: null, rule, explanation: "…" }],
});

function routes() {
  const items = [
    classification({ id: 1, tema_id: A, etapa: "acelerando", fecha_referencia: AS_OF }),
    classification({ id: 2, tema_id: B, etapa: "punto_maximo", fecha_referencia: AS_OF }),
    classification({ id: 3, tema_id: C, etapa: "datos_insuficientes", motivo: "sin_evidencia_temporal_suficiente", evidencia: [wikiEvidence("W7")], fecha_referencia: AS_OF }),
  ];
  const views = [10, 11, 12, 13].map((i) =>
    metric({ tema_id: A, metrica: "wiki_views_total", ambito: "es.wikipedia.org:Keke_Palmer", fecha_referencia: `2026-10-${i + 2}`, valor: 1000 + i * 100 }),
  );
  return {
    "/clasificaciones": (url: URL) => (url.searchParams.get("fecha_referencia") ? page(items) : page([items[0]!], { total: 3 })),
    "/temas": page([
      topic({ id: A, nombre: "keke palmer", vinculos_por_fuente: { google_trends_rss: 2, wikimedia: 45 } }),
      topic({ id: B, nombre: "manzanillo", vinculos_por_fuente: { google_trends_rss: 1, wikimedia: 45 } }),
      topic({ id: C, nombre: "nicki minaj", vinculos_por_fuente: { google_trends_rss: 1, wikimedia: 45 } }),
      topic({ id: D, nombre: "clima hoy", vinculos_por_fuente: { google_trends_rss: 1 } }),
    ]),
    "/metricas": (url: URL) =>
      url.searchParams.get("metrica") === "wiki_views_growth"
        ? page([metric({ tema_id: A, metrica: "wiki_views_growth", unidad: "growth_rate", ambito: "es.wikipedia.org:Keke_Palmer", valor: 0.35, fecha_referencia: AS_OF })])
        : page(views),
  };
}

beforeEach(() => {
  nav.reset("/");
  clearTopicNameCache();
});

describe("Tendencias (página de inicio en lenguaje simple)", () => {
  it("agrupa los temas según la etapa que devuelve la API", async () => {
    mockApi(routes());
    render(<TrendsView />);
    const fast = await screen.findByRole("region", { name: /Creciendo cada vez más rápido/ });
    expect(within(fast).getByRole("heading", { name: "Keke palmer" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /En su punto más alto/ })).getByRole("heading", { name: "Manzanillo" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /Empezando a crecer/ })).getByText("Ningún tema en esta etapa ahora mismo.")).toBeInTheDocument();
  });

  it("muestra el crecimiento real y las visitas de la última ventana, sin inventar valores", async () => {
    mockApi(routes());
    render(<TrendsView />);
    const card = (await screen.findByRole("heading", { name: "Keke palmer" })).closest("li")!;
    await waitFor(() => expect(within(card).getByText(/visitas en Wikipedia en 7 días/)).toBeInTheDocument());
    expect(within(card).getByText("2300")).toBeInTheDocument(); // último total de 7 días de la serie (1000 + 13 × 100)
    expect(within(card).getByText(/\+35\s?% frente a la semana anterior/)).toBeInTheDocument();
    expect(within(card).getByText("Visto en Google Trends y Wikipedia")).toBeInTheDocument();
    // Sin crecimiento calculado no se muestra ningún porcentaje.
    const other = screen.getByRole("heading", { name: "Manzanillo" }).closest("li")!;
    expect(other.textContent).not.toMatch(/%/);
  });

  it("explica «Sin señal clara» con la regla real aplicada a Wikipedia", async () => {
    mockApi(routes());
    render(<TrendsView />);
    expect(await screen.findByText(/Sin señal clara: 1 temas/)).toBeInTheDocument();
    expect(screen.getByText("Sus visitas en Wikipedia están bajando.")).toBeInTheDocument();
  });

  it("lista las tendencias de hoy que no tienen historial en Wikipedia", async () => {
    mockApi(routes());
    render(<TrendsView />);
    expect(await screen.findByText(/Tendencias de hoy sin historial: 1 temas/)).toBeInTheDocument();
    expect(screen.getByText("Clima hoy.")).toBeInTheDocument();
  });

  it("aclara que la etapa no dice si el tema conviene ni hay saturación", async () => {
    mockApi(routes());
    render(<TrendsView />);
    expect(await screen.findByText(/no si te conviene/)).toBeInTheDocument();
    expect(screen.getByText(/no hay medida de saturación/)).toBeInTheDocument();
  });

  it("sin clasificaciones explica cómo traer tendencias reales", async () => {
    mockApi({ "/clasificaciones": page([]), "/temas": page([]) });
    render(<TrendsView />);
    expect(await screen.findByText("Todavía no hay tendencias calculadas")).toBeInTheDocument();
    expect(screen.getByText("npm run tendencias:actualizar")).toBeInTheDocument();
  });

  it("pide todo en el modo de la URL", async () => {
    nav.reset("/", "modo=simulated");
    const api = mockApi(routes());
    render(<TrendsView />);
    await screen.findByRole("heading", { name: "Keke palmer" });
    for (const url of api.calls) expect(url.searchParams.get("data_mode"), url.href).toBe("simulated");
  });
});

describe("fecha con datos de Wikipedia incompletos", () => {
  it("muestra el día anterior, lo avisa y permite ver el más reciente", async () => {
    const latest = classification({ id: 9, tema_id: A, etapa: "datos_insuficientes", motivo: "sin_evidencia_temporal_suficiente", fecha_referencia: "2026-10-16" });
    const previous = classification({ id: 1, tema_id: A, etapa: "acelerando", fecha_referencia: AS_OF });
    mockApi({
      ...routes(),
      "/clasificaciones": (url: URL) => {
        const date = url.searchParams.get("fecha_referencia");
        if (date === "2026-10-16") return page([latest]);
        if (date === AS_OF) return page([previous]);
        return page([latest, previous]);
      },
      "/metricas": (url: URL) =>
        url.searchParams.get("fecha_referencia") === "2026-10-16"
          ? page([metric({ tema_id: A, metrica: "wiki_views_growth", estado: "insufficient", valor: null, motivo: "current_missing_days:1", fecha_referencia: "2026-10-16" })])
          : page([]),
    });
    render(<TrendsView />);
    const fast = await screen.findByRole("region", { name: /Creciendo cada vez más rápido/ });
    expect(within(fast).getByRole("heading", { name: "Keke palmer" })).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("todavía no tiene completas las visitas de Wikipedia");
    await userEvent.click(screen.getByRole("button", { name: /igualmente/ }));
    expect(await screen.findByText(/Sin señal clara: 1 temas/)).toBeInTheDocument();
    expect(screen.queryByRole("note")).toBeNull();
  });
});

describe("plainReason", () => {
  it.each([
    ["W6", "estables"],
    ["W7", "bajando"],
    ["W8", "suben poco"],
    ["W4", "más despacio"],
    ["W0", "No hay suficientes días"],
  ])("traduce la regla %s", (rule, text) => {
    expect(plainReason(classification({ etapa: "datos_insuficientes", evidencia: [wikiEvidence(rule)] }))).toMatch(text);
  });

  it("sin regla conocida usa el motivo de la API", () => {
    expect(plainReason(classification({ etapa: "datos_insuficientes", motivo: "solo_fuente_no_validada", evidencia: [] }))).toMatch(
      /fuente que todavía no está validada/,
    );
  });
});
