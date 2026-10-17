"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, ModeBadge, StageBadge } from "@/components/ui/Badges";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState, QueryView, RefreshControl } from "@/components/ui/States";
import { Day, Time } from "@/components/ui/Time";
import { useClassifications, useLinks, useTopic, useTopics } from "@/hooks/queries";
import { useDataMode, useModeHref } from "@/hooks/useDataMode";
import { label, LINK_RULE, LINK_STATUS, SOURCE } from "@/lib/labels";
import type { DataMode, TopicLink } from "@/lib/schemas";

const PAGE = 20;

function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

function LinksTable({ links }: { links: TopicLink[] }) {
  return (
    <div className="table-wrap" tabIndex={0}>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Fuente</th>
            <th scope="col">Sujeto original</th>
            <th scope="col">Estado</th>
            <th scope="col">Regla</th>
            <th scope="col">Creado</th>
          </tr>
        </thead>
        <tbody>
          {links.map((link) => {
            const status = LINK_STATUS[link.estado];
            return (
              <tr key={link.id}>
                <td>{label(SOURCE, link.fuente)}</td>
                <td>
                  {link.sujeto_original}
                  <div className="faint small mono">observación {link.observacion_id}</div>
                </td>
                <td>
                  {status ? <Badge tone={status.tone}>{status.text}</Badge> : link.estado}
                  {link.motivo ? <div className="faint small">{link.motivo}</div> : null}
                </td>
                <td className="small">{label(LINK_RULE, link.regla)}</td>
                <td className="small">
                  <Time value={link.creado} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function TopicDrawer({ topicId, mode, onClose }: { topicId: string | null; mode: DataMode; onClose: () => void }) {
  const detail = useTopic(topicId, mode);
  const links = useLinks(mode, { tema_id: topicId ?? undefined, limite: 50 }, topicId !== null);
  const classification = useClassifications(mode, { tema_id: topicId ?? undefined, limite: 1 }, topicId !== null);
  const href = useModeHref();
  return (
    <Dialog
      open={topicId !== null}
      onClose={onClose}
      title={detail.data?.tema.nombre ?? "Tema"}
      subtitle={
        <span className="row">
          <span className="mono">{topicId}</span>
          <ModeBadge mode={mode} />
        </span>
      }
    >
      <QueryView query={detail}>
        {(d) => (
          <>
            <div className="row">
              {d.tema.ambiguo ? <Badge tone="warn">Marcado como ambiguo</Badge> : <Badge tone="neutral">No ambiguo</Badge>}
              <Link className="btn" href={href("/metricas", { tema_id: d.tema.id })}>
                Ver métricas
              </Link>
              <Link className="btn" href={href("/clasificaciones", { tema_id: d.tema.id })}>
                Ver clasificaciones
              </Link>
            </div>
            {d.tema.ambiguo && d.tema.motivo_ambiguedad ? <p className="muted">{d.tema.motivo_ambiguedad}</p> : null}
            <dl className="dl">
              <dt>Clave normalizada</dt>
              <dd className="mono">{d.tema.clave_normalizada}</dd>
              <dt>Creado por</dt>
              <dd className="mono">{d.tema.creado_por}</dd>
              <dt>Creado</dt>
              <dd>
                <Time value={d.tema.creado} />
              </dd>
              <dt>Actualizado</dt>
              <dd>
                <Time value={d.tema.actualizado} />
              </dd>
            </dl>
            <section className="stack">
              <h3 className="panel__title">Última clasificación vigente</h3>
              <QueryView query={classification} skeletonLines={1}>
                {(page) => {
                  const c = page.items[0];
                  return c ? (
                    <p className="row">
                      <StageBadge stage={c.etapa} /> <span className="muted">al</span> <Day value={c.fecha_referencia} />
                      <span className="faint small mono">{c.version}</span>
                    </p>
                  ) : (
                    <p className="muted">Sin clasificaciones para este tema.</p>
                  );
                }}
              </QueryView>
            </section>
            <section className="stack">
              <h3 className="panel__title">Alias ({d.alias.length})</h3>
              {d.alias.length ? (
                <ul className="chips">
                  {d.alias.map((a) => (
                    <li key={`${a.tipo}-${a.normalizado}`}>
                      <Badge tone="neutral" outline icon={null} title={`${a.tipo} · ${a.origen}`}>
                        {a.texto}
                      </Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">Sin alias.</p>
              )}
            </section>
            <section className="stack">
              <h3 className="panel__title">Sujetos por fuente</h3>
              {d.sujetos.length ? (
                <div className="table-wrap" tabIndex={0}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th scope="col">Fuente</th>
                        <th scope="col">Sujeto original</th>
                        <th scope="col">Observaciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.sujetos.map((s) => (
                        <tr key={`${s.fuente}-${s.sujeto_original}`}>
                          <td>{label(SOURCE, s.fuente)}</td>
                          <td>{s.sujeto_original}</td>
                          <td className="mono">{s.observaciones}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="muted">Sin observaciones vinculadas.</p>
              )}
            </section>
            <section className="stack">
              <h3 className="panel__title">Vínculos vigentes</h3>
              <QueryView query={links}>
                {(page) =>
                  page.items.length ? <LinksTable links={page.items} /> : <p className="muted">Sin vínculos vigentes.</p>
                }
              </QueryView>
            </section>
          </>
        )}
      </QueryView>
    </Dialog>
  );
}

export function TopicsView() {
  const mode = useDataMode();
  const [tab, setTab] = useState<"temas" | "revision">("temas");
  const [text, setText] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const query = useDebounced(text.trim());
  const searchActive = query.length >= 2;
  const topics = useTopics(mode, { q: searchActive ? query : undefined, limite: PAGE, desplazamiento: offset });
  const review = useLinks(mode, { estado: "needs_review", limite: 50 }, tab === "revision");

  useEffect(() => setOffset(0), [query, mode]);

  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="page-title">Temas</h1>
          <p className="page-lede">
            Temas normalizados y sus vínculos con observaciones de cada fuente. Esta vista no fusiona temas ni cambia
            vínculos. Modo <ModeBadge mode={mode} />.
          </p>
        </div>
        <RefreshControl queries={tab === "temas" ? [topics] : [review]} />
      </header>

      <div className="row" role="tablist" aria-label="Secciones de temas" style={{ marginBottom: 16 }}>
        <button type="button" role="tab" aria-selected={tab === "temas"} className="btn" onClick={() => setTab("temas")}>
          Temas
        </button>
        <button type="button" role="tab" aria-selected={tab === "revision"} className="btn" onClick={() => setTab("revision")}>
          Cola de revisión
        </button>
      </div>

      {tab === "temas" ? (
        <section className="panel" role="tabpanel" aria-label="Temas">
          <div className="filters">
            <label className="field" style={{ flex: "1 1 260px" }}>
              Buscar tema
              <span className="row" style={{ position: "relative" }}>
                <Search size={16} aria-hidden="true" style={{ position: "absolute", left: 10, color: "var(--text-faint)" }} />
                <input
                  className="input"
                  type="search"
                  value={text}
                  maxLength={100}
                  name="q"
                  autoComplete="off"
                  placeholder="Por ejemplo, Tema demo Alfa…"
                  aria-describedby="buscar-ayuda"
                  onChange={(e) => setText(e.target.value)}
                  style={{ paddingLeft: 32, width: "100%" }}
                />
              </span>
            </label>
          </div>
          <p id="buscar-ayuda" className="faint small" style={{ marginTop: -8, marginBottom: 12 }}>
            Busca por nombre o alias, con al menos 2 caracteres.
          </p>
          <QueryView query={topics} skeletonLines={6}>
            {(page) =>
              page.items.length === 0 ? (
                <EmptyState title={searchActive ? "Ningún tema coincide con la búsqueda" : "Sin temas"}>
                  {searchActive ? `Sin resultados para «${query}».` : "Todavía no hay temas normalizados en este modo."}
                </EmptyState>
              ) : (
                <>
                  <div className="table-wrap" tabIndex={0}>
                    <table className="table">
                      <caption className="visually-hidden">Temas</caption>
                      <thead>
                        <tr>
                          <th scope="col">Tema</th>
                          <th scope="col">Vínculos por fuente</th>
                          <th scope="col">Revisión</th>
                          <th scope="col">Actualizado</th>
                        </tr>
                      </thead>
                      <tbody>
                        {page.items.map((t) => (
                          <tr key={t.id}>
                            <td>
                              <button type="button" className="row-btn" onClick={() => setSelected(t.id)}>
                                {t.nombre}
                              </button>
                              <div className="faint small mono">{t.id}</div>
                            </td>
                            <td>
                              {Object.keys(t.vinculos_por_fuente).length ? (
                                <ul className="chips">
                                  {Object.entries(t.vinculos_por_fuente).map(([source, n]) => (
                                    <li key={source}>
                                      <Badge tone="neutral" outline icon={null}>
                                        {label(SOURCE, source)}: {n}
                                      </Badge>
                                    </li>
                                  ))}
                                </ul>
                              ) : (
                                <span className="faint">Sin vínculos</span>
                              )}
                            </td>
                            <td>{t.ambiguo ? <Badge tone="warn">Ambiguo</Badge> : <span className="faint">—</span>}</td>
                            <td className="small">
                              <Time value={t.actualizado} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
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
      ) : (
        <section className="panel" role="tabpanel" aria-label="Cola de revisión">
          <p className="muted small" style={{ marginBottom: 12 }}>
            Vínculos con estado <code>needs_review</code>: posibles coincidencias que requieren una decisión humana. Las
            correcciones se hacen por la API administrativa, no desde esta vista.
          </p>
          <QueryView query={review}>
            {(page) =>
              page.items.length ? (
                <LinksTable links={page.items} />
              ) : (
                <EmptyState title="Nada pendiente de revisión">No hay vínculos que requieran revisión en este modo.</EmptyState>
              )
            }
          </QueryView>
        </section>
      )}

      <TopicDrawer topicId={selected} mode={mode} onClose={() => setSelected(null)} />
    </>
  );
}
