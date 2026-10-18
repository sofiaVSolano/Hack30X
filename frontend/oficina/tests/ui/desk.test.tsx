import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Desk } from "@/components/agents/Desk";
import { OfficeFloor } from "@/components/agents/OfficeFloor";
import { ACTIVITIES, type Activity } from "@/lib/schemas";

import { agent, agentList, run, scheduler } from "../support/fixtures";

function deskState(activity: Activity, implemented: boolean) {
  const { container } = render(<Desk activity={activity} implemented={implemented} />);
  const svg = container.querySelector("svg")!;
  return {
    state: svg.getAttribute("data-state"),
    typing: svg.querySelectorAll("rect[class*='line']").length,
    agentDrawn: svg.querySelector("[class*='person']") !== null,
    hidden: svg.getAttribute("aria-hidden"),
  };
}

describe("puesto de trabajo (Desk)", () => {
  it.each(["pendiente", "en_curso"] as const)("con %s el agente trabaja en pantalla", (activity) => {
    expect(deskState(activity, true)).toMatchObject({ state: "trabajando", typing: 3, agentDrawn: true });
  });

  it.each(["sin_ejecuciones", "completada", "fallida", "bloqueada"] as const)("con %s no hay trabajo en pantalla", (activity) => {
    expect(deskState(activity, true)).toMatchObject({ state: activity, typing: 0, agentDrawn: true });
  });

  it("un rol sin tarea es un puesto vacante: sin agente y sin trabajo, aunque la API dijera otra cosa", () => {
    for (const activity of ACTIVITIES) {
      expect(deskState(activity, false)).toMatchObject({ state: "vacante", typing: 0, agentDrawn: false });
    }
  });

  it("es decorativo para lectores de pantalla: el estado se anuncia con texto", () => {
    expect(deskState("completada", true).hidden).toBe("true");
  });
});

describe("planta de la oficina", () => {
  it("agrupa los puestos en salas según el alcance real de cada agente", () => {
    render(<OfficeFloor agents={agentList().agentes} onSelect={() => {}} />);
    const floor = screen.getByRole("group", { name: "Estaciones de agentes" });
    const detectar = within(floor).getByRole("region", { name: "Sala DETECTAR" });
    expect(within(detectar).getAllByRole("button")).toHaveLength(5); // fixtures: 5 en detectar
    expect(within(floor).getByRole("region", { name: "Coordinación" })).toBeInTheDocument();
  });

  it("solo hay pulso y trabajo en pantalla para el agente con ejecución en curso registrada", () => {
    const agents = [
      agent("trend_hunter", { ejecutado: true, actividad: "en_curso", ultima_ejecucion: run({ estado: "running", fin: null }) }),
      agent("supervisor", { ejecutado: true, actividad: "completada", ultima_ejecucion: run({ agente: "supervisor" }) }),
      agent("analyst"),
    ];
    const { container } = render(<OfficeFloor agents={agents} onSelect={() => {}} />);
    expect(container.querySelectorAll('[data-live="true"]')).toHaveLength(1);
    expect(container.querySelectorAll('svg[data-state="trabajando"]')).toHaveLength(1);
    expect(container.querySelectorAll('svg[data-state="vacante"]')).toHaveLength(1);
    expect(screen.getByRole("button", { name: /Agente trend_hunter: tarea implementada/ }).querySelector('[data-live="true"]')).not.toBeNull();
  });

  it("el reloj del pasillo muestra el estado real del programador", () => {
    const { rerender } = render(<OfficeFloor agents={agentList().agentes} onSelect={() => {}} scheduler={scheduler()} />);
    expect(screen.getByText("Programador apagado")).toBeInTheDocument();
    expect(screen.getByText("0 agentes con ejecución periódica")).toBeInTheDocument();
    rerender(
      <OfficeFloor
        agents={agentList().agentes}
        onSelect={() => {}}
        scheduler={scheduler({
          habilitado: true,
          en_ejecucion: true,
          agentes: [{ agente: "supervisor", programado: true, motivo_omision: null, frecuencia_minutos: 15, data_mode: "simulated" }],
        })}
      />,
    );
    expect(screen.getByText("Programador en marcha")).toBeInTheDocument();
    expect(screen.getByText("1 agente con ejecución periódica")).toBeInTheDocument();
  });

  it("sin datos del programador no inventa su estado", () => {
    render(<OfficeFloor agents={agentList().agentes} onSelect={() => {}} />);
    expect(screen.queryByText(/Programador/)).toBeNull();
  });
});
