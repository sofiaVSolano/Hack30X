/**
 * Acceso estrictamente local a la oficina (cierre de DETECTAR).
 *
 * - Host: solo `localhost`, `127.0.0.1` o `[::1]`, y con el puerto en el que escucha el servidor.
 *   Frena el DNS rebinding: tras el rebinding, el navegador envía `Host: dominio-atacante`.
 * - X-Forwarded-Host: si llega, debe ser igual de local (no hay proxies inversos previstos).
 * - Sec-Fetch-Site: las peticiones de otro sitio (`cross-site`) o de otro origen del mismo sitio
 *   (`same-site`, p. ej. otro puerto de localhost) se rechazan en la API; en las páginas, solo
 *   se permiten si son navegaciones de nivel superior. Sin la cabecera (curl, scripts locales)
 *   decide únicamente la validación de Host.
 *
 * No sustituye a la autenticación: cualquier proceso del propio equipo puede seguir leyendo la
 * oficina. Ver docs/e14-seguridad-acceso.md.
 */

export const LOCAL_HOSTNAMES = ["localhost", "127.0.0.1", "[::1]"] as const;

export interface LocalRequest {
  host: string | null;
  forwardedHost?: string | null;
  secFetchSite?: string | null;
  secFetchMode?: string | null;
  pathname: string;
  /** Puerto real del servidor (Next lo publica en la variable PORT). Sin él, se admite cualquier puerto válido. */
  expectedPort?: string | null;
}

export type Verdict = { ok: true } | { ok: false; status: 403 | 421; code: string; title: string };

const HOST_RE = /^(localhost|127\.0\.0\.1|\[::1\])(?::(\d{1,5}))?$/;

export function parseLocalHost(value: string | null | undefined): { hostname: string; port: number } | null {
  if (!value) return null;
  const match = HOST_RE.exec(value.trim().toLowerCase());
  if (!match) return null;
  const port = match[2] === undefined ? 80 : Number(match[2]);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return null;
  return { hostname: match[1]!, port };
}

function validPort(host: { port: number }, expectedPort: string | null | undefined): boolean {
  if (!expectedPort) return true;
  return String(host.port) === expectedPort.trim();
}

export function checkLocalRequest(req: LocalRequest): Verdict {
  const host = parseLocalHost(req.host);
  if (!host || !validPort(host, req.expectedPort)) {
    return { ok: false, status: 421, code: "host_no_permitido", title: "Host no permitido: la oficina solo atiende en el equipo local" };
  }
  if (req.forwardedHost) {
    const forwarded = parseLocalHost(req.forwardedHost);
    if (!forwarded || !validPort(forwarded, req.expectedPort)) {
      return { ok: false, status: 421, code: "host_reenviado_no_permitido", title: "Cabecera X-Forwarded-Host no permitida" };
    }
  }
  const site = req.secFetchSite?.toLowerCase();
  if (site === "cross-site" || site === "same-site") {
    const isApi = req.pathname === "/api" || req.pathname.startsWith("/api/");
    const isNavigation = req.secFetchMode?.toLowerCase() === "navigate";
    if (isApi || !isNavigation) {
      return { ok: false, status: 403, code: "origen_no_permitido", title: "Solicitud de otro origen rechazada" };
    }
  }
  return { ok: true };
}

export function rejection(verdict: Extract<Verdict, { ok: false }>): Response {
  return new Response(JSON.stringify({ code: verdict.code, title: verdict.title }), {
    status: verdict.status,
    headers: { "Content-Type": "application/problem+json; charset=utf-8", "Cache-Control": "no-store" },
  });
}
