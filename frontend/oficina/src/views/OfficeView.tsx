"use client";

import { ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AgentDrawer } from "@/components/agents/AgentPanels";
import { OfficeFloor } from "@/components/agents/OfficeFloor";
import { SchedulerSummary } from "@/components/scheduler/SchedulerSummary";
import { Badge, CalibrationBadge, ModeBadge, RunStatusBadge, StageBadge } from "@/components/ui/Badges";
import { InfoTip } from "@/components/ui/InfoTip";
import { EmptyState, QueryView, RefreshControl } from "@/components/ui/States";
import { Day, Time } from "@/components/ui/Time";
import {
  OPERATIONAL_POLL_MS,
  useAgents,
  useClassifications,
  useMetricDefinitions,
  useMetrics,
  useScheduler,
  useStageRules,
  useTopicNames,
  useTopics,
} from "@/hooks/queries";
import { useDataMode, useModeHref } from "@/hooks/useDataMode";
import { label, SOURCE } from "@/lib/labels";
import type { Agent } from "@/lib/schemas";

import styles from "./OfficeView.module.css";

function Kpi({ value, label: text, hint }: { value: number | string; label: string; hint: string }) {
  return (
    <div className={styles.kpi}>
      <span className={styles.kpiValue}>{value}</span>
      <span className={styles.kpiLabel}>
        {text} <InfoTip label={text}>{hint}</InfoTip>
      </span>
    </div>
  );
}

