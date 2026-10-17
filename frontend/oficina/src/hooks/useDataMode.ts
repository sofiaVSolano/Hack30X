"use client";

import { usePathname, useSearchParams } from "next/navigation";

import type { DataMode } from "@/lib/schemas";

/** Modo de datos de la vista, tomado de `?modo=`. Cualquier otro valor equivale a `real`. */
export function useDataMode(): DataMode {
  const params = useSearchParams();
  return params.get("modo") === "simulated" ? "simulated" : "real";
}

/** Construye un enlace interno que conserva el modo de datos actual. */
export function useModeHref() {
  const mode = useDataMode();
  return (path: string, extra: Record<string, string> = {}) => {
    const search = new URLSearchParams(extra);
    if (mode === "simulated") search.set("modo", "simulated");
    const query = search.toString();
    return query ? `${path}?${query}` : path;
  };
}

export function useCurrentPath(): string {
  return usePathname() ?? "/";
}
