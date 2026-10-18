import "../support/navigation";

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ENTRY_MS, MORPH_MS, OfficeWorld, SHOT } from "@/components/office/OfficeWorld";
import { clearTopicNameCache } from "@/hooks/queries";
import { TrendsView } from "@/views/TrendsView";

import { mockApi, problem } from "../support/api";
import { agentList, page, run, scheduler } from "../support/fixtures";
import { nav } from "../support/navigation";

function routes(overrides: Record<string, unknown> = {}) {
  return {
    "/agentes": agentList({
      trend_hunter: { nombre: "Cazador de tendencias", ejecutado: true, actividad: "completada", ultima_ejecucion: run() },
      supervisor: { nombre: "Supervisor" },
    }),
    "/programador": scheduler(),
    "/clasificaciones": page([]),
    "/temas": page([]),
    "/metricas": page([]),
    ...overrides,
  };
}

/** Simula el cambio de ruta que hace el router de Next tras `router.push`. */
function World({ children }: { children?: ReactNode }) {
  return <OfficeWorld>{children ?? <p>contenido del computador</p>}</OfficeWorld>;
}

function setMedia(matches: Record<string, boolean>) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: matches[query] ?? false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

const station = (name: RegExp) => within(screen.getByRole("group", { name: "Puestos de la oficina" })).getByRole("button", { name });
const pushed = () => nav.replace.mock.calls.map((c) => [c[0], (c as unknown[])[1]]);
/** Salta la secuencia de cámara (clic en el escenario) para no esperarla entera en cada prueba. */
const skipEntry = () => fireEvent.pointerDown(document.body);
const SKIP_WAIT = SHOT.skip + 1000;

beforeEach(() => {
  nav.reset("/oficina");
  clearTopicNameCache();
  window.localStorage.clear();
  delete document.documentElement.dataset.motion;
});
afterEach(() => {
  // @ts-expect-error: se elimina el mock para la siguiente prueba
  delete window.matchMedia;
});

