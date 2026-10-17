import { NextResponse, type NextRequest } from "next/server";

import { checkLocalRequest, rejection } from "@/lib/local-access";

/**
 * Se ejecuta antes de TODAS las solicitudes (páginas, API y estáticos): la oficina solo atiende
 * a `localhost`/`127.0.0.1`/`[::1]` en su puerto y rechaza peticiones de otros orígenes.
 */
export function proxy(request: NextRequest): Response {
  const verdict = checkLocalRequest({
    host: request.headers.get("host"),
    forwardedHost: request.headers.get("x-forwarded-host"),
    secFetchSite: request.headers.get("sec-fetch-site"),
    secFetchMode: request.headers.get("sec-fetch-mode"),
    pathname: request.nextUrl.pathname,
    expectedPort: process.env.PORT,
  });
  if (verdict.ok) return NextResponse.next();
  // Sin valores de cabeceras: pueden venir de un atacante.
  console.warn(`[oficina] solicitud rechazada: ${verdict.code}`);
  return rejection(verdict);
}
