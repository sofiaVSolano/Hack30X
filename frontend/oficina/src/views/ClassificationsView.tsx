"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Badge, CalibrationBadge, ModeBadge, StageBadge, ValidationBadge } from "@/components/ui/Badges";
import { InfoTip } from "@/components/ui/InfoTip";
import { EmptyState, QueryView, RefreshControl } from "@/components/ui/States";
import { Structured } from "@/components/ui/Structured";
import { Day, Time } from "@/components/ui/Time";
import { useClassifications, useStageRules, useTopicNames } from "@/hooks/queries";
import { useDataMode, useModeHref } from "@/hooks/useDataMode";
import { EVIDENCE_ROLE, label, SOURCE, STAGE } from "@/lib/labels";
import { STAGES, type Classification, type StageRules } from "@/lib/schemas";

const TOPIC_RE = /^tpc_[0-9a-f]{16}$/;
const PAGE = 20;
const FILTER_SOURCES = ["google_trends_rss", "wikimedia", "gdelt"] as const;

function RulesPanel({ rules }: { rules: StageRules }) {
  return (
    <section className="panel" aria-labelledby="reglas" style={{ borderColor: rules.calibrado ? undefined : "rgba(243,185,74,.3)" }}>
      <div className="panel__head">
        <div>
          <h2 id="reglas" className="panel__title">
            Reglas <code>{rules.version}</code> sobre métricas <code>{rules.version_metricas}</code>
          </h2>
          <p className="panel__sub">
            Huella de parámetros <code title={rules.parametros_sha256}>{rules.parametros_sha256.slice(0, 12)}…</code>
            {rules.registrada ? ", registrada en la base" : ", aún no registrada en la base"}
          </p>
        </div>
        <div className="row">
          <CalibrationBadge calibrated={rules.calibrado} />
          {rules.provisional ? <Badge tone="warn">Provisionales</Badge> : null}
        </div>
      </div>
      {!rules.calibrado ? (
        <p className="notice notice--warn small" style={{ marginBottom: 12 }}>
          Los umbrales de las etapas son provisionales y no se han validado con datos reales. Úsalas como orientación, no
          como resultado confirmado.
        </p>
      ) : null}
      <dl className="dl small">
        {Object.entries(rules.etapas).map(([stage, text]) => (
          <div key={stage} style={{ display: "contents" }}>
            <dt>{label(Object.fromEntries(Object.entries(STAGE).map(([k, v]) => [k, v.text])), stage)}</dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>
      <details style={{ marginTop: 12 }}>
        <summary className="small muted">Qué etapas puede proponer cada fuente</summary>
        <dl className="dl small" style={{ marginTop: 8 }}>
          {Object.entries(rules.capacidades_por_fuente).map(([source, stages]) => (
            <div key={source} style={{ display: "contents" }}>
              <dt>{label(SOURCE, source)}</dt>
              <dd>{stages.length ? stages.join(", ") : <span className="faint">ninguna</span>}</dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  );
}

function notesOf(explanation: Record<string, unknown>): string[] {
  const notes = explanation.notes;
  return Array.isArray(notes) ? notes.filter((n): n is string => typeof n === "string") : [];
}

function ClassificationCard({ item, name }: { item: Classification; name: string | null | undefined }) {
  const [open, setOpen] = useState(false);
  const notes = notesOf(item.explicacion);
  return (
    <article className="panel stack" aria-labelledby={`c-${item.id}`}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h3 id={`c-${item.id}`} style={{ fontSize: 17 }}>
            {name ?? <span className="mono">{item.tema_id}</span>}
          </h3>
          <p className="faint small mono">{item.tema_id}</p>
        </div>
        <div className="row">
          <StageBadge stage={item.etapa} />
          <CalibrationBadge calibrated={item.calibrado} />
          {item.data_mode === "simulated" ? <ModeBadge mode="simulated" /> : null}
          {item.reemplazada ? <Badge tone="neutral" outline icon={null}>Reemplazada</Badge> : null}
        </div>
      </div>
      <dl className="dl small">
        <dt>Fecha de referencia</dt>
        <dd>
          <Day value={item.fecha_referencia} />
        </dd>
        <dt>Calculada</dt>
        <dd>
          <Time value={item.calculado} />
        </dd>
        <dt>Versión</dt>
        <dd className="mono">
          {item.version} sobre {item.version_metricas}
        </dd>
        {item.motivo ? (
          <>
            <dt>Motivo</dt>
            <dd className="mono">{item.motivo}</dd>
          </>
        ) : null}
        {item.reemplazada ? (
          <>
            <dt>Reemplazada</dt>
            <dd>
              <Time value={item.reemplazada} />
            </dd>
          </>
        ) : null}
      </dl>

      <div className="table-wrap" tabIndex={0}>
        <table className="table">
          <caption className="visually-hidden">Evidencias por fuente</caption>
          <thead>
            <tr>
              <th scope="col">Fuente</th>
              <th scope="col">
                Rol <InfoTip label="Rol de la evidencia">Principal: puede determinar la etapa. Complementaria: solo se informa. Excluida: no aporta.</InfoTip>
              </th>
              <th scope="col">Etapa propuesta</th>
              <th scope="col">Motivo</th>
            </tr>
          </thead>
          <tbody>
            {item.evidencia.length === 0 ? (
              <tr>
                <td colSpan={4} className="faint">
                  Sin evidencias registradas.
                </td>
              </tr>
            ) : (
              item.evidencia.map((e) => (
                <tr key={e.fuente}>
                  <td>
                    <div className="stack" style={{ gap: 4 }}>
                      {label(SOURCE, e.fuente)}
                      <ValidationBadge validated={e.fuente_validada} />
                    </div>
                  </td>
                  <td title={EVIDENCE_ROLE[e.rol]?.hint}>{EVIDENCE_ROLE[e.rol]?.text ?? e.rol}</td>
                  <td>{e.etapa_propuesta ? <StageBadge stage={e.etapa_propuesta} /> : <span className="faint">—</span>}</td>
                  <td className="small">{e.motivo}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {notes.length ? (
        <ul className="structured__list small muted">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}

      <div>
        <button type="button" className="btn btn--ghost" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? "Ocultar" : "Ver"} explicación completa y métricas consideradas
        </button>
      </div>
      {open ? (
        <div className="stack">
          <div className="code-block">
            <p className="code-block__title">
              explicacion
            </p>
            <Structured value={item.explicacion} />
          </div>
          <div className="code-block">
            <p className="code-block__title">
              metricas_consideradas ({item.metricas_consideradas.length})
            </p>
            <Structured value={item.metricas_consideradas} />
          </div>
          {item.evidencia.some((e) => e.ambitos.length) ? (
            <div className="code-block">
              <p className="code-block__title">
                ámbitos por fuente
              </p>
              <Structured value={Object.fromEntries(item.evidencia.map((e) => [e.fuente, e.ambitos]))} />
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

export function ClassificationsView() {
  const mode = useDataMode();
  const href = useModeHref();
  const router = useRouter();
  const params = useSearchParams();
  const rules = useStageRules();
  const [offset, setOffset] = useState(0);

  const topicParam = params.get("tema_id") ?? "";
  const topicId = TOPIC_RE.test(topicParam) ? topicParam : "";
  const stageParam = params.get("etapa") ?? "";
  const stage = (STAGES as readonly string[]).includes(stageParam) ? stageParam : "";
  const sourceParam = params.get("fuente") ?? "";
  const source = (FILTER_SOURCES as readonly string[]).includes(sourceParam) ? sourceParam : "";
  const superseded = params.get("incluir_reemplazadas") === "true";

  const list = useClassifications(mode, {
    tema_id: topicId || undefined,
    etapa: stage || undefined,
    fuente: source || undefined,
    incluir_reemplazadas: superseded ? "true" : undefined,
    limite: PAGE,
    desplazamiento: offset,
  });
  const names = useTopicNames(list.data?.items.map((c) => c.tema_id) ?? [], mode);

  const set = (changes: Record<string, string>) => {
    const next: Record<string, string> = {};
    const merged = { tema_id: topicId, etapa: stage, fuente: source, incluir_reemplazadas: superseded ? "true" : "", ...changes };
    for (const [k, v] of Object.entries(merged)) if (v) next[k] = v;
    setOffset(0);
    router.replace(href("/clasificaciones", next));
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="page-title">Clasificaciones</h1>
          <p className="page-lede">
            Etapa de cada tema según las reglas de DETECTAR, con la evidencia de cada fuente. La interfaz no asigna ni
            recalcula etapas. Modo <ModeBadge mode={mode} />.
          </p>
        </div>
        <RefreshControl queries={[list, rules]} />
      </header>

      <div className="stack" style={{ gap: 24 }}>
        <QueryView query={rules}>{(r) => <RulesPanel rules={r} />}</QueryView>

        <section aria-labelledby="lista" className="stack">
          <h2 id="lista" className="visually-hidden">
            Clasificaciones
          </h2>
          <div className="filters panel" style={{ padding: 16 }}>
            <label className="field">
              Etapa
              <select className="select" value={stage} onChange={(e) => set({ etapa: e.target.value })}>
                <option value="">Todas</option>
                {STAGES.map((s) => (
                  <option key={s} value={s}>
                    {STAGE[s].text}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Fuente con evidencia
              <select className="select" value={source} onChange={(e) => set({ fuente: e.target.value })}>
                <option value="">Todas</option>
                {FILTER_SOURCES.map((s) => (
                  <option key={s} value={s}>
                    {label(SOURCE, s)}
                  </option>
                ))}
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={superseded} onChange={(e) => set({ incluir_reemplazadas: e.target.checked ? "true" : "" })} />
              Incluir reemplazadas
            </label>
            {topicId ? (
              <span className="row">
                <Badge tone="neutral" outline icon={null}>
                  Tema: {names[topicId] ?? topicId}
                </Badge>
                <button type="button" className="btn btn--ghost" onClick={() => set({ tema_id: "" })}>
                  Quitar filtro de tema
                </button>
              </span>
            ) : null}
          </div>

          <QueryView query={list} skeletonLines={6}>
            {(page) =>
              page.items.length === 0 ? (
                <EmptyState title="Sin clasificaciones">
                  No hay clasificaciones con estos filtros en este modo. Una clasificación solo existe después de calcular
                  métricas y etapas en el backend.
                </EmptyState>
              ) : (
                <>
                  {page.items.map((item) => (
                    <ClassificationCard key={item.id} item={item} name={names[item.tema_id]} />
                  ))}
                  <div className="pager">
                    <span className="faint small">
                      {page.desplazamiento + 1}–{page.desplazamiento + page.items.length} de {page.total}
                    </span>
                    <span className="row">
                      <button type="button" className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                        Anterior
                      </button>
                      <button
                        type="button"
                        className="btn"
                        disabled={page.desplazamiento + page.items.length >= page.total}
                        onClick={() => setOffset(offset + PAGE)}
                      >
                        Siguiente
                      </button>
                    </span>
                  </div>
                </>
              )
            }
          </QueryView>
        </section>
      </div>
    </>
  );
}