export function OfficeView() {
  const mode = useDataMode();
  const href = useModeHref();
  const agents = useAgents(mode, OPERATIONAL_POLL_MS);
  const scheduler = useScheduler(OPERATIONAL_POLL_MS);
  const classifications = useClassifications(mode, { limite: 5 });
  const topics = useTopics(mode, { limite: 5 });
  const metrics = useMetrics(mode, { limite: 1 });
  const definitions = useMetricDefinitions();
  const rules = useStageRules();
  const [selected, setSelected] = useState<Agent | null>(null);
  const names = useTopicNames(classifications.data?.items.map((c) => c.tema_id) ?? [], mode);

  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="page-title">Oficina de agentes</h1>
          <p className="page-lede">
            Cada agente tiene su puesto. Solo trabaja en pantalla cuando la API registra una ejecución pendiente o en
            curso; el resto del tiempo el puesto muestra su último resultado. Modo <ModeBadge mode={mode} />.
          </p>
        </div>
        <RefreshControl queries={[agents, scheduler, classifications, topics, metrics]} />
      </header>

      <section aria-labelledby="planta" className="stack" style={{ marginBottom: 24 }}>
        <h2 id="planta" className="visually-hidden">
          Planta de la oficina
        </h2>
        <QueryView query={agents} skeletonLines={6}>
          {(data) => {
            const list = data.agentes;
            const count = (fn: (a: Agent) => boolean) => list.filter(fn).length;
            return (
              <>
                <OfficeFloor agents={list} onSelect={setSelected} scheduler={scheduler.data} />
                <div className={styles.kpis} aria-label="Leyenda y conteo de la planta" role="group">
                  <Kpi value={count((a) => a.definido)} label="Definidos" hint="Agentes en el registro declarativo." />
                  <Kpi value={count((a) => a.implementado)} label="Con tarea" hint="implementado = true: su tarea está disponible." />
                  <Kpi
                    value={count((a) => a.ejecutado)}
                    label="Con ejecuciones"
                    hint="Agentes con al menos una ejecución registrada en este modo."
                  />
                  <Kpi
                    value={count((a) => a.actividad === "pendiente" || a.actividad === "en_curso")}
                    label="Activos ahora"
                    hint="Última ejecución registrada en estado pendiente o en curso."
                  />
                  <Kpi
                    value={count((a) => a.actividad === "fallida" || a.actividad === "bloqueada")}
                    label="Fallidas o bloqueadas"
                    hint="Agentes cuya última ejecución terminó fallida o bloqueada."
                  />
                  <Kpi
                    value={count((a) => a.actividad === "sin_ejecuciones")}
                    label="Sin actividad"
                    hint="Agentes sin ninguna ejecución registrada en este modo."
                  />
                </div>
              </>
            );
          }}
        </QueryView>
      </section>

      <div className={styles.columns}>
        <section className="panel" aria-labelledby="ultimas">
          <div className="panel__head">
            <div>
              <h2 id="ultimas" className="panel__title">
                Última ejecución de cada agente
              </h2>
              <p className="panel__sub">Tomada de /agentes; no es el historial completo.</p>
            </div>
            <Link className="btn" href={href("/ejecuciones")}>
              Historial
            </Link>
          </div>
          <QueryView query={agents}>
            {(data) => {
              const runs = data.agentes
                .flatMap((a) => (a.ultima_ejecucion ? [a.ultima_ejecucion] : []))
                .sort((a, b) => b.solicitado.localeCompare(a.solicitado));
              if (!runs.length) {
                return <EmptyState title="Ningún agente tiene ejecuciones registradas">En este modo de datos.</EmptyState>;
              }
              return (
                <ul className={styles.feed}>
                  {runs.map((run) => (
                    <li key={run.id}>
                      <span className="mono small">{run.agente}</span>
                      <RunStatusBadge status={run.estado} />
                      <span className="faint small">
                        <Time value={run.solicitado} />
                      </span>
                    </li>
                  ))}
                </ul>
              );
            }}
          </QueryView>
        </section>

        <section className="panel" aria-labelledby="prog">
          <div className="panel__head">
            <div>
              <h2 id="prog" className="panel__title">
                Programador
              </h2>
              <p className="panel__sub">Estado operativo del proceso, independiente de cada agente.</p>
            </div>
            <Link className="btn" href={href("/programador")}>
              Ver plan
            </Link>
          </div>
          <QueryView query={scheduler}>{(status) => <SchedulerSummary status={status} />}</QueryView>
        </section>

        <section className="panel" aria-labelledby="clasif">
          <div className="panel__head">
            <div>
              <h2 id="clasif" className="panel__title">
                Clasificaciones recientes
              </h2>
              <p className="panel__sub">Etapas asignadas por DETECTAR; el frontend no las calcula.</p>
            </div>
            <Link className="btn" href={href("/clasificaciones")}>
              Todas
            </Link>
          </div>
          <QueryView query={classifications}>
            {(page) =>
              page.items.length === 0 ? (
                <EmptyState title="Sin clasificaciones">No hay clasificaciones registradas en este modo.</EmptyState>
              ) : (
                <ul className={styles.feed}>
                  {page.items.map((c) => (
                    <li key={c.id}>
                      <span className={styles.feedMain}>{names[c.tema_id] ?? <span className="mono small">{c.tema_id}</span>}</span>
                      <StageBadge stage={c.etapa} />
                      <span className="faint small">
                        <Day value={c.fecha_referencia} />
                      </span>
                    </li>
                  ))}
                </ul>
              )
            }
          </QueryView>
        </section>

        <section className="panel" aria-labelledby="temas">
          <div className="panel__head">
            <div>
              <h2 id="temas" className="panel__title">
                Temas
              </h2>
              <p className="panel__sub">Primeros por clave normalizada (orden de la API).</p>
            </div>
            <Link className="btn" href={href("/temas")}>
              Explorar
            </Link>
          </div>
          <QueryView query={topics}>
            {(page) =>
              page.items.length === 0 ? (
                <EmptyState title="Sin temas">Todavía no hay temas normalizados en este modo.</EmptyState>
              ) : (
                <>
                  <p className="faint small" style={{ marginBottom: 8 }}>
                    {page.total} temas registrados
                  </p>
                  <ul className={styles.feed}>
                    {page.items.map((t) => (
                      <li key={t.id}>
                        <span className={styles.feedMain}>{t.nombre}</span>
                        {t.ambiguo ? <Badge tone="warn">Ambiguo</Badge> : null}
                        <span className="faint small">
                          {Object.values(t.vinculos_por_fuente).reduce((a, b) => a + b, 0)} vínculos
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )
            }
          </QueryView>
        </section>

        <section className="panel" aria-labelledby="metr">
          <div className="panel__head">
            <div>
              <h2 id="metr" className="panel__title">
                Métricas
              </h2>
              <p className="panel__sub">Definiciones disponibles y valores calculados.</p>
            </div>
            <Link className="btn" href={href("/metricas")}>
              Ver
            </Link>
          </div>
          <QueryView query={definitions}>
            {(defs) => {
              const bySource = new Map<string, number>();
              defs.metricas.forEach((m) => bySource.set(m.source, (bySource.get(m.source) ?? 0) + 1));
              return (
                <dl className="dl small">
                  {[...bySource.entries()].map(([source, n]) => (
                    <div key={source} style={{ display: "contents" }}>
                      <dt>{label(SOURCE, source)}</dt>
                      <dd>{n} definiciones</dd>
                    </div>
                  ))}
                  <dt>Valores calculados</dt>
                  <dd>{metrics.data ? metrics.data.total : metrics.error ? "no disponible" : "…"}</dd>
                  <dt>Versión</dt>
                  <dd className="mono">{defs.version}</dd>
                </dl>
              );
            }}
          </QueryView>
        </section>

        <section className={`panel ${styles.limits}`} aria-labelledby="limites">
          <div className="panel__head">
            <div>
              <h2 id="limites" className="panel__title">
                Limitaciones de los datos
              </h2>
              <p className="panel__sub">Lo que DETECTAR todavía no puede afirmar.</p>
            </div>
            <ShieldAlert size={20} aria-hidden="true" color="var(--warn)" />
          </div>
          <ul className={styles.limitList}>
            <li>
              <QueryView query={rules} skeletonLines={1}>
                {(r) => (
                  <span className="row">
                    Reglas <code>{r.version}</code>: <CalibrationBadge calibrated={r.calibrado} />
                    {r.provisional ? <span className="muted small">umbrales provisionales</span> : null}
                  </span>
                )}
              </QueryView>
            </li>
            <li>
              <strong>Saturación, oportunidad y confianza:</strong> la API no las calcula (no hay datos de oferta de
              contenido). Por eso no aparecen como valores en ninguna vista.
            </li>
            <li>
              <strong>Validación de fuentes:</strong> cada métrica y evidencia indica <code>fuente_validada</code>. Una
              fuente no validada (hoy GDELT) se marca y nunca determina una etapa.
            </li>
            <li>
              <strong>Etapa «saturada»:</strong> existe en el modelo, pero las reglas actuales no la asignan.
            </li>
          </ul>
        </section>
      </div>

      <AgentDrawer agent={selected} mode={mode} onClose={() => setSelected(null)} />
    </>
  );
}
