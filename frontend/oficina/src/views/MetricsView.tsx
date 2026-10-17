"use client";

import { useRouter, useSearchParams } from "next/navigation";

import { MetricChart } from "@/components/metrics/MetricChart";
import { Badge, ModeBadge, ValidationBadge } from "@/components/ui/Badges";
import { InfoTip } from "@/components/ui/InfoTip";
import { EmptyState, QueryView, RefreshControl } from "@/components/ui/States";
import { Day } from "@/components/ui/Time";
import { useMetricDefinitions, useMetrics, useTopicNames } from "@/hooks/queries";
import { useDataMode, useModeHref } from "@/hooks/useDataMode";
import { formatMetricValue, unitLabel } from "@/lib/format";
import { label, METRIC_STATUS, SOURCE } from "@/lib/labels";
import type { MetricDefinition } from "@/lib/schemas";
import { buildSeries } from "@/lib/series";

const TOPIC_RE = /^tpc_[0-9a-f]{16}$/;
const SERIES_LIMIT = 200;

function DefinitionsCatalog({ definitions }: { definitions: MetricDefinition[] }) {
  const bySource = new Map<string, MetricDefinition[]>();
  definitions.forEach((d) => bySource.set(d.source, [...(bySource.get(d.source) ?? []), d]));
  return (
    <div className="stack">
      {[...bySource.entries()].map(([source, defs]) => (
        <details key={source} className="panel" style={{ padding: 16 }}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>
            {label(SOURCE, source)} <span className="faint small">({defs.length} métricas)</span>
          </summary>
          <dl className="stack" style={{ marginTop: 12 }}>
            {defs.map((d) => (
              <div key={d.key} className="code-block stack" style={{ gap: 4 }}>
                <dt className="row">
                  <code>{d.key}</code>
                  <Badge tone="neutral" outline icon={null}>
                    {unitLabel(d.unit)}
                  </Badge>
                </dt>
                <dd style={{ margin: 0 }} className="small">
                  <p>{d.description}</p>
                  <p className="muted">
                    <strong>Fórmula:</strong> {d.formula}
                  </p>
                  <p className="muted">
                    <strong>Ámbito:</strong> {d.scope}. <strong>Periodo:</strong> {d.min_period}
                  </p>
                  <p className="muted">
                    <strong>Insuficiente cuando:</strong> {d.insufficient_when}
                  </p>
                  <p className="faint">
                    <strong>Limitaciones:</strong> {d.limitations}
                  </p>
                </dd>
              </div>
            ))}
          </dl>
        </details>
      ))}
    </div>
  );
}

