"use client";

import { SchedulerSummary } from "@/components/scheduler/SchedulerSummary";
import { Badge, ModeBadge } from "@/components/ui/Badges";
import { InfoTip } from "@/components/ui/InfoTip";
import { EmptyState, QueryView, RefreshControl } from "@/components/ui/States";
import { Structured } from "@/components/ui/Structured";
import { Time } from "@/components/ui/Time";
import { OPERATIONAL_POLL_MS, useScheduler } from "@/hooks/queries";
import { formatDuration, formatMinutes } from "@/lib/format";
import { label, SKIP_REASON } from "@/lib/labels";

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function SchedulerView() {
  const scheduler = useScheduler(OPERATIONAL_POLL_MS);
  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="page-title">Programador</h1>
          <p className="page-lede">
            Plan de ejecuciones periódicas del proceso del backend. Esta vista es de solo lectura: el programador se
            configura con variables de entorno en el servidor.
          </p>
        </div>
        <RefreshControl queries={[scheduler]} />
      </header>
      <QueryView query={scheduler} skeletonLines={6}>
        {(status) => {
          const tick = status.ultimo_tick;
          return (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
              <section className="panel" aria-labelledby="estado">
                <div className="panel__head">
                  <h2 id="estado" className="panel__title">
                    Estado operativo
                  </h2>
                </div>
                <SchedulerSummary status={status} />
                <dl className="dl small" style={{ marginTop: 12 }}>
                  <dt>
                    Umbral de abandono{" "}
                    <InfoTip label="Umbral de abandono">
                      Antigüedad mínima para cerrar como «abandonada» una ejecución sin proceso activo.
                    </InfoTip>
                  </dt>
                  <dd>{formatDuration(status.umbral_abandono_segundos * 1000)}</dd>
                </dl>
              </section>

              <section className="panel" aria-labelledby="plan" style={{ gridColumn: "1 / -1" }}>
                <div className="panel__head">
                  <div>
                    <h2 id="plan" className="panel__title">
                      Plan por agente
                    </h2>
                    <p className="panel__sub">Qué se programaría y por qué se omite cada agente.</p>
                  </div>
                </div>
                <div className="table-wrap" tabIndex={0}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th scope="col">Agente</th>
                        <th scope="col">Programado</th>
                        <th scope="col">Motivo de omisión</th>
                        <th scope="col">Frecuencia</th>
                        <th scope="col">Modo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {status.agentes.map((a) => (
                        <tr key={a.agente}>
                          <td className="mono">{a.agente}</td>
                          <td>{a.programado ? <Badge tone="ok">Sí</Badge> : <Badge tone="neutral">No</Badge>}</td>
                          <td>
                            {a.motivo_omision ? (
                              <>
                                {label(SKIP_REASON, a.motivo_omision)}
                                <div className="faint small mono">{a.motivo_omision}</div>
                              </>
                            ) : (
                              <span className="faint">—</span>
                            )}
                          </td>
                          <td>{formatMinutes(a.frecuencia_minutos)}</td>
                          <td>{a.data_mode ? <ModeBadge mode={a.data_mode} /> : <span className="faint">—</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="panel" aria-labelledby="tick" style={{ gridColumn: "1 / -1" }}>
                <div className="panel__head">
                  <div>
                    <h2 id="tick" className="panel__title">
                      Último tick
                    </h2>
                    <p className="panel__sub">En memoria del proceso actual; se pierde al reiniciar el backend.</p>
                  </div>
                </div>
                {!tick ? (
                  <EmptyState title="Sin ticks en este proceso">
                    {status.habilitado
                      ? "El programador está habilitado pero todavía no ha completado ninguna revisión."
                      : "El programador está deshabilitado, así que no revisa el plan."}
                  </EmptyState>
                ) : (
                  <div className="stack">
                    <dl className="dl">
                      <dt>Momento</dt>
                      <dd>{typeof tick.momento === "string" ? <Time value={tick.momento} /> : "—"}</dd>
                      <dt>Lanzadas</dt>
                      <dd>{list(tick.lanzadas).length ? list(tick.lanzadas).join(", ") : <span className="faint">Ninguna</span>}</dd>
                      <dt>No vencidas</dt>
                      <dd>{list(tick.no_vencidas).length ? list(tick.no_vencidas).join(", ") : <span className="faint">Ninguna</span>}</dd>
                      <dt>Ocupadas</dt>
                      <dd>{list(tick.ocupadas).length ? list(tick.ocupadas).join(", ") : <span className="faint">Ninguna</span>}</dd>
                    </dl>
                    {list(tick.errores).length ? (
                      <div className="notice notice--danger">
                        <div className="stack">
                          <p className="notice__title">Errores del tick</p>
                          <Structured value={tick.errores} />
                        </div>
                      </div>
                    ) : null}
                    <details>
                      <summary className="small muted">Recuperación de ejecuciones abandonadas</summary>
                      <div className="code-block" style={{ marginTop: 8 }}>
                        <Structured value={tick.recuperacion ?? null} />
                      </div>
                    </details>
                  </div>
                )}
              </section>
            </div>
          );
        }}
      </QueryView>
    </>
  );
}
