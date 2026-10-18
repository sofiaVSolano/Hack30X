import "../support/navigation";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LabView } from "@/views/crear/LabView";

import { nav } from "../support/navigation";
import { batch, context, gap, gapPage, options, proposal, proposalPage, TOPIC } from "./datos";

type Handler = (body: unknown, url: URL) => unknown;

/** Sustituye fetch por respuestas del intermediario, por «MÉTODO ruta»; guarda los cuerpos enviados. */
function mockLab(routes: Record<string, Handler | unknown>) {
  const sent: { method: string; path: string; body: unknown; url: URL }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://127.0.0.1:3000");
      const method = init?.method ?? "GET";
      const path = url.pathname.replace(/^\/api\/oficina/, "");
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      sent.push({ method, path, body, url });
      const handler = routes[`${method} ${path}`];
      if (handler === undefined) return new Response(JSON.stringify({ code: "not_found", title: "No encontrado" }), { status: 404 });
      const value = typeof handler === "function" ? (handler as Handler)(body, url) : handler;
      if (value instanceof Response) return value;
      return new Response(JSON.stringify(value), { status: method === "POST" ? 201 : 200, headers: { "content-type": "application/json" } });
    }),
  );
  return sent;
}

const BASE = {
  "GET /crear/opciones": options(),
  "GET /crear/brechas": gapPage([gap(), gap({ tema_id: "tpc_00000000000000f2", tema_nombre: "Tema Theta", veredicto: "senales_mixtas" })]),
  "GET /crear/propuestas": proposalPage(),
};

beforeEach(() => nav.reset("/crear"));

async function chooseFirstGap() {
  const user = userEvent.setup();
  render(<LabView />);
  const list = await screen.findByRole("list", { name: "Temas con su comparación inglés–español" });
  const first = within(list).getAllByRole("listitem")[0]!;
  await user.click(within(first).getByRole("button", { name: "Crear a partir de esta brecha" }));
  return { user, first };
}

