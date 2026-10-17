// @vitest-environment node
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { checkLocalRequest, parseLocalHost } from "@/lib/local-access";
import { loopbackProblem } from "@/lib/loopback";
import { proxy } from "@/proxy";
import { handleRead } from "@/server/handler";

const base = { pathname: "/api/oficina/agentes", expectedPort: "3000" };

describe("validación de Host", () => {
  it.each(["127.0.0.1:3000", "localhost:3000", "[::1]:3000", "LOCALHOST:3000"])("admite %s", (host) => {
    expect(checkLocalRequest({ ...base, host })).toEqual({ ok: true });
  });

  it.each([
    "evil.example",
    "evil.example:3000",
    "127.0.0.1.evil.example:3000",
    "localhost.evil.example:3000",
    "user@127.0.0.1:3000",
    "127.0.0.1:3000, evil.example",
    "127.0.0.1 :3000",
    "0.0.0.0:3000",
    "192.168.1.20:3000",
    "[::ffff:127.0.0.1]:3000",
    "127.0.0.2:3000",
    "127.0.0.1:99999",
    "",
  ])("rechaza Host %j con 421", (host) => {
    const verdict = checkLocalRequest({ ...base, host });
    expect(verdict).toMatchObject({ ok: false, status: 421, code: "host_no_permitido" });
  });

  it("rechaza la ausencia de Host", () => {
    expect(checkLocalRequest({ ...base, host: null }).ok).toBe(false);
  });

  it("exige el puerto real del servidor", () => {
    expect(checkLocalRequest({ ...base, host: "127.0.0.1:3001" }).ok).toBe(false);
    expect(checkLocalRequest({ ...base, host: "127.0.0.1" }).ok).toBe(false); // puerto 80 implícito
    expect(checkLocalRequest({ ...base, host: "127.0.0.1:4000", expectedPort: "4000" }).ok).toBe(true);
  });

  it("valida también X-Forwarded-Host", () => {
    expect(checkLocalRequest({ ...base, host: "127.0.0.1:3000", forwardedHost: "evil.example" })).toMatchObject({
      ok: false,
      code: "host_reenviado_no_permitido",
    });
    expect(checkLocalRequest({ ...base, host: "127.0.0.1:3000", forwardedHost: "localhost:3000" }).ok).toBe(true);
  });

  it("parseLocalHost normaliza y rechaza formatos ambiguos", () => {
    expect(parseLocalHost("Localhost:3000")).toEqual({ hostname: "localhost", port: 3000 });
    expect(parseLocalHost("127.0.0.1")).toEqual({ hostname: "127.0.0.1", port: 80 });
    expect(parseLocalHost("::1:3000")).toBeNull();
    expect(parseLocalHost("127.0.0.1:0")).toBeNull();
  });
});

describe("solicitudes de otro origen (Sec-Fetch-Site)", () => {
  const host = "127.0.0.1:3000";

  it.each(["same-origin", "none", null])("admite %s en la API", (site) => {
    expect(checkLocalRequest({ ...base, host, secFetchSite: site, secFetchMode: "cors" }).ok).toBe(true);
  });

  it.each(["cross-site", "same-site"])("rechaza %s en la API, incluso como navegación", (site) => {
    for (const mode of ["cors", "no-cors", "navigate"]) {
      expect(checkLocalRequest({ ...base, host, secFetchSite: site, secFetchMode: mode })).toMatchObject({
        ok: false,
        status: 403,
        code: "origen_no_permitido",
      });
    }
  });

  it("en las páginas permite abrir la oficina desde un enlace, pero no incrustarla ni leerla", () => {
    const page = { host, pathname: "/agentes", expectedPort: "3000" };
    expect(checkLocalRequest({ ...page, secFetchSite: "cross-site", secFetchMode: "navigate" }).ok).toBe(true);
    expect(checkLocalRequest({ ...page, secFetchSite: "cross-site", secFetchMode: "no-cors" }).ok).toBe(false);
    expect(checkLocalRequest({ ...page, secFetchSite: "same-site", secFetchMode: "cors" }).ok).toBe(false);
  });
});

describe("proxy.ts (se ejecuta antes de cada solicitud)", () => {
  beforeEach(() => {
    vi.stubEnv("PORT", "3000");
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  it("rechaza Host: evil.example (el caso detectado en E14) sin registrar el valor", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const response = proxy(new NextRequest("http://127.0.0.1:3000/agentes", { headers: { host: "evil.example" } }));
    expect(response.status).toBe(421);
    expect(response.headers.get("content-type")).toContain("application/problem+json");
    expect((await response.json()).code).toBe("host_no_permitido");
    expect(warn.mock.calls.flat().join(" ")).not.toContain("evil.example");
  });

  it("rechaza peticiones de otro sitio a la API", () => {
    const response = proxy(
      new NextRequest("http://127.0.0.1:3000/api/oficina/agentes", {
        headers: { host: "127.0.0.1:3000", "sec-fetch-site": "cross-site", "sec-fetch-mode": "cors" },
      }),
    );
    expect(response.status).toBe(403);
  });

  it("deja pasar una solicitud local normal", () => {
    const response = proxy(
      new NextRequest("http://127.0.0.1:3000/api/oficina/agentes", {
        headers: { host: "127.0.0.1:3000", "sec-fetch-site": "same-origin", "sec-fetch-mode": "cors" },
      }),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});

describe("el intermediario repite la comprobación (defensa en profundidad)", () => {
  it("rechaza Host ajeno sin llamar al backend", async () => {
    vi.stubEnv("OFICINA_DETECTAR_URL", "http://127.0.0.1:8000");
    vi.stubEnv("DETECTAR_ADMIN_TOKEN", "tok_PRUEBA_no_real_0123456789abcdef");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const response = await handleRead("agentes", new Request("http://127.0.0.1:3000/api/oficina/agentes", { headers: { host: "evil.example" } }));
    expect(response.status).toBe(421);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await response.text()).not.toContain("tok_PRUEBA");
  });
});

describe("arranque solo en loopback", () => {
  const next = "node_modules/next/dist/bin/next";

  it.each([
    [["node", next, "start", "--hostname", "127.0.0.1", "--port", "3000"], {}],
    [["node", next, "start", "-H", "localhost"], {}],
    [["node", next, "start", "--hostname=::1"], {}],
    [["node", next, "build"], {}],
    [["node", "start-server.js"], { OFICINA_HOSTNAME: "127.0.0.1" }],
  ])("permite %j", (argv, env) => {
    expect(loopbackProblem(argv, env)).toBeNull();
  });

  it.each([
    [["node", next, "start"], {}, /Falta --hostname/],
    [["node", next, "start", "--hostname", "0.0.0.0"], {}, /no es de loopback/],
    [["node", next, "start", "-H", "192.168.1.20"], {}, /no es de loopback/],
    [["node", next, "start", "--hostname=::"], {}, /no es de loopback/],
    [["node", "start-server.js"], {}, /npm run dev/],
    [["node", "start-server.js"], { OFICINA_HOSTNAME: "0.0.0.0" }, /no es de loopback/],
  ])("impide %j", (argv, env, message) => {
    expect(loopbackProblem(argv, env)).toMatch(message);
  });
});
