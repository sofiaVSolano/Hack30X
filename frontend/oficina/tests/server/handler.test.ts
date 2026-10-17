// @vitest-environment node
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

import { readConfig } from "@/server/config";
import { ENDPOINTS } from "@/server/endpoints";
import { handleRead } from "@/server/handler";

import { agentList, scheduler } from "../support/fixtures";

const TOKEN = "tok_PRUEBA_no_real_9f8e7d";
const BASE = "http://127.0.0.1:8000";

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

function req(path: string) {
  return new Request(`http://127.0.0.1:3000/api/oficina${path}`);
}

let fetchMock: ReturnType<typeof vi.fn>;
let warnings: string[];

beforeEach(() => {
  vi.stubEnv("OFICINA_DETECTAR_URL", BASE);
  vi.stubEnv("DETECTAR_ADMIN_TOKEN", TOKEN);
  vi.stubEnv("OFICINA_DETECTAR_TIMEOUT_MS", "2000");
  fetchMock = vi.fn(async () => json(agentList()));
  vi.stubGlobal("fetch", fetchMock);
  warnings = [];
  vi.spyOn(console, "warn").mockImplementation((...args: unknown[]) => {
    warnings.push(args.join(" "));
  });
});

async function bodyText(response: Response) {
  return response.clone().text();
}

function expectNoSecret(text: string) {
  expect(text).not.toContain(TOKEN);
  expect(text).not.toMatch(/Bearer/i);
}

