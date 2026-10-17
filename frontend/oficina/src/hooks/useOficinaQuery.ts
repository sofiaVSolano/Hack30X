"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ZodType } from "zod";

import { buildUrl, getJson, OficinaError, type QueryParams } from "@/lib/api-client";

export interface QueryState<T> {
  data: T | undefined;
  error: OficinaError | undefined;
  /** Primera carga sin datos todavía. */
  loading: boolean;
  /** Recarga con datos previos visibles. */
  refreshing: boolean;
  updatedAt: Date | undefined;
  refetch: () => void;
}

export interface QueryOptions<T> {
  path: string;
  params?: QueryParams;
  schema: ZodType<T>;
  /** Sondeo periódico en ms; se pausa con la pestaña oculta. */
  pollMs?: number;
  enabled?: boolean;
}

/**
 * Consulta al intermediario con:
 * - cancelación de la solicitud anterior al cambiar la clave (vista o filtros);
 * - sin solicitudes duplicadas mientras una sigue en curso;
 * - sondeo opcional pausado cuando la página no es visible;
 * - si una recarga falla, se conservan los últimos datos válidos junto al error.
 */
export function useOficinaQuery<T>({ path, params, schema, pollMs, enabled = true }: QueryOptions<T>): QueryState<T> {
  const url = buildUrl(path, params);
  const [state, setState] = useState<{ key: string; data?: T; error?: OficinaError; updatedAt?: Date; inFlight: boolean }>({
    key: url,
    inFlight: enabled,
  });
  const controller = useRef<AbortController | null>(null);
  const lastStarted = useRef(0);
  const schemaRef = useRef(schema);
  schemaRef.current = schema;

  const run = useCallback(
    (force: boolean) => {
      if (!enabled) return;
      if (controller.current && !force) return; // ya hay una en curso para esta clave
      controller.current?.abort();
      const current = new AbortController();
      controller.current = current;
      lastStarted.current = Date.now();
      setState((prev) => (prev.key === url ? { ...prev, inFlight: true } : { key: url, inFlight: true }));
      getJson(url, schemaRef.current, current.signal)
        .then((data) => {
          if (current.signal.aborted) return;
          setState({ key: url, data, error: undefined, updatedAt: new Date(), inFlight: false });
        })
        .catch((error: unknown) => {
          if (current.signal.aborted) return;
          const failure =
            error instanceof OficinaError ? error : new OficinaError("invalid", "Error inesperado en la oficina");
          setState((prev) => ({ ...(prev.key === url ? prev : { key: url }), error: failure, inFlight: false }));
        })
        .finally(() => {
          if (controller.current === current) controller.current = null;
        });
    },
    [url, enabled],
  );

  useEffect(() => {
    run(true);
    return () => {
      controller.current?.abort();
      controller.current = null;
    };
  }, [run]);

  useEffect(() => {
    if (!pollMs || !enabled) return;
    const tick = () => {
      if (document.visibilityState === "visible") run(false);
    };
    const onVisible = () => {
      if (document.visibilityState === "visible" && Date.now() - lastStarted.current >= pollMs) run(false);
    };
    const timer = window.setInterval(tick, pollMs);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [pollMs, enabled, run]);

  const refetch = useCallback(() => run(true), [run]);
  const sameKey = state.key === url;
  const data = sameKey ? state.data : undefined;
  return {
    data,
    error: sameKey ? state.error : undefined,
    loading: enabled && data === undefined && (!sameKey || state.inFlight),
    refreshing: sameKey && state.inFlight && data !== undefined,
    updatedAt: sameKey ? state.updatedAt : undefined,
    refetch,
  };
}
