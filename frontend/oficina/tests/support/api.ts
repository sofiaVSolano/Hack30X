import { vi } from "vitest";

type Handler = unknown | ((url: URL) => unknown);

export interface ApiMock {
  calls: URL[];
  set: (path: string, handler: Handler) => void;
}

/**
 * Sustituye `fetch` del navegador por respuestas del intermediario (`/api/oficina/...`).
 * Un handler puede devolver un objeto (200 JSON) o un `Response` (p. ej. un error).
 */
export function mockApi(routes: Record<string, Handler>): ApiMock {
  const table = new Map(Object.entries(routes));
  const calls: URL[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://127.0.0.1:3000");
      calls.push(url);
      const path = url.pathname.replace(/^\/api\/oficina/, "");
      const handler = table.get(path);
      if (handler === undefined) {
        return new Response(JSON.stringify({ code: "not_found", title: "No encontrado" }), { status: 404 });
      }
      const value = typeof handler === "function" ? (handler as (u: URL) => unknown)(url) : handler;
      if (value instanceof Response) return value;
      return new Response(JSON.stringify(value), { status: 200, headers: { "content-type": "application/json" } });
    }),
  );
  return { calls, set: (path, handler) => table.set(path, handler) };
}

export function problem(status: number, code: string, title: string) {
  return new Response(JSON.stringify({ code, title, detail: "Detalle seguro." }), {
    status,
    headers: { "content-type": "application/problem+json" },
  });
}
