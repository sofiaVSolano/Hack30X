import "../support/navigation";

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { LandingView } from "@/views/landing/LandingView";

import { mockApi } from "../support/api";
import { agentList, run } from "../support/fixtures";
import { nav } from "../support/navigation";

beforeEach(() => nav.reset("/"));

describe("Portada", () => {
  it("presenta la propuesta en una frase y una sola acción: entrar a la oficina", () => {
    mockApi({ "/agentes": agentList() });
    render(<LandingView />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Las tendencias no esperan. Anticípate.");
    const cta = screen.getByRole("link", { name: /Entrar a la oficina/ });
    expect(cta).toHaveAttribute("href", "/oficina");
    expect(cta).toHaveAttribute("data-transition-types", "entrar-oficina");
    // saltar al contenido, la marca y la acción principal
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(3);
    expect(links[0]).toHaveAccessibleName("Saltar al contenido");
    expect(links[1]).toHaveAccessibleName("HACK 30X: portada");
    expect(links[2]).toBe(cta);
  });

  it("no muestra indicadores operativos ni cifras antes de entrar", () => {
    mockApi({ "/agentes": agentList() });
    const { container } = render(<LandingView />);
    expect(container.textContent).not.toMatch(/\d+\s*(temas|agentes|%)/);
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("la ilustración es la oficina real: decorativa y con el estado que da la API en modo real", async () => {
    nav.reset("/", "modo=simulated");
    const api = mockApi({
      "/agentes": agentList({ trend_hunter: { ejecutado: true, actividad: "completada", ultima_ejecucion: run() } }),
    });
    const { container } = render(<LandingView />);
    const svg = container.querySelector("svg[data-interactive='false']")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    await waitFor(() => expect(container.querySelectorAll("g[class*='person']")).toHaveLength(2));
    expect(container.querySelector('[data-station="trend_hunter"]')).toHaveAttribute("data-state", "completada");
    expect(container.querySelectorAll("g[class*='typing']")).toHaveLength(0);
    expect(new Set(api.calls.map((u) => u.searchParams.get("data_mode")))).toEqual(new Set(["real"]));
  });
});
