// @vitest-environment node
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

import { checkLocalRequest } from "@/lib/local-access";
import { CREAR_ENDPOINTS } from "@/server/crear/endpoints";
import { GENERATION_TIMEOUT_MS, handleCrear, MAX_BODY_BYTES } from "@/server/crear/handler";

import { batch, gapPage, options, proposal, TOPIC } from "./datos";

const TOKEN = "tok_PRUEBA_crear_no_real_1a2b";
const BASE = "http://127.0.0.1:8000";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function get(path: string) {
  return new Request(`http://127.0.0.1:3000/api/oficina/crear${path}`);
}

function post(path: string, body: unknown, headers: Record<string, string> = { "content-type": "application/json" }) {
  return new Request(`http://127.0.0.1:3000/api/oficina/crear${path}`, {
    method: "POST",
    headers,
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

const VALID_BATCH = { data_mode: "real", origen: "brecha", tema_id: TOPIC, plataforma: "tiktok", audiencia: "general_latam", pais: "MX" };

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubEnv("OFICINA_DETECTAR_URL", BASE);
  vi.stubEnv("DETECTAR_ADMIN_TOKEN", TOKEN);
  vi.stubEnv("OFICINA_DETECTAR_TIMEOUT_MS", "2000");
  fetchMock = vi.fn(async () => json(options()));
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

function lastCall() {
  return fetchMock.mock.calls.at(-1) as [URL, RequestInit];
}

describe("lecturas", () => {
  it("van a /api/crear con el token del servidor y solo Accept y Authorization", async () => {
    fetchMock.mockResolvedValueOnce(json(gapPage()));
    const response = await handleCrear("brechas", get("/brechas?data_mode=simulated&veredicto=brecha_confirmada"));

    expect(response.status).toBe(200);
    const [url, init] = lastCall();
    expect(String(url)).toBe(`${BASE}/api/crear/brechas?data_mode=simulated&veredicto=brecha_confirmada`);
    expect(init.method).toBe("GET");
    expect(init.headers).toEqual({ Accept: "application/json", Authorization: `Bearer ${TOKEN}` });
    expect(await response.text()).not.toContain(TOKEN);
  });

  it("rechaza parámetros y segmentos no declarados", async () => {
    expect((await handleCrear("brechas", get("/brechas?veredicto=oportunidad"))).status).toBe(400);
    expect((await handleCrear("brechas", get("/brechas?orden=x"))).status).toBe(400);
    expect((await handleCrear("propuesta", get("/propuestas/../../detectar"), { propuesta: "../../detectar" })).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("no muestra respuestas que no cumplen el contrato", async () => {
    fetchMock.mockResolvedValueOnce(json({ ...gapPage(), items: [{ tema_id: TOPIC }] }));
    const response = await handleCrear("brechas", get("/brechas"));

    expect(response.status).toBe(502);
    expect((await response.json()).code).toBe("respuesta_inesperada");
  });

  it("traduce los errores del backend sin filtrar credenciales", async () => {
    fetchMock.mockResolvedValueOnce(json({ code: "not_found", title: "No encontrado", detail: "La propuesta no existe." }, 404));
    const missing = await handleCrear("propuesta", get("/propuestas/prp_0000000000000000"), { propuesta: "prp_0000000000000000" });
    fetchMock.mockResolvedValueOnce(json({ code: "unauthorized", title: "No autorizado" }, 401));
    const unauthorized = await handleCrear("opciones", get("/opciones"));

    expect(missing.status).toBe(404);
    expect((await missing.json()).detail).toBe("La propuesta no existe.");
    expect(unauthorized.status).toBe(502);
    expect((await unauthorized.json()).code).toBe("intermediario_no_autorizado");
  });
});

describe("escrituras (generar y regenerar)", () => {
  it("reenvía el cuerpo ya validado y espera más que una lectura", async () => {
    fetchMock.mockResolvedValueOnce(json(batch(), 201));
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const response = await handleCrear("generar", post("/propuestas", { ...VALID_BATCH }));

    expect(response.status).toBe(201);
    const [url, init] = lastCall();
    expect(String(url)).toBe(`${BASE}/api/crear/propuestas`);
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ Accept: "application/json", Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" });
    expect(JSON.parse(String(init.body))).toEqual(VALID_BATCH);
    expect(timeout).toHaveBeenCalledWith(GENERATION_TIMEOUT_MS);
  });

  it("exige JSON, un tamaño máximo y un esquema estricto", async () => {
    const notJson = await handleCrear("generar", post("/propuestas", VALID_BATCH, { "content-type": "text/plain" }));
    const huge = await handleCrear("generar", post("/propuestas", { ...VALID_BATCH, tema_texto: "x".repeat(MAX_BODY_BYTES) }));
    const extra = await handleCrear("generar", post("/propuestas", { ...VALID_BATCH, admin: "SECRETO_DEL_NAVEGADOR" }));
    const broken = await handleCrear("generar", post("/propuestas", "{no es json"));

    expect([notJson.status, huge.status, extra.status, broken.status]).toEqual([415, 413, 400, 400]);
    expect(await extra.text()).not.toContain("SECRETO_DEL_NAVEGADOR");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("regenera solo con los campos permitidos", async () => {
    fetchMock.mockResolvedValueOnce(json(proposal("narrativo", { version: 2 }), 201));
    const ok = await handleCrear(
      "regenerar",
      post("/propuestas/prp_000000000000000a/regeneraciones", { data_mode: "real", enfoque: "narrativo", pais: null }),
      { propuesta: "prp_000000000000000a" },
    );
    const wrongApproach = await handleCrear(
      "regenerar",
      post("/propuestas/prp_000000000000000a/regeneraciones", { data_mode: "real", enfoque: "agresivo" }),
      { propuesta: "prp_000000000000000a" },
    );

    expect(ok.status).toBe(201);
    expect(String(lastCall()[0])).toBe(`${BASE}/api/crear/propuestas/prp_000000000000000a/regeneraciones`);
    expect(wrongApproach.status).toBe(400);
  });

  it("cada operación solo admite su método", async () => {
    const getOnWrite = await handleCrear("regenerar", get("/propuestas/prp_000000000000000a/regeneraciones"), {
      propuesta: "prp_000000000000000a",
    });
    const postOnRead = await handleCrear("opciones", post("/opciones", {}));

    expect([getOnWrite.status, postOnRead.status]).toEqual([405, 405]);
  });

  it("una escritura desde otro sitio se rechaza antes de llegar al intermediario", () => {
    const verdict = checkLocalRequest({
      host: "127.0.0.1:3000",
      secFetchSite: "cross-site",
      secFetchMode: "cors",
      pathname: "/api/oficina/crear/propuestas",
    });

    expect(verdict.ok).toBe(false);
  });
});

describe("documento PDF", () => {
  const pdf = (headers: Record<string, string>, body = "%PDF-1.4 contenido") =>
    new Response(body, { status: 200, headers: { "content-type": "application/pdf", ...headers } });
  const request = () => handleCrear("pdf", get("/lotes/lot_0000000000000001/pdf?data_mode=simulated"), { lote: "lot_0000000000000001" });

  it("reenvía un PDF real con un nombre de archivo seguro", async () => {
    fetchMock.mockResolvedValueOnce(pdf({ "content-disposition": 'attachment; filename="propuestas-tema-eta-00000001.pdf"', "x-interna": "1" }));
    const response = await request();

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("application/pdf");
    expect(response.headers.get("content-disposition")).toBe('attachment; filename="propuestas-tema-eta-00000001.pdf"');
    expect(response.headers.get("x-interna")).toBeNull();
    expect(String(lastCall()[0])).toBe(`${BASE}/api/crear/lotes/lot_0000000000000001/pdf?data_mode=simulated`);
    expect(new TextDecoder().decode(await response.arrayBuffer())).toBe("%PDF-1.4 contenido");
  });

  it("no reenvía algo que no es un PDF ni un nombre de archivo inesperado", async () => {
    fetchMock.mockResolvedValueOnce(pdf({ "content-disposition": 'attachment; filename="../../x.exe"' }));
    const renamed = await request();
    fetchMock.mockResolvedValueOnce(pdf({}, "<html>no es un pdf</html>"));
    const fake = await request();
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 200, headers: { "content-type": "text/html" } }));
    const html = await request();

    expect(renamed.headers.get("content-disposition")).toBe('attachment; filename="propuestas-crear.pdf"');
    expect([fake.status, html.status]).toEqual([502, 502]);
  });

  it("traduce los errores del backend como en el resto de operaciones", async () => {
    fetchMock.mockResolvedValueOnce(json({ code: "not_found", title: "No encontrado", detail: "El lote de propuestas no existe." }, 404));
    const response = await request();

    expect(response.status).toBe(404);
    expect((await response.json()).detail).toBe("El lote de propuestas no existe.");
  });
});

describe("rutas de CREAR", () => {
  const root = join(__dirname, "..", "..", "src", "app", "api", "oficina", "crear");
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) walk(full);
      else if (name === "route.ts") files.push(full);
    }
  };
  walk(root);
  const handlers = files.flatMap((f) => [...readFileSync(f, "utf8").matchAll(/export async function (\w+)[\s\S]*?handleCrear\("(\w+)"/g)].map((m) => [m[1], m[2]]));

  it("cada operación declarada tiene exactamente una ruta y viceversa", () => {
    const used = handlers.map(([, endpoint]) => endpoint);
    expect(new Set(used)).toEqual(new Set(Object.keys(CREAR_ENDPOINTS)));
    expect(used).toHaveLength(Object.keys(CREAR_ENDPOINTS).length);
  });

  it("solo generar y regenerar escriben, y con el método declarado", () => {
    for (const [method, endpoint] of handlers) {
      expect(method, endpoint).toBe(CREAR_ENDPOINTS[endpoint as keyof typeof CREAR_ENDPOINTS].method);
    }
    const writes = Object.entries(CREAR_ENDPOINTS).filter(([, spec]) => spec.method === "POST").map(([id]) => id);
    expect(writes.sort()).toEqual(["generar", "regenerar"]);
    for (const file of files) {
      expect(readFileSync(file, "utf8"), relative(root, file)).not.toMatch(/function\s+(PUT|PATCH|DELETE)/);
    }
  });

  it("ninguna operación apunta a DETECTAR", () => {
    for (const spec of Object.values(CREAR_ENDPOINTS)) {
      expect(spec.path).not.toMatch(/detectar|recolecciones|agentes|normalizaciones|calculos/);
    }
  });
});