export function MetricsView() {
  const mode = useDataMode();
  const href = useModeHref();
  const router = useRouter();
  const params = useSearchParams();
  const definitions = useMetricDefinitions();

  const topicParam = params.get("tema_id") ?? "";
  const topicId = TOPIC_RE.test(topicParam) ? topicParam : "";
  const metricParam = params.get("metrica") ?? "";
  const known = definitions.data?.metricas.find((d) => d.key === metricParam);
  const metric = known ? known.key : "";
  const status = params.get("estado") === "ok" || params.get("estado") === "insufficient" ? params.get("estado")! : "";

  const values = useMetrics(
    mode,
    { tema_id: topicId || undefined, metrica: metric || undefined, estado: status || undefined, limite: topicId && metric ? SERIES_LIMIT : 50 },
    definitions.data !== undefined || !metricParam,
  );
  const names = useTopicNames(values.data?.items.map((v) => v.tema_id) ?? [], mode);

  const set = (changes: Record<string, string>) => {
    const next: Record<string, string> = {};
    for (const [k, v] of Object.entries({ tema_id: topicId, metrica: metric, estado: status, ...changes })) if (v) next[k] = v;
    router.replace(href("/metricas", next));
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="page-title">Métricas</h1>
          <p className="page-lede">
            Valores calculados por fuente y ámbito, en su unidad original. Las métricas de fuentes distintas no se combinan
            ni se comparan entre sí. Modo <ModeBadge mode={mode} />.
          </p>
        </div>
        <RefreshControl queries={[values]} />
      </header>

      <section className="panel" aria-labelledby="explorador" style={{ marginBottom: 24 }}>
        <div className="panel__head">
          <div>
            <h2 id="explorador" className="panel__title">
              Explorador de valores
            </h2>
            <p className="panel__sub">Elige un tema y una métrica para ver su serie temporal.</p>
          </div>
        </div>
        <div className="filters">
          <label className="field" style={{ flex: "1 1 220px" }}>
            Tema (identificador)
            <input
              key={topicId}
              className="input mono"
              defaultValue={topicId}
              name="tema_id"
              placeholder="tpc_0123456789abcdef…"
              autoComplete="off"
              spellCheck={false}
              translate="no"
              pattern="tpc_[0-9a-f]{16}"
              onBlur={(e) => {
                const value = e.target.value.trim();
                if (value === "" || TOPIC_RE.test(value)) set({ tema_id: value });
              }}
              onKeyDown={(e) => {
                const value = e.currentTarget.value.trim();
                if (e.key === "Enter" && (value === "" || TOPIC_RE.test(value))) set({ tema_id: value });
              }}
            />
          </label>
          <label className="field" style={{ flex: "1 1 240px" }}>
            Métrica
            <select className="select" value={metric} onChange={(e) => set({ metrica: e.target.value })}>
              <option value="">Todas</option>
              {definitions.data?.metricas.map((d) => (
                <option key={d.key} value={d.key}>
                  {label(SOURCE, d.source)}: {d.key}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Estado
            <select className="select" value={status} onChange={(e) => set({ estado: e.target.value })}>
              <option value="">Todos</option>
              <option value="ok">Calculada</option>
              <option value="insufficient">Insuficiente</option>
            </select>
          </label>
        </div>

        <QueryView query={values} skeletonLines={5}>
          {(page) => {
            if (page.items.length === 0) {
              return (
                <EmptyState title="Sin valores calculados">
                  No hay métricas registradas con estos filtros en este modo. Ausencia de datos no equivale a cero.
                </EmptyState>
              );
            }
            const series = topicId && metric ? buildSeries(page.items) : null;
            return (
              <div className="stack">
                {series ? (
                  series.kind === "ok" ? (
                    <>
                      {page.total > page.items.length ? (
                        <p className="notice notice--warn small">
                          Serie parcial: se muestran los {page.items.length} valores más recientes de {page.total}.
                        </p>
                      ) : null}
                      <MetricChart
                        series={series.series}
                        unit={series.unit}
                        metric={series.metric}
                        source={label(SOURCE, series.source)}
                        synthetic={mode === "simulated"}
                      />
                    </>
                  ) : (
                    <EmptyState title="No se dibuja una serie">
                      {series.kind === "mixed"
                        ? series.reason
                        : "Hacen falta al menos dos valores calculados del mismo ámbito para dibujar una serie. Se muestran los valores en la tabla."}
                    </EmptyState>
                  )
                ) : (
                  <p className="faint small">Para ver una serie temporal, indica un tema y una métrica concretos.</p>
                )}
                <div className="table-wrap" tabIndex={0}>
                  <table className="table">
                    <caption className="visually-hidden">Valores de métricas</caption>
                    <thead>
                      <tr>
                        <th scope="col">Fecha ref.</th>
                        <th scope="col">Tema</th>
                        <th scope="col">Métrica</th>
                        <th scope="col">Ámbito</th>
                        <th scope="col">Valor</th>
                        <th scope="col">
                          Estado <InfoTip label="Estado de la métrica">«Insuficiente»: DETECTAR no pudo calcularla y registró el motivo; no es un cero.</InfoTip>
                        </th>
                        <th scope="col">Fuente</th>
                      </tr>
                    </thead>
                    <tbody>
                      {page.items.map((v) => {
                        const st = METRIC_STATUS[v.estado];
                        return (
                          <tr key={`${v.tema_id}-${v.fuente}-${v.ambito}-${v.metrica}-${v.fecha_referencia}`}>
                            <td>
                              <Day value={v.fecha_referencia} />
                              <div className="faint small">ventana {v.ventana_dias} d</div>
                            </td>
                            <td>
                              <button type="button" className="row-btn" onClick={() => set({ tema_id: v.tema_id })}>
                                {names[v.tema_id] ?? <span className="mono small">{v.tema_id}</span>}
                              </button>
                            </td>
                            <td>
                              <code>{v.metrica}</code>
                              <div className="faint small">{v.version}</div>
                            </td>
                            <td className="small">{v.ambito}</td>
                            <td>
                              <span className="mono">{formatMetricValue(v.valor, v.unidad)}</span>
                              <div className="faint small">{unitLabel(v.unidad)}</div>
                            </td>
                            <td>
                              {st ? <Badge tone={st.tone}>{st.text}</Badge> : v.estado}
                              {v.motivo ? <div className="faint small">{v.motivo}</div> : null}
                            </td>
                            <td>
                              <div className="stack" style={{ gap: 4 }}>
                                {label(SOURCE, v.fuente)}
                                <ValidationBadge validated={v.fuente_validada} />
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="faint small">
                  {page.items.length} de {page.total} valores (orden de la API: fecha de referencia descendente).
                </p>
              </div>
            );
          }}
        </QueryView>
      </section>

      <section aria-labelledby="catalogo">
        <div className="page-head" style={{ marginBottom: 12 }}>
          <h2 id="catalogo" className="panel__title">
            Catálogo de definiciones
          </h2>
        </div>
        <QueryView query={definitions}>{(defs) => <DefinitionsCatalog definitions={defs.metricas} />}</QueryView>
      </section>
    </>
  );
}
