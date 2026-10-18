"use client";

import { ArrowUpRight, ChevronRight, Info } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Sparkline } from "@/components/trends/Sparkline";
import { ModeBadge, StageBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorNotice, QueryView, RefreshControl, Skeleton } from "@/components/ui/States";
import { Day } from "@/components/ui/Time";
import { useClassifications, useMetrics, useTopics } from "@/hooks/queries";
import { useDataMode, useModeHref } from "@/hooks/useDataMode";
import { buildUrl, getJson, OficinaError } from "@/lib/api-client";
import { displayName, plainReason, plainSources, STAGE_PLAIN } from "@/lib/plain";
import { MetricPage, type Classification, type DataMode, type MetricValue, type Stage, type Topic } from "@/lib/schemas";
import { buildSeries, type ScopeSeries } from "@/lib/series";

import styles from "./TrendsView.module.css";

const ORDER: Stage[] = ["acelerando", "emergente", "punto_maximo"];
const percent = new Intl.NumberFormat("es", { style: "percent", maximumFractionDigits: 0, signDisplay: "exceptZero" });
const integer = new Intl.NumberFormat("es");

/** Todas las páginas de una métrica (máximo 5 × 200 valores). */
function useAllValues(mode: DataMode, metric: string, enabled: boolean) {
  const [state, setState] = useState<{ items?: MetricValue[]; error?: OficinaError }>({});
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    (async () => {
      const items: MetricValue[] = [];
      for (let offset = 0; offset < 1000; offset += 200) {
        const page = await getJson(buildUrl("/metricas", { data_mode: mode, metrica: metric, limite: 200, desplazamiento: offset }), MetricPage, controller.signal);
        items.push(...page.items);
        if (offset + page.items.length >= page.total) break;
      }
      return items;
    })()
      .then((items) => setState({ items }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setState({ error: error instanceof OficinaError ? error : new OficinaError("invalid", "No se pudieron leer las visitas") });
      });
    return () => controller.abort();
  }, [mode, metric, enabled]);
  return state;
}

/** Serie principal de Wikipedia de un tema: el ámbito (artículo) con más visitas. */
function mainSeries(values: MetricValue[] | undefined, topicId: string): ScopeSeries | null {
  const own = (values ?? []).filter((v) => v.tema_id === topicId);
  const result = buildSeries(own.filter((v) => v.ambito === bestScope(own)));
  return result.kind === "ok" ? (result.series[0] ?? null) : null;
}

