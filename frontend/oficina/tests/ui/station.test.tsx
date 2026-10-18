import "../support/navigation";

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { StationView, ValidationView } from "@/views/StationView";

import { mockApi } from "../support/api";
import { agentList, run } from "../support/fixtures";
import { nav } from "../support/navigation";

const history = (agente: string, ejecuciones: unknown[] = []) => ({ agente, data_mode: "real", limite: 20, ejecuciones });

beforeEach(() => nav.reset("/puesto/analyst"));

describe("computador del puesto de un agente", () => {
  it("un agente de un módulo pendiente muestra su ficha y avisa de que el módulo no existe aún", async () => {
    mockApi({ "/agentes": agentList({ analyst: { nombre: "Analista", alcance: "entender" } }), "/agentes/analyst/ejecuciones": history("analyst") });
    const { container } = render(<StationView agentId="analyst" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Analista" })).toBeInTheDocument();
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("ENTENDER está en preparación");
    expect(note).toHaveTextContent(/no muestra análisis, resultados ni puntuaciones/);
    expect(screen.getByText(/no tiene tarea implementada/)).toBeInTheDocument();
    expect(await screen.findByText("Sin ejecuciones registradas")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d+\s*%/);
  });

  it("un agente funcional muestra su historial real sin aviso de preparación", async () => {
    nav.reset("/puesto/trend_hunter");
    mockApi({
      "/agentes": agentList({ trend_hunter: { nombre: "Cazador de tendencias", ejecutado: true, actividad: "completada", ultima_ejecucion: run() } }),
      "/agentes/trend_hunter/ejecuciones": history("trend_hunter", [run()]),
    });
    render(<StationView agentId="trend_hunter" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Cazador de tendencias" })).toBeInTheDocument();
    expect(screen.queryByText(/en preparación/)).toBeNull();
    expect(await screen.findByText("run_0001")).toBeInTheDocument();
  });

  it("un puesto sin agente registrado lo dice", async () => {
    mockApi({ "/agentes": agentList() });
    render(<StationView agentId="desconocido" />);
    expect(await screen.findByText("Este puesto no tiene un agente registrado")).toBeInTheDocument();
  });
});

describe("sala de validación", () => {
  it("explica que VALIDAR está en preparación y que no tiene agentes asignados", async () => {
    nav.reset("/validar");
    mockApi({ "/agentes": agentList() });
    render(<ValidationView />);
    expect(screen.getByRole("heading", { level: 1, name: "Sala de validación" })).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("VALIDAR está en preparación");
    const panel = screen.getByRole("heading", { name: "Agentes asignados a VALIDAR" }).closest("section")!;
    expect(await within(panel).findByText(/no tiene ningún agente asignado a VALIDAR/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Validar|Ejecutar/ })).toBeNull();
  });
});