describe("la oficina", () => {
  it("muestra las cinco salas con su estado real de implementación", async () => {
    mockApi(routes());
    render(<World />);
    expect(screen.getByRole("button", { name: /Sala de tendencias, DETECTAR: funcional/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Centro de agentes, Coordinación: funcional/ })).toBeInTheDocument();
    for (const room of [/Sala de análisis, ENTENDER: en preparación/, /Estudio creativo, CREAR: en preparación/, /Sala de validación, VALIDAR: en preparación/]) {
      expect(screen.getByRole("button", { name: room })).toBeInTheDocument();
    }
    expect(screen.getByRole("heading", { level: 1, name: "Oficina de HACK 30X" })).toBeInTheDocument();
  });

  it("cada puesto es un botón con el estado que devuelve la API", async () => {
    mockApi(routes());
    render(<World />);
    const group = screen.getByRole("group", { name: "Puestos de la oficina" });
    await within(group).findByRole("button", { name: /Cazador de tendencias \(Sala de tendencias\): Completada\. Entrar al computador/ });
    expect(within(group).getByRole("button", { name: /Agente analyst \(Sala de análisis\): Sin tarea implementada/ })).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: /Puesto de validación \(Sala de validación\): VALIDAR en preparación/ })).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: /Pantalla del programador \(Centro de agentes\): Programador apagado/ })).toBeInTheDocument();
    expect(within(group).getAllByRole("button", { name: /Entrar al computador/ })).toHaveLength(12);
  });

  it("si la API no responde lo dice, permite reintentar y no dibuja a nadie trabajando", async () => {
    const api = mockApi(routes({ "/agentes": problem(502, "detectar_no_disponible", "No se pudo conectar con DETECTAR") }));
    const { container } = render(<World />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No se pudo leer el estado de los agentes");
    expect(station(/Puesto del Cazador de tendencias \(Sala de tendencias\): Estado no disponible/)).toBeInTheDocument();
    expect(container.querySelectorAll("g[class*='person']")).toHaveLength(0);
    api.set("/agentes", agentList());
    await userEvent.click(within(alert).getByRole("button", { name: /Reintentar/ }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(container.querySelectorAll("g[class*='person']")).toHaveLength(2);
  });

  it("al elegir una sala la cámara la encuadra y explica qué hará el módulo pendiente", async () => {
    mockApi(routes());
    const { container } = render(<World />);
    const world = container.querySelector("[data-instant]") as HTMLElement;
    const before = world.style.transform;
    await userEvent.click(screen.getByRole("button", { name: /Sala de análisis, ENTENDER/ }));
    const panel = screen.getByRole("complementary", { name: "Sala de análisis" });
    expect(within(panel).getByText("ENTENDER · en preparación")).toBeInTheDocument();
    expect(within(panel).getByText(/Todavía no está implementado/)).toBeInTheDocument();
    expect(world.style.transform).not.toBe(before);
    expect(screen.getByRole("navigation", { name: "Ubicación" })).toHaveTextContent("Sala de análisis");
    await userEvent.click(within(panel).getByRole("button", { name: "Ver toda la oficina" }));
    expect(screen.queryByRole("complementary", { name: "Sala de análisis" })).toBeNull();
  });

  it("Escape vuelve a la vista general desde una sala", async () => {
    mockApi(routes());
    render(<World />);
    await userEvent.click(screen.getByRole("button", { name: /Centro de agentes, Coordinación/ }));
    expect(screen.getByRole("complementary", { name: "Centro de agentes" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("complementary", { name: "Centro de agentes" })).toBeNull();
  });

  it("la ficha de un agente se consulta sin entrar al computador", async () => {
    mockApi(routes({ "/agentes/trend_hunter/ejecuciones": { agente: "trend_hunter", data_mode: "real", limite: 20, ejecuciones: [run()] } }));
    render(<World />);
    const button = await within(screen.getByRole("group", { name: "Puestos de la oficina" })).findByRole("button", { name: /Cazador de tendencias \(Sala de tendencias\)/ });
    button.focus();
    await userEvent.click(screen.getAllByRole("button", { name: "Ficha del agente" })[0]!);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Cazador de tendencias" })).toBeInTheDocument();
    expect(await within(dialog).findByText("run_0001")).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
  });
});

describe("entrar al computador y volver", () => {
  it(
    "la cámara se acerca despacio en planos (acercamiento, pausa, empuje) y después abre el computador",
    async () => {
      mockApi(routes());
      const { container } = render(<World />);
      const root = container.firstChild as HTMLElement;
      const world = container.querySelector("[data-instant]") as HTMLElement;
      const before = world.style.transform;
      await userEvent.click(
        await within(screen.getByRole("group", { name: "Puestos de la oficina" })).findByRole("button", { name: /Cazador de tendencias \(Sala de tendencias\)/ }),
      );
      // 1. acercamiento lento a un plano medio
      expect(root).toHaveAttribute("data-phase", "acercando");
      expect(world.style.transition).toBe(`transform ${SHOT.approach}ms cubic-bezier(0.45, 0, 0.2, 1)`);
      const medium = world.style.transform;
      expect(medium).not.toBe(before);
      expect(container.querySelector('[data-station="trend_hunter"]')).toHaveAttribute("data-selected", "true");
      expect(screen.getByRole("status")).toHaveTextContent("Entrando al computador");
      expect(nav.replace).not.toHaveBeenCalled();
      // 2. pausa: el monitor se enciende
      await waitFor(() => expect(root).toHaveAttribute("data-phase", "pausa"), { timeout: SHOT.approach + 500 });
      expect(container.querySelector('[data-station="trend_hunter"]')).toHaveAttribute("data-lit", "true");
      // 3. empuje hacia la pantalla (más cerca que el plano medio)
      await waitFor(() => expect(root).toHaveAttribute("data-phase", "empujando"), { timeout: SHOT.hold + 500 });
      expect(world.style.transform).not.toBe(medium);
      expect(world.style.transition).toBe(`transform ${SHOT.push}ms cubic-bezier(0.55, 0, 0.25, 1)`);
      expect(nav.replace).not.toHaveBeenCalled();
      // 4. entra con su tipo de transición
      await waitFor(() => expect(pushed()).toEqual([["/tendencias", { transitionTypes: ["entrar-computador"] }]]), { timeout: SHOT.push + 800 });
      expect(ENTRY_MS).toBeGreaterThanOrEqual(4000);
    },
    ENTRY_MS + 4000,
  );

  it("un clic o Enter durante la secuencia la saltan; Escape la cancela", async () => {
    mockApi(routes());
    const { container } = render(<World />);
    const group = screen.getByRole("group", { name: "Puestos de la oficina" });
    await userEvent.click(await within(group).findByRole("button", { name: /Cazador de tendencias \(Sala de tendencias\)/ }));
    skipEntry();
    expect(container.firstChild).toHaveAttribute("data-phase", "saltando");
    await waitFor(() => expect(pushed()[0]?.[0]).toBe("/tendencias"), { timeout: SKIP_WAIT });

    nav.replace.mockClear();
    await userEvent.click(within(group).getByRole("button", { name: /Pantalla de métricas/ }));
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(pushed()[0]?.[0]).toBe("/metricas"), { timeout: SKIP_WAIT });
  });

  it("Escape durante la entrada la cancela y vuelve a la vista general", async () => {
    mockApi(routes());
    const { container } = render(<World />);
    await userEvent.click(await within(screen.getByRole("group", { name: "Puestos de la oficina" })).findByRole("button", { name: /Pantalla de temas/ }));
    expect(container.firstChild).toHaveAttribute("data-phase", "acercando");
    await userEvent.keyboard("{Escape}");
    expect(container.firstChild).not.toHaveAttribute("data-phase");
    expect(screen.queryByRole("status")).toBeNull();
    await new Promise((r) => setTimeout(r, 300));
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("con movimiento reducido entra sin esperar a la cámara", async () => {
    setMedia({ "(prefers-reduced-motion: reduce)": true });
    mockApi(routes());
    render(<World />);
    await userEvent.click(station(/Pantalla de métricas/));
    await waitFor(() => expect(pushed()[0]?.[0]).toBe("/metricas"), { timeout: 200 });
  });

  it("con el sistema en movimiento reducido, «Animaciones» permite ver el acercamiento completo", async () => {
    setMedia({ "(prefers-reduced-motion: reduce)": true });
    mockApi(routes());
    const { container } = render(<World />);
    const toggle = screen.getByRole("button", { name: /Animaciones: reducidas/ });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: /Animaciones: completas/ })).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement.dataset.motion).toBe("completo");
    expect(window.localStorage.getItem("hack30x:movimiento")).toBe("completo");
    await userEvent.click(station(/Pantalla de métricas/));
    expect(container.firstChild).toHaveAttribute("data-phase", "acercando");
    expect(nav.replace).not.toHaveBeenCalled();
    // y se puede volver a seguir al sistema
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: /Animaciones: completas/ }));
    expect(document.documentElement.dataset.motion).toBeUndefined();
  });

  it("conserva el modo simulado al entrar", async () => {
    nav.reset("/oficina", "modo=simulated");
    const api = mockApi(routes({ "/agentes": agentList({}, "simulated") }));
    render(<World />);
    await userEvent.click(station(/Pantalla de temas/));
    skipEntry();
    await waitFor(() => expect(pushed()[0]?.[0]).toBe("/temas?modo=simulated"), { timeout: SKIP_WAIT });
    expect(api.calls.find((u) => u.pathname === "/api/oficina/agentes")!.searchParams.get("data_mode")).toBe("simulated");
    expect(screen.getAllByRole("note")[0]).toHaveTextContent("Modo simulado");
  });

  it("dentro del computador funciona la interfaz real de DETECTAR", async () => {
    nav.reset("/tendencias");
    mockApi(routes({ "/clasificaciones": page([]), "/temas": page([]) }));
    render(
      <World>
        <TrendsView />
      </World>,
    );
    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("id", "contenido");
    expect(await within(main).findByText("Todavía no hay tendencias calculadas")).toBeInTheDocument();
    const location = screen.getByRole("navigation", { name: "Ubicación" });
    expect(location).toHaveTextContent("HACK 30X");
    expect(location).toHaveTextContent("Sala de tendencias");
    expect(location).toHaveTextContent("Computador");
    expect(within(location).getByText("DETECTAR")).toHaveAttribute("aria-current", "page");
    const sections = screen.getByRole("navigation", { name: "Secciones de DETECTAR" });
    expect(within(sections).getByRole("link", { name: "Tendencias" })).toHaveAttribute("aria-current", "page");
    expect(within(sections).getByRole("link", { name: "Temas" })).toHaveAttribute("href", "/temas");
    expect(within(sections).getByRole("link", { name: "Temas" })).toHaveAttribute("data-transition-types", "pestana");
  });

  it("el ambiente y el cursor cambian al entrar y se restauran al volver", async () => {
    setMedia({ "(hover: hover) and (pointer: fine)": true });
    mockApi(routes());
    const { container, rerender } = render(<World />);
    expect(container.firstChild).toHaveAttribute("data-cursor", "oficina");
    expect(screen.queryByTestId("cursor-halo")).toBeNull();

    await userEvent.click(await within(screen.getByRole("group", { name: "Puestos de la oficina" })).findByRole("button", { name: /Cazador de tendencias \(Sala de tendencias\)/ }));
    skipEntry();
    await waitFor(() => expect(nav.replace).toHaveBeenCalled(), { timeout: SKIP_WAIT });
    nav.path = "/tendencias";
    rerender(<World />);

    expect(container.firstChild).toHaveAttribute("data-cursor", "computador");
    expect(container.querySelector('[data-cursor="computador"][data-module="detectar"]')).not.toBeNull();
    const halo = screen.getByTestId("cursor-halo");
    expect(halo.parentElement).toHaveAttribute("aria-hidden", "true");
    // la oficina queda detrás, inerte
    expect(screen.queryByRole("group", { name: "Puestos de la oficina" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /Volver a la oficina/ }));
    expect(pushed().at(-1)).toEqual(["/oficina", { transitionTypes: ["salir-computador"] }]);
    nav.path = "/oficina";
    rerender(<World />);
    expect(container.firstChild).toHaveAttribute("data-cursor", "oficina");
    expect(screen.queryByTestId("cursor-halo")).toBeNull();
    expect(screen.queryByRole("button", { name: /Volver a la oficina/ })).toBeNull();
    // el puesto de origen queda marcado y recupera el foco cuando la cámara se aleja
    expect(container.querySelector('[data-station="trend_hunter"]')).toHaveAttribute("data-selected", "true");
    await waitFor(
      () => expect(document.activeElement).toHaveAccessibleName(/Cazador de tendencias \(Sala de tendencias\)/),
      { timeout: MORPH_MS + 1000 },
    );
    expect(container.querySelector('[data-station="trend_hunter"]')).toHaveAttribute("data-last", "true");
  });

  it("el halo del cursor se oculta en los campos de texto y no existe en pantallas táctiles", async () => {
    setMedia({ "(hover: hover) and (pointer: fine)": true });
    nav.reset("/temas");
    mockApi(routes());
    const { unmount } = render(
      <World>
        <input aria-label="Buscar" />
        <button type="button">Acción</button>
      </World>,
    );
    const halo = screen.getByTestId("cursor-halo");
    const computer = document.querySelector('[data-cursor="computador"][data-module]')!;
    fireEvent.pointerMove(screen.getByRole("button", { name: "Acción" }), { pointerType: "mouse", clientX: 40, clientY: 40, bubbles: true });
    expect(halo).toHaveAttribute("data-mode", "hover");
    fireEvent.pointerMove(screen.getByRole("textbox", { name: "Buscar" }), { pointerType: "mouse", clientX: 60, clientY: 40, bubbles: true });
    expect(halo).toHaveAttribute("data-mode", "hidden");
    fireEvent.pointerLeave(computer);
    expect(halo).toHaveAttribute("data-mode", "hidden");
    unmount();

    setMedia({ "(hover: hover) and (pointer: fine)": false });
    render(<World />);
    expect(screen.queryByTestId("cursor-halo")).toBeNull();
  });

  it("con movimiento reducido no hay halo animado", () => {
    setMedia({ "(hover: hover) and (pointer: fine)": true, "(prefers-reduced-motion: reduce)": true });
    nav.reset("/temas");
    mockApi(routes());
    render(<World />);
    expect(screen.queryByTestId("cursor-halo")).toBeNull();
  });

  it("Escape sale del computador, salvo mientras se escribe o con un diálogo abierto", async () => {
    nav.reset("/temas");
    mockApi(routes());
    const { rerender } = render(
      <World>
        <input aria-label="Buscar tema" />
      </World>,
    );
    screen.getByRole("textbox", { name: "Buscar tema" }).focus();
    await userEvent.keyboard("{Escape}");
    expect(nav.replace).not.toHaveBeenCalled();

    rerender(
      <World>
        <dialog open aria-label="Detalle">
          <p>detalle</p>
        </dialog>
      </World>,
    );
    act(() => (document.activeElement as HTMLElement | null)?.blur());
    await userEvent.keyboard("{Escape}");
    expect(nav.replace).not.toHaveBeenCalled();

    rerender(
      <World>
        <p>sin diálogo</p>
      </World>,
    );
    await userEvent.keyboard("{Escape}");
    expect(pushed()).toEqual([["/oficina", { transitionTypes: ["salir-computador"] }]]);
  });

  it("al volver se puede entrar a otro puesto", async () => {
    nav.reset("/coordinacion");
    mockApi(routes());
    const { rerender } = render(<World />);
    expect(screen.getByRole("navigation", { name: "Secciones de Coordinación" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Volver a la oficina/ }));
    nav.path = "/oficina";
    rerender(<World />);
    nav.replace.mockClear();
    await userEvent.click(await within(screen.getByRole("group", { name: "Puestos de la oficina" })).findByRole("button", { name: /Agente strategist \(Estudio creativo\)/ }));
    skipEntry();
    await waitFor(() => expect(pushed()).toEqual([["/puesto/strategist", { transitionTypes: ["entrar-computador"] }]]), {
      timeout: SKIP_WAIT,
    });
  });

  it("el sonido está apagado por defecto y se puede activar", async () => {
    mockApi(routes());
    render(<World />);
    const toggle = screen.getByRole("button", { name: "Sonido al entrar y salir del computador" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(window.localStorage.getItem("hack30x:sonido")).toBe("on");
  });

  it("el directorio de puestos permite entrar desde el móvil sin hacer zoom", async () => {
    mockApi(routes());
    render(<World />);
    const directory = screen.getByRole("region", { name: "Puestos de la oficina" });
    expect(within(directory).getAllByRole("heading", { level: 3 })).toHaveLength(5);
    await userEvent.click(within(directory).getByRole("button", { name: /Pantalla de clasificaciones y evidencias/ }));
    skipEntry();
    await waitFor(() => expect(pushed()[0]?.[0]).toBe("/clasificaciones"), { timeout: SKIP_WAIT });
  });
});