function bestScope(values: MetricValue[]): string | undefined {
  const totals = new Map<string, number>();
  for (const v of values) totals.set(v.ambito, (totals.get(v.ambito) ?? 0) + (v.valor ?? 0));
  return [...totals.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
}

function TrendCard({ item, topic, series, growth, href }: { item: Classification; topic?: Topic; series: ScopeSeries | null; growth?: MetricValue; href: string }) {
  const last = series?.points.at(-1);
  const name = displayName(topic?.nombre ?? item.tema_id);
  return (
    <li className={styles.card} data-stage={item.etapa}>
      <span className={styles.channelCell}>
        <StageBadge stage={item.etapa} />
      </span>
      <div className={styles.cardMain}>
        <h3 className={styles.name}>{name}</h3>
        <p className={styles.sources}>{topic ? `Visto en ${plainSources(topic.vinculos_por_fuente)}` : ""}</p>
      </div>
      <div className={styles.cardData}>
        {series && last ? (
          <>
            <span className={styles.spark}>
              <Sparkline segments={series.segments} />
            </span>
            <p className={styles.figure}>
              <strong>{integer.format(last.value)}</strong> visitas en Wikipedia en 7 días
              {growth?.estado === "ok" && growth.valor !== null ? (
                <span className={growth.valor >= 0 ? styles.up : styles.down}>
                  {" "}
                  ({percent.format(growth.valor)} frente a la semana anterior)
                </span>
              ) : null}
            </p>
          </>
        ) : (
          <p className={styles.figure}>Sin serie de visitas en Wikipedia.</p>
        )}
      </div>
      <Link className={styles.more} href={href} aria-label={`Ver la evidencia de ${name}`}>
        Ver evidencia <ChevronRight size={15} aria-hidden="true" />
      </Link>
    </li>
  );
}

export function TrendsView() {
  const mode = useDataMode();
  const href = useModeHref();
  const latest = useClassifications(mode, { limite: 100 });
  const dates = [...new Set((latest.data?.items ?? []).map((i) => i.fecha_referencia))].sort().reverse();
  // Si a la fecha más reciente le faltan días de Wikipedia (lo dicen sus métricas: current_missing_days),
  // se muestra la anterior y se avisa; la persona puede ver la más reciente igualmente.
  const latestGrowth = useMetrics(mode, { metrica: "wiki_views_growth", fecha_referencia: dates[0], limite: 200 }, dates[0] !== undefined);
  const missing = (latestGrowth.data?.items ?? []).filter((m) => (m.motivo ?? "").startsWith("current_missing_days")).length;
  const incomplete = latestGrowth.data !== undefined && latestGrowth.data.items.length > 0 && missing / latestGrowth.data.items.length >= 0.5;
  const [showLatest, setShowLatest] = useState(false);
  const fallback = incomplete && !showLatest && dates[1] !== undefined;
  const asOf = latestGrowth.data === undefined && dates[0] ? undefined : fallback ? dates[1] : dates[0];
  const list = useClassifications(mode, { fecha_referencia: asOf, limite: 100 }, asOf !== undefined);
  const topics = useTopics(mode, { limite: 100 });
  const growth = useMetrics(mode, { metrica: "wiki_views_growth", fecha_referencia: asOf, limite: 200 }, asOf !== undefined);
  const views = useAllValues(mode, "wiki_views_total", asOf !== undefined);

  const byId = useMemo(() => new Map((topics.data?.items ?? []).map((t) => [t.id, t])), [topics.data]);
  const growthOf = (topicId: string) => {
    const own = (growth.data?.items ?? []).filter((g) => g.tema_id === topicId);
    const scope = bestScope((views.items ?? []).filter((v) => v.tema_id === topicId));
    return own.find((g) => g.ambito === scope) ?? own[0];
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="page-title">Tendencias</h1>
          <p className="page-lede">
            Temas que la gente está buscando hoy (Google Trends) y cómo evolucionan sus visitas en Wikipedia. Modo{" "}
            <ModeBadge mode={mode} />.
          </p>
        </div>
        <RefreshControl queries={[latest, list, topics, growth]} />
      </header>

      <QueryView query={latest} skeletonLines={4}>
        {(first) => {
          if (first.items.length > 0 && !asOf) return <Skeleton lines={6} />;
          if (!asOf || first.items.length === 0) {
            return (
              <EmptyState title="Todavía no hay tendencias calculadas">
                {mode === "real" ? (
                  <>
                    Con el backend en marcha, ejecuta <code>npm run tendencias:actualizar</code> en{" "}
                    <code>frontend/oficina</code>: trae las tendencias de hoy y calcula sus etapas.
                  </>
                ) : (
                  <>
                    Prepara la demostración con <code>npm run demo:preparar</code>.
                  </>
                )}
              </EmptyState>
            );
          }
          if (list.data === undefined) {
            return list.error ? <ErrorNotice error={list.error} onRetry={list.refetch} /> : <Skeleton lines={6} />;
          }
          const items = list.data.items;
          const classified = new Set(items.map((i) => i.tema_id));
          const unclear = items.filter((i) => !ORDER.includes(i.etapa));
          const withoutHistory = (topics.data?.items ?? []).filter(
            (t) => !classified.has(t.id) && (t.vinculos_por_fuente.google_trends_rss ?? 0) > 0,
          );
          return (
            <div className={styles.page}>
              <p className={styles.dateLine}>
                <Info size={15} aria-hidden="true" /> Datos hasta el <Day value={asOf} />. Wikipedia publica las visitas con un día
                de retraso.
              </p>
              {fallback ? (
                <p className={styles.dateNote} role="note">
                  El <Day value={dates[0]} /> todavía no tiene completas las visitas de Wikipedia (sus métricas lo indican), así
                  que se muestra el día anterior.{" "}
                  <button type="button" className={styles.linkButton} onClick={() => setShowLatest(true)}>
                    Ver el <Day value={dates[0]} /> igualmente
                  </button>
                </p>
              ) : null}

              {ORDER.map((stage) => {
                const group = items.filter((i) => i.etapa === stage);
                return (
                  <section key={stage} className={styles.group} data-stage={stage} aria-labelledby={`g-${stage}`}>
                    <div className={styles.groupHead}>
                      <h2 id={`g-${stage}`} className={styles.groupTitle}>
                        {STAGE_PLAIN[stage].title} <span className={styles.count}>{group.length}</span>
                      </h2>
                      <p className={styles.groupSentence}>{STAGE_PLAIN[stage].sentence}</p>
                    </div>
                    {group.length ? (
                      <ul className={styles.cards}>
                        {group.map((item) => (
                          <TrendCard
                            key={item.id}
                            item={item}
                            topic={byId.get(item.tema_id)}
                            series={mainSeries(views.items, item.tema_id)}
                            growth={growthOf(item.tema_id)}
                            href={href("/clasificaciones", { tema_id: item.tema_id })}
                          />
                        ))}
                      </ul>
                    ) : (
                      <p className={styles.none}>Ningún tema en esta etapa ahora mismo.</p>
                    )}
                  </section>
                );
              })}

              <details className={styles.unclear}>
                <summary>
                  {STAGE_PLAIN.datos_insuficientes.title}: {unclear.length} temas{" "}
                  <span className="muted small">(ver por qué)</span>
                </summary>
                <ul className={styles.unclearList}>
                  {unclear.map((item) => (
                    <li key={item.id}>
                      <Link href={href("/clasificaciones", { tema_id: item.tema_id })} className={styles.unclearName}>
                        {displayName(byId.get(item.tema_id)?.nombre ?? item.tema_id)}
                      </Link>
                      <span className="muted small">{plainReason(item)}</span>
                    </li>
                  ))}
                </ul>
              </details>

              {withoutHistory.length ? (
                <details className={styles.unclear}>
                  <summary>
                    Tendencias de hoy sin historial: {withoutHistory.length} temas{" "}
                    <span className="muted small">(no tienen artículo en Wikipedia para medir su evolución)</span>
                  </summary>
                  <p className={styles.chips}>{withoutHistory.map((t) => displayName(t.nombre)).join(", ")}.</p>
                </details>
              ) : null}

              <aside className={styles.footnote}>
                <p>
                  <strong>Cómo leer esto:</strong> la etapa dice <em>en qué momento</em> está un tema, no si te conviene. Si encaja
                  con tu audiencia lo decidirá el módulo ENTENDER. Las reglas son provisionales (aún sin calibrar con datos
                  reales) y no hay medida de saturación todavía.
                </p>
                <Link className={styles.moreInline} href={href("/clasificaciones")}>
                  Ver todas las evidencias <ArrowUpRight size={14} aria-hidden="true" />
                </Link>
              </aside>
            </div>
          );
        }}
      </QueryView>
    </>
  );
}
