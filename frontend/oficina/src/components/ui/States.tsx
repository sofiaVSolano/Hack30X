"use client";

import { CircleDashed, RefreshCw, TriangleAlert, WifiOff } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import type { OficinaError } from "@/lib/api-client";
import { formatRelative } from "@/lib/format";
import type { QueryState } from "@/hooks/useOficinaQuery";

export function Skeleton({ lines = 3, height = 18 }: { lines?: number; height?: number }) {
  return (
    <div className="stack" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton" style={{ height, width: `${92 - i * 14}%` }} />
      ))}
    </div>
  );
}

export function ErrorNotice({ error, onRetry }: { error: OficinaError; onRetry?: () => void }) {
  const Icon = error.kind === "network" ? WifiOff : TriangleAlert;
  return (
    <div className="notice notice--danger" role="alert">
      <Icon size={18} aria-hidden="true" color="var(--danger)" />
      <div className="stack" style={{ gap: 6 }}>
        <p className="notice__title">{error.title}</p>
        {error.detail ? <p className="muted">{error.detail}</p> : null}
        {error.code ? <p className="faint small mono">código: {error.code}</p> : null}
        {onRetry ? (
          <div>
            <button type="button" className="btn" onClick={onRetry}>
              <RefreshCw size={15} aria-hidden="true" /> Reintentar
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="notice" role="status">
      <CircleDashed size={18} aria-hidden="true" color="var(--text-faint)" />
      <div className="stack" style={{ gap: 4 }}>
        <p className="notice__title">{title}</p>
        {children ? <div className="muted small">{children}</div> : null}
      </div>
    </div>
  );
}

/**
 * Representa una consulta: carga inicial, error sin datos, o los datos (con un aviso si la
 * última recarga falló y lo mostrado puede estar desactualizado).
 */
export function QueryView<T>({
  query,
  children,
  skeletonLines = 3,
}: {
  query: QueryState<T>;
  children: (data: T) => ReactNode;
  skeletonLines?: number;
}) {
  if (query.data === undefined) {
    if (query.error) return <ErrorNotice error={query.error} onRetry={query.refetch} />;
    return (
      <div aria-busy="true">
        <span className="visually-hidden">Cargando…</span>
        <Skeleton lines={skeletonLines} />
      </div>
    );
  }
  return (
    <>
      {query.error ? (
        <div className="notice notice--warn" role="status">
          <TriangleAlert size={18} aria-hidden="true" color="var(--warn)" />
          <p>
            <strong>No se pudo actualizar:</strong> {query.error.title}. Se muestran los últimos datos recibidos
            {query.updatedAt ? ` (${formatRelative(query.updatedAt)})` : ""}.
          </p>
        </div>
      ) : null}
      {children(query.data)}
    </>
  );
}

/** Botón de actualización manual con la hora de la última respuesta válida. */
export function RefreshControl({ queries, label = "Actualizar" }: { queries: QueryState<unknown>[]; label?: string }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setTick((t) => t + 1), 15_000);
    return () => window.clearInterval(timer);
  }, []);
  const busy = queries.some((q) => q.loading || q.refreshing);
  const times = queries.map((q) => q.updatedAt?.getTime()).filter((t): t is number => t !== undefined);
  const oldest = times.length === queries.length && times.length ? new Date(Math.min(...times)) : undefined;
  return (
    <div className="row" style={{ gap: 10 }}>
      <span className="faint small" aria-live="polite">
        {busy ? "Actualizando…" : oldest ? `Actualizado ${formatRelative(oldest)}` : "Sin datos todavía"}
      </span>
      <button type="button" className="btn" onClick={() => queries.forEach((q) => q.refetch())} disabled={busy}>
        <RefreshCw size={15} aria-hidden="true" className={busy ? "spin" : undefined} />
        {label}
      </button>
    </div>
  );
}