describe("Laboratorio creativo", () => {
  it("lista las brechas con su veredicto y filtra por veredicto", async () => {
    mockLab(BASE);
    const user = userEvent.setup();
    render(<LabView />);

    const list = await screen.findByRole("list", { name: "Temas con su comparación inglés–español" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).getByText("Brecha confirmada")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Señales mixtas (1)" }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(within(list).getByText("Tema Theta")).toBeInTheDocument();
  });

  it("muestra la evidencia por fuente sin convertir un idioma sin medir en cero", async () => {
    mockLab(BASE);
    const { user, first } = await chooseFirstGap();

    await user.click(within(first).getByRole("button", { name: "Ver la evidencia" }));
    const table = within(first).getByRole("table");
    expect(within(table).getByText("9800 visitas")).toBeInTheDocument();
    const trends = within(table).getByText("Google Trends (RSS)").closest("tr")!;
    expect(trends).toHaveTextContent("7 de 7 capturas US");
    expect(within(trends).getByText("sin medición")).toBeInTheDocument();
  });

  it("genera tres propuestas a partir de una brecha con la audiencia y la plataforma elegidas", async () => {
    const sent = mockLab({ ...BASE, "POST /crear/propuestas": batch() });
    const { user } = await chooseFirstGap();

    expect(await screen.findByText("Tema Eta", { selector: "strong" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /Carrusel de Instagram/ }));
    await user.selectOptions(screen.getByLabelText("Audiencia"), "jovenes_genz");
    await user.selectOptions(screen.getByLabelText("País"), "CO");
    await user.type(screen.getByLabelText("Detalle de la audiencia (opcional)"), "  estudiantes  ");
    await user.click(screen.getByRole("button", { name: "Generar 3 propuestas" }));

    const board = await screen.findByRole("region", { name: "Propuestas para «Tema Eta»" });
    expect(within(board).getAllByRole("article")).toHaveLength(3);
    expect(within(board).getByRole("heading", { name: "Título controversial" })).toBeInTheDocument();
    const request = sent.find((r) => r.method === "POST")!;
    expect(request.body).toEqual({
      data_mode: "real",
      origen: "brecha",
      tema_id: TOPIC,
      audiencia: "jovenes_genz",
      audiencia_detalle: "estudiantes",
      plataforma: "instagram_carrusel",
      pais: "CO",
    });
    expect(within(board).getByText(/Datos de DETECTAR que usaron las propuestas \(1\)/)).toBeInTheDocument();
    const download = within(board).getByRole("link", { name: "Descargar PDF" });
    expect(download).toHaveAttribute("href", "/api/oficina/crear/lotes/lot_0000000000000001/pdf?data_mode=real");
    expect(download).toHaveAttribute("download");
  });

  it("regenera una propuesta enviando solo lo que cambió y conserva la versión anterior", async () => {
    const sent = mockLab({
      ...BASE,
      "POST /crear/propuestas": batch(),
      [`POST /crear/propuestas/prp_000000000000000a/regeneraciones`]: proposal("narrativo", {
        id: "prp_00000000000000a2",
        raiz_id: "prp_000000000000000a",
        padre_id: "prp_000000000000000a",
        version: 2,
        cambios: ["enfoque", "indicacion"],
        contenido: { ...proposal("narrativo").contenido, titulo: "Título nuevo" },
        aviso_motor: "Las plantillas no interpretan indicaciones libres.",
      }),
    });
    const { user } = await chooseFirstGap();
    await user.click(await screen.findByRole("button", { name: "Generar 3 propuestas" }));
    const card = (await screen.findByRole("heading", { name: "Título educativo" })).closest("article")!;

    await user.click(within(card).getByRole("button", { name: /Regenerar con otro enfoque/ }));
    await user.selectOptions(within(card).getByLabelText("Enfoque"), "narrativo");
    await user.type(within(card).getByLabelText("Indicación libre (opcional)"), "más humor");
    await user.click(within(card).getByRole("button", { name: "Crear versión nueva" }));

    expect(await within(card).findByRole("heading", { name: "Título nuevo" })).toBeInTheDocument();
    const request = sent.find((r) => r.path.endsWith("/regeneraciones"))!;
    expect(request.body).toEqual({ data_mode: "real", enfoque: "narrativo", indicacion: "más humor" });
    expect(within(card).getByText(/Cambios frente a la versión anterior: enfoque, indicación/)).toBeInTheDocument();
    expect(within(card).getByText("Las plantillas no interpretan indicaciones libres.")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Versión 1" }));
    expect(within(card).getByRole("heading", { name: "Título educativo" })).toBeInTheDocument();
  });

  it("copia la propuesta como texto y avisa de cifras sin respaldo", async () => {
    const withFigures = proposal("educativo", { cifras_sin_respaldo: ["45 %"] });
    mockLab({ ...BASE, "POST /crear/propuestas": batch({ propuestas: [withFigures, proposal("controversial"), proposal("narrativo")] }) });
    const { user } = await chooseFirstGap(); // user-event instala su propio portapapeles
    await user.click(await screen.findByRole("button", { name: "Generar 3 propuestas" }));
    const card = (await screen.findByRole("heading", { name: "Título educativo" })).closest("article")!;

    expect(within(card).getByText(/Cifras sin respaldo en DETECTAR:/).closest("p")).toHaveTextContent("45 %");
    await user.click(within(card).getByRole("button", { name: "Copiar texto" }));
    await waitFor(() => expect(within(card).getByRole("button", { name: "Copiada" })).toBeInTheDocument());
    expect(await navigator.clipboard.readText()).toMatch(/^Título educativo\nEnfoque: Educativo\. Plataforma: TikTok\./);
  });

  it("acepta un tema escrito a mano, sin datos de DETECTAR", async () => {
    const sent = mockLab({
      ...BASE,
      "POST /crear/propuestas": batch({ contexto: context({ origen: "manual", tema_id: null, tema_nombre: "Ahorro joven", hechos: [] }) }),
    });
    const user = userEvent.setup();
    render(<LabView />);
    await user.click(await screen.findByRole("tab", { name: /Escribir un tema/ }));
    await user.type(screen.getByLabelText("Tema o tendencia"), "Ahorro   joven");
    await user.click(screen.getByRole("button", { name: "Usar este tema" }));
    await user.click(screen.getByRole("button", { name: "Generar 3 propuestas" }));

    await screen.findAllByRole("article");
    expect(sent.find((r) => r.method === "POST")!.body).toMatchObject({ origen: "manual", tema_texto: "Ahorro joven" });
  });

  it("explica qué hacer cuando DETECTAR todavía no tiene métricas", async () => {
    mockLab({ ...BASE, "GET /crear/brechas": gapPage([], { fecha_referencia: null }) });
    render(<LabView />);

    expect(await screen.findByText("DETECTAR todavía no tiene métricas en este modo")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generar 3 propuestas" })).toBeDisabled();
  });

  it("en modo simulado consulta y genera solo con datos simulados", async () => {
    nav.reset("/crear", "modo=simulated");
    const sent = mockLab({ ...BASE, "POST /crear/propuestas": batch({ data_mode: "simulated" }) });
    const { user } = await chooseFirstGap();
    await user.click(screen.getByRole("button", { name: "Generar 3 propuestas" }));
    await screen.findAllByRole("article");

    const reads = sent.filter((r) => r.method === "GET" && r.path !== "/crear/opciones");
    expect(reads.every((r) => r.url.searchParams.get("data_mode") === "simulated")).toBe(true);
    expect(sent.find((r) => r.method === "POST")!.body).toMatchObject({ data_mode: "simulated" });
  });

  it("muestra el error del intermediario y permite reintentar", async () => {
    mockLab({
      ...BASE,
      "POST /crear/propuestas": new Response(JSON.stringify({ code: "tiempo_agotado", title: "CREAR no respondió a tiempo" }), { status: 504 }),
    });
    const { user } = await chooseFirstGap();
    await user.click(screen.getByRole("button", { name: "Generar 3 propuestas" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("CREAR no respondió a tiempo");
    expect(screen.getByRole("button", { name: "Generar 3 propuestas" })).toBeEnabled();
  });
});
