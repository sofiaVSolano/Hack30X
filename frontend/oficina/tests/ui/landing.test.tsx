import "../support/navigation";

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { clearTopicNameCache } from "@/hooks/queries";
import { LandingView } from "@/views/landing/LandingView";

import { mockApi } from "../support/api";
import { agentList, classification, metric, page, rules, topic } from "../support/fixtures";
import { nav } from "../support/navigation";

const A = "tpc_aaaaaaaaaaaaaaaa";
const B = "tpc_bbbbbbbbbbbbbbbb";
const LATEST = "2026-10-16";
const AS_OF = "2026-10-15";

function routes() {
  const older = [
    classification({ id: 1, tema_id: A, etapa: "acelerando", fecha_referencia: AS_OF }),
    classification({ id: 2, tema_id: B, etapa: "emergente", fecha_referencia: AS_OF }),
  ];
  const latest = [classification({ id: 3, tema_id: A, etapa: "datos_insuficientes", fecha_referencia: LATEST })];
  return {
    "/clasificaciones/reglas": { ...rules, parametros: { window_days: 7, growth_min: 0.2, acceleration_min: 0.1, flat_band: 0.1, calibrated: false } },
    "/clasificaciones": (url: URL) => {
      const date = url.searchParams.get("fecha_referencia");
      if (date === AS_OF) return page(older);
      if (date === LATEST) return page(latest);
      return page([...latest, ...older]);
    },
    "/temas": page([topic({ id: A, nombre: "keke palmer" }), topic({ id: B, nombre: "frente frío" })]),
    // Al último día le faltan visitas de Wikipedia: la portada usa el anterior, igual que Tendencias.
    "/metricas": (url: URL) =>
      url.searchParams.get("fecha_referencia") === LATEST
        ? page([metric({ tema_id: A, metrica: "wiki_views_growth", estado: "insufficient", valor: null, motivo: "current_missing_days:2" })])
        : page([]),
    "/agentes": agentList({ trend_hunter: { nombre: "Cazador de tendencias", actividad: "completada" } }),
  };
}

beforeEach(() => {
  nav.reset("/");
  clearTopicNameCache();
});

describe("Portada", () => {
  it("muestra la parrilla real del último día completo, con la etapa de cada tema", async () => {
    mockApi(routes());
    render(<LandingView />);
    const row = await screen.findByRole("button", { name: /Keke palmer/ });
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(within(row).getByText("Acelerando")).toBeInTheDocument();
    expect(screen.getAllByText(/jueves, 15 de octubre/).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /Ver la evidencia/ })).toHaveAttribute("href", `/clasificaciones?tema_id=${A}`);
  });

  it("abre otra fila al elegirla", async () => {
    mockApi(routes());
    render(<LandingView />);
    const other = await screen.findByRole("button", { name: /Frente frío/ });
    await userEvent.click(other);
    expect(other).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /Keke palmer/ })).toHaveAttribute("aria-expanded", "false");
  });

  it("escribe las reglas con los umbrales que devuelve la API y dice que no están calibradas", async () => {
    mockApi(routes());
    render(<LandingView />);
    expect(await screen.findByText(/suben al menos un 20\s?%/)).toBeInTheDocument();
    expect(screen.getByText(/provisionales, sin calibrar con datos reales/)).toBeInTheDocument();
  });

  it("pide siempre datos reales, aunque la URL diga simulado", async () => {
    nav.reset("/", "modo=simulated");
    const api = mockApi(routes());
    render(<LandingView />);
    await screen.findByRole("button", { name: /Keke palmer/ });
    const modes = api.calls.map((u) => u.searchParams.get("data_mode")).filter(Boolean);
    expect(modes.length).toBeGreaterThan(0);
    expect(new Set(modes)).toEqual(new Set(["real"]));
  });

  it("muestra a los agentes con su estado real y lleva a la oficina", async () => {
    mockApi(routes());
    render(<LandingView />);
    const link = await screen.findByRole("link", { name: /Cazador de tendencias: Completada/ });
    expect(link).toHaveAttribute("href", "/oficina");
  });
});

describe("Portada: primera pantalla", () => {
  it("nombra los temas reales en emisión", async () => {
    mockApi(routes());
    render(<LandingView />);
    expect(await screen.findByText("Keke palmer, Frente frío")).toBeInTheDocument();
  });
});