describe("autenticación del lado del servidor", () => {
  it("añade el token solo en la solicitud al backend y envía únicamente Accept y Authorization", async () => {
    const response = await handleRead("agentes", req("/agentes?data_mode=real"));
    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(String(url)).toBe(`${BASE}/api/detectar/agentes?data_mode=real`);
    expect(init.method).toBe("GET");
    expect(init.redirect).toBe("error");
    expect(init.headers).toEqual({ Accept: "application/json", Authorization: `Bearer ${TOKEN}` });
    expectNoSecret(await bodyText(response));
  });

  it("no reenvía cabeceras del navegador (ni un token que el navegador intente enviar)", async () => {
    const request = new Request(`http://127.0.0.1:3000/api/oficina/agentes`, {
      headers: { Authorization: "Bearer token-del-navegador", Cookie: "x=1", "X-Forwarded-Host": "evil.example" },
    });
    await handleRead("agentes", request);
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(init.headers).toEqual({ Accept: "application/json", Authorization: `Bearer ${TOKEN}` });
  });

  it("no devuelve cabeceras internas del backend y revalida el cuerpo", async () => {
    fetchMock.mockResolvedValueOnce(
      json({ ...agentList(), interno: "x" }, 200, { "x-internal-trace": "abc", server: "uvicorn", "set-cookie": "s=1" }),
    );
    const response = await handleRead("agentes", req("/agentes"));
    expect(response.headers.get("x-internal-trace")).toBeNull();
    expect(response.headers.get("server")).toBeNull();
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(response.headers.get("cache-control")).toBe("no-store");
    const body = await response.json();
    expect(body).not.toHaveProperty("interno");
    expect(body.agentes).toHaveLength(6);
  });

  it("sin token configurado responde 503 sin llamar al backend", async () => {
    vi.stubEnv("DETECTAR_ADMIN_TOKEN", "");
    const response = await handleRead("agentes", req("/agentes"));
    expect(response.status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
    expect((await response.json()).code).toBe("intermediario_sin_configurar");
  });

  it.each([
    ["http://user:pass@127.0.0.1:8000", "invalid_url"],
    ["ftp://127.0.0.1", "invalid_url"],
    ["http://127.0.0.1:8000/?x=1", "invalid_url"],
    ["no es una url", "invalid_url"],
  ])("rechaza la URL de backend %s", (url, reason) => {
    expect(readConfig({ OFICINA_DETECTAR_URL: url, DETECTAR_ADMIN_TOKEN: TOKEN } as unknown as NodeJS.ProcessEnv)).toEqual({ ok: false, reason });
  });

  it("rechaza tokens con espacios o saltos de línea (inyección de cabeceras)", () => {
    const result = readConfig({ OFICINA_DETECTAR_URL: BASE, DETECTAR_ADMIN_TOKEN: "abc\r\nX-Evil: 1" } as unknown as NodeJS.ProcessEnv);
    expect(result).toEqual({ ok: false, reason: "invalid_token" });
  });
});

describe("lista cerrada de rutas y parámetros", () => {
  it.each([
    ["/agentes?url=http://evil.example", "agentes"],
    ["/agentes?data_mode=real&data_mode=simulated", "agentes"],
    ["/agentes?data_mode=todo", "agentes"],
    ["/temas?limite=1000", "temas"],
    ["/temas?q=a", "temas"],
    ["/metricas?fecha_referencia=2026-02-30", "metricas"],
    ["/clasificaciones?etapa=inventada", "clasificaciones"],
    ["/programador?data_mode=real", "programador"],
  ] as const)("rechaza %s sin llamar al backend", async (path, endpoint) => {
    const response = await handleRead(endpoint, req(path));
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(response.headers.get("content-type")).toContain("application/problem+json");
  });

  it.each(["../../health", "trend_hunter/../../x", "http:%2F%2Fevil", "A"])("rechaza el segmento de agente %s", async (agente) => {
    const response = await handleRead("agenteEjecuciones", req(`/agentes/x/ejecuciones`), { agente });
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rechaza identificadores de tema que no cumplen el patrón", async () => {
    const response = await handleRead("tema", req("/temas/x"), { tema: "tpc_zz" });
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("el destino siempre queda en el backend configurado, aunque el texto de búsqueda parezca una URL", async () => {
    fetchMock.mockResolvedValueOnce(json({ data_mode: "real", total: 0, limite: 20, desplazamiento: 0, items: [] }));
    await handleRead("temas", req("/temas?q=" + encodeURIComponent("//evil.example/@x")));
    const [url] = fetchMock.mock.calls[0] as [URL];
    expect(url.origin).toBe(BASE);
    expect(url.pathname).toBe("/api/detectar/temas");
    expect(url.searchParams.get("q")).toBe("//evil.example/@x");
  });

  it("construye la ruta con segmentos válidos", async () => {
    fetchMock.mockResolvedValueOnce(json({ agente: "supervisor", data_mode: "real", limite: 5, ejecuciones: [] }));
    const response = await handleRead("agenteEjecuciones", req("/agentes/supervisor/ejecuciones?limite=5"), { agente: "supervisor" });
    expect(response.status).toBe(200);
    const [url] = fetchMock.mock.calls[0] as [URL];
    expect(url.pathname).toBe("/api/detectar/agentes/supervisor/ejecuciones");
  });

  it("rechaza métodos distintos de GET", async () => {
    const response = await handleRead("agentes", new Request("http://127.0.0.1:3000/api/oficina/agentes", { method: "POST" }));
    expect(response.status).toBe(405);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("errores del backend", () => {
  it("401/403 del backend se convierten en 502 sin detalles ni token", async () => {
    fetchMock.mockResolvedValueOnce(json({ type: "x", title: "No autorizado", status: 401, code: "unauthorized" }, 401));
    const response = await handleRead("agentes", req("/agentes"));
    expect(response.status).toBe(502);
    const text = await bodyText(response);
    expect(JSON.parse(text).code).toBe("intermediario_no_autorizado");
    expectNoSecret(text);
  });

  it("un 500 con detalles internos no los muestra", async () => {
    fetchMock.mockResolvedValueOnce(
      json({ detail: 'Traceback (most recent call last): File "/srv/app.py" sqlalchemy.exc.OperationalError' }, 500),
    );
    const response = await handleRead("agentes", req("/agentes"));
    expect(response.status).toBe(502);
    const text = await bodyText(response);
    expect(text).not.toMatch(/Traceback|sqlalchemy|app\.py/);
  });

  it("los 404 de dominio conservan el mensaje de DETECTAR", async () => {
    fetchMock.mockResolvedValueOnce(
      json({ type: "urn:x", title: "Agente no encontrado", status: 404, code: "not_found", detail: "No existe un agente con ese identificador." }, 404),
    );
    const response = await handleRead("agenteEjecuciones", req("/agentes/nadie_x/ejecuciones"), { agente: "nadie_x" });
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({
      code: "not_found",
      title: "Agente no encontrado",
      detail: "No existe un agente con ese identificador.",
    });
  });

  it("tiempo agotado -> 504", async () => {
    fetchMock.mockRejectedValueOnce(new DOMException("timeout", "TimeoutError"));
    const response = await handleRead("agentes", req("/agentes"));
    expect(response.status).toBe(504);
  });

  it("sin conexión -> 502", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    const response = await handleRead("agentes", req("/agentes"));
    expect(response.status).toBe(502);
    expect((await response.json()).code).toBe("detectar_no_disponible");
  });

  it("respuesta con estructura inesperada -> 502 (no se muestran datos incompletos)", async () => {
    fetchMock.mockResolvedValueOnce(json({ data_mode: "real", agentes: [{ id: "trend_hunter" }] }));
    const response = await handleRead("agentes", req("/agentes"));
    expect(response.status).toBe(502);
    expect((await response.json()).code).toBe("respuesta_inesperada");
  });

  it("respuesta no JSON o demasiado grande -> 502", async () => {
    fetchMock.mockResolvedValueOnce(new Response("<html>proxy error</html>", { status: 200 }));
    expect((await handleRead("programador", req("/programador"))).status).toBe(502);
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 200, headers: { "content-length": "99999999" } }));
    expect((await handleRead("programador", req("/programador"))).status).toBe(502);
  });

  it("los registros del servidor nunca incluyen el token ni la URL", async () => {
    fetchMock.mockResolvedValueOnce(json({}, 401));
    await handleRead("agentes", req("/agentes"));
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    await handleRead("programador", req("/programador"));
    expect(warnings.length).toBeGreaterThan(0);
    for (const line of warnings) {
      expect(line).not.toContain(TOKEN);
      expect(line).not.toContain(BASE);
    }
  });

  it("el programador valida su contrato real", async () => {
    fetchMock.mockResolvedValueOnce(json(scheduler()));
    expect((await handleRead("programador", req("/programador"))).status).toBe(200);
  });
});

describe("rutas del intermediario", () => {
  const root = join(__dirname, "..", "..", "src", "app", "api", "oficina");
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) walk(full);
      else if (name === "route.ts") files.push(full);
    }
  };
  walk(root);

  it("cada endpoint permitido tiene exactamente una ruta y viceversa", () => {
    const used = files.map((f) => readFileSync(f, "utf8").match(/handleRead\("([a-zA-Z]+)"/)?.[1]);
    expect(used.every(Boolean)).toBe(true);
    expect(new Set(used)).toEqual(new Set(Object.keys(ENDPOINTS)));
    expect(used).toHaveLength(Object.keys(ENDPOINTS).length);
  });

  it("solo exportan GET: ninguna ruta puede escribir ni ejecutar agentes", () => {
    for (const file of files) {
      const source = readFileSync(file, "utf8");
      expect(source, relative(root, file)).not.toMatch(/export\s+(async\s+)?function\s+(POST|PUT|PATCH|DELETE)/);
      expect(source).toMatch(/export async function GET/);
    }
  });

  it("ningún endpoint apunta a rutas de escritura de DETECTAR", () => {
    for (const spec of Object.values(ENDPOINTS)) {
      expect(spec.path).not.toMatch(/normalizaciones|calculos|correccion|alias|ambiguedad/);
    }
  });
});

describe("ruta base del backend", () => {
  it("respeta una ruta base sin duplicar barras", async () => {
    vi.stubEnv("OFICINA_DETECTAR_URL", "http://127.0.0.1:8000/hack30x/");
    await handleRead("agentes", req("/agentes"));
    const [url] = fetchMock.mock.calls[0] as [URL];
    expect(url.href).toBe("http://127.0.0.1:8000/hack30x/api/detectar/agentes");
  });
});
