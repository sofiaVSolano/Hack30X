"use client";

import {
  FileDown,
  History,
  Images,
  Mic,
  MessageCircle,
  NotebookPen,
  Smartphone,
  Sparkles,
  BriefcaseBusiness,
  Video,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";

import { EngineBadge, VerdictBadge } from "@/components/crear/CrearBadges";
import styles from "@/components/crear/Lab.module.css";
import { ProposalCard, type RegenerationChanges } from "@/components/crear/ProposalCard";
import { selectionName, StartPicker, type Selection } from "@/components/crear/StartPicker";
import { Badge, ModeBadge, StageBadge } from "@/components/ui/Badges";
import { InfoTip } from "@/components/ui/InfoTip";
import { EmptyState, ErrorNotice, QueryView } from "@/components/ui/States";
import { Day, Time } from "@/components/ui/Time";
import { generateBatch, loadBatch, regenerateProposal, useCrearOptions, useProposalHistory } from "@/hooks/crear";
import { useDataMode } from "@/hooks/useDataMode";
import { buildUrl, OficinaError } from "@/lib/api-client";
import { ENGINE, ORIGIN } from "@/lib/crear/labels";
import { APPROACHES, type CreativeContext, type CrearOptions, type ProposalOut } from "@/lib/crear/schemas";
import type { DataMode } from "@/lib/schemas";

const PLATFORM_ICON: Record<string, LucideIcon> = {
  tiktok: Smartphone,
  instagram_reels: Smartphone,
  youtube_shorts: Smartphone,
  youtube: Video,
  instagram_carrusel: Images,
  x_hilo: MessageCircle,
  linkedin: BriefcaseBusiness,
  podcast: Mic,
  blog: NotebookPen,
};

interface Lot {
  batchId: string;
  context: CreativeContext | null;
  proposals: ProposalOut[];
}

interface Settings {
  plataforma: string;
  audiencia: string;
  detalle: string;
  pais: string;
}

/** Documento PDF del lote (lo genera el backend; el intermediario lo valida y lo reenvía). */
export function pdfUrl(mode: DataMode, batchId: string): string {
  return buildUrl(`/crear/lotes/${encodeURIComponent(batchId)}/pdf`, { data_mode: mode });
}

function toError(caught: unknown, title: string): OficinaError {
  return caught instanceof OficinaError ? caught : new OficinaError("invalid", title);
}

/** Versiones agrupadas por propuesta (raíz), en el orden educativa, controversial, narrativa. */
function groupVersions(proposals: ProposalOut[]): ProposalOut[][] {
  const byRoot = new Map<string, ProposalOut[]>();
  for (const proposal of proposals) {
    const list = byRoot.get(proposal.raiz_id) ?? [];
    list.push(proposal);
    byRoot.set(proposal.raiz_id, list);
  }
  return [...byRoot.values()]
    .map((list) => [...list].sort((a, b) => a.version - b.version))
    .sort((a, b) => APPROACHES.indexOf(a[0]!.enfoque) - APPROACHES.indexOf(b[0]!.enfoque));
}

function StepHead({ number, done, title, children }: { number: number; done: boolean; title: string; children?: ReactNode }) {
  return (
    <div className={styles.stepHead}>
      <span className={styles.stepNumber} data-done={done} aria-hidden="true">
        {number}
      </span>
      <div>
        <h2 className="panel__title">{title}</h2>
        {children ? <p className="panel__sub">{children}</p> : null}
      </div>
    </div>
  );
}

function SettingsPanel({
  options,
  selection,
  settings,
  onChange,
  onClear,
  onGenerate,
  busy,
  error,
}: {
  options: CrearOptions;
  selection: Selection | null;
  settings: Settings;
  onChange: (next: Partial<Settings>) => void;
  onClear: () => void;
  onGenerate: () => void;
  busy: boolean;
  error: OficinaError | null;
}) {
  const audience = options.audiencias.find((a) => a.id === settings.audiencia);
  return (
    <section className="panel" aria-labelledby="paso-2">
      <div id="paso-2">
        <StepHead number={2} done={selection !== null} title="Para quién y dónde">
          Elija la plataforma y la audiencia; el laboratorio crea tres propuestas con enfoques distintos.
        </StepHead>
      </div>
      {selection ? (
        <div className={styles.selected}>
          <div className="stack" style={{ gap: 6 }}>
            <span className="eyebrow">{ORIGIN[selection.origen]}</span>
            <strong>{selectionName(selection)}</strong>
            {selection.origen !== "manual" && (selection.veredicto || selection.etapa) ? (
              <span className="row">
                {selection.veredicto ? <VerdictBadge verdict={selection.veredicto} /> : null}
                {selection.etapa ? <StageBadge stage={selection.etapa} /> : null}
              </span>
            ) : null}
          </div>
          <button type="button" className="btn btn--ghost" onClick={onClear}>
            Cambiar
          </button>
        </div>
      ) : (
        <p className="notice small" style={{ marginBottom: 16 }}>
          Primero elija una brecha, un tema detectado o escriba un tema en el paso 1.
        </p>
      )}
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          onGenerate();
        }}
      >
        <fieldset className={styles.platforms}>
          <legend>Plataforma</legend>
          {options.plataformas.map((platform) => {
            const Icon = PLATFORM_ICON[platform.id] ?? Smartphone;
            return (
              <label key={platform.id} className={styles.platform}>
                <input
                  type="radio"
                  name="plataforma"
                  value={platform.id}
                  checked={settings.plataforma === platform.id}
                  onChange={() => onChange({ plataforma: platform.id })}
                />
                <Icon size={16} aria-hidden="true" />
                <span>
                  <span className={styles.platformName}>{platform.nombre}</span>
                  <span className={styles.platformFormat}>{platform.formato}</span>
                </span>
              </label>
            );
          })}
        </fieldset>
        <div className={styles.formRow}>
          <label className="field">
            Audiencia
            <select className="select" value={settings.audiencia} onChange={(e) => onChange({ audiencia: e.target.value })}>
              {options.audiencias.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.nombre}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            País
            <select className="select" value={settings.pais} onChange={(e) => onChange({ pais: e.target.value })}>
              <option value="">Toda Latinoamérica</option>
              {options.paises.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.nombre}
                </option>
              ))}
            </select>
          </label>
        </div>
        {audience ? (
          <p className="small muted" style={{ marginTop: -8 }}>
            {audience.descripcion} Tono: {audience.tono.charAt(0).toLowerCase() + audience.tono.slice(1)}
          </p>
        ) : null}
        <label className="field">
          Detalle de la audiencia (opcional)
          <input
            className="input"
            value={settings.detalle}
            maxLength={200}
            placeholder="Por ejemplo, estudiantes de ingeniería en Bogotá"
            onChange={(e) => onChange({ detalle: e.target.value })}
          />
        </label>
        {error ? <ErrorNotice error={error} /> : null}
        <button type="submit" className={`btn ${styles.primary}`} disabled={!selection || busy} aria-busy={busy}>
          <Sparkles size={16} aria-hidden="true" className={busy ? "spin" : undefined} />
          {busy ? "Generando las tres propuestas…" : "Generar 3 propuestas"}
        </button>
        <p className="faint small" aria-live="polite">
          {busy && options.motor.id === "claude" ? "Claude puede tardar hasta un minuto." : ""}
        </p>
      </form>
    </section>
  );
}

function Board({
  mode,
  lot,
  options,
  onRegenerate,
  headingRef,
}: {
  mode: DataMode;
  lot: Lot;
  options: CrearOptions | undefined;
  onRegenerate: (proposalId: string, changes: RegenerationChanges) => Promise<void>;
  headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  const groups = useMemo(() => groupVersions(lot.proposals), [lot.proposals]);
  const first = groups[0]?.[0];
  const context = lot.context;
  return (
    <section aria-labelledby="propuestas" style={{ marginBottom: 32 }}>
      <div className={styles.boardHead}>
        <div className={styles.stepHead} style={{ marginBottom: 0 }}>
          <span className={styles.stepNumber} data-done="true" aria-hidden="true">
            3
          </span>
          <div>
            <h2 id="propuestas" className="panel__title" ref={headingRef} tabIndex={-1}>
              Propuestas para «{first?.tema_nombre ?? context?.tema_nombre}»
            </h2>
            <p className="panel__sub">
              {context ? ORIGIN[context.origen] : null}
              {context?.fecha_referencia ? (
                <>
                  {" "}
                  con datos de DETECTAR al <Day value={context.fecha_referencia} />
                </>
              ) : null}
              . Cada tarjeta puede regenerarse con otro enfoque, audiencia o plataforma; las versiones anteriores se
              conservan.
            </p>
          </div>
        </div>
        <div className="row">
          {context?.veredicto_brecha ? <VerdictBadge verdict={context.veredicto_brecha} /> : null}
          {context?.etapa ? <StageBadge stage={context.etapa} /> : null}
          {first ? <EngineBadge engine={first.motor} model={first.modelo} /> : null}
        </div>
      </div>
      <div className={styles.download}>
        <p>
          <strong>Documento listo.</strong> Descargue el PDF con las tres propuestas (su versión más reciente), los datos de
          DETECTAR que usaron y sus precauciones, para compartirlo con el equipo.
        </p>
        <a className={`btn ${styles.primary}`} href={pdfUrl(mode, lot.batchId)} download>
          <FileDown size={16} aria-hidden="true" />
          Descargar PDF
        </a>
      </div>
      {context ? (
        <details className="panel" style={{ padding: 16, marginBottom: 16 }}>
          <summary className="small">
            Datos de DETECTAR que usaron las propuestas ({context.hechos.length}) y sus limitaciones
          </summary>
          <div className="stack" style={{ marginTop: 12 }}>
            {context.hechos.length ? (
              <ul className={styles.facts}>
                {context.hechos.map((fact) => (
                  <li key={fact.clave}>
                    {fact.texto} <span className="faint">({fact.fuente})</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="small muted">Sin datos de DETECTAR: es un tema escrito a mano.</p>
            )}
            {context.limitaciones.length ? (
              <ul className="structured__list small muted">
                {context.limitaciones.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            ) : null}
          </div>
        </details>
      ) : null}
      <div className={styles.board}>
        {groups.map((versions) => (
          <ProposalCard key={versions[0]!.raiz_id} versions={versions} options={options} onRegenerate={onRegenerate} />
        ))}
      </div>
    </section>
  );
}

function HistoryPanel({
  mode,
  currentBatch,
  onOpen,
  history,
}: {
  mode: DataMode;
  currentBatch: string | null;
  onOpen: (batchId: string) => void;
  history: ReturnType<typeof useProposalHistory>;
}) {
  return (
    <section className="panel" aria-labelledby="historial">
      <div className="panel__head">
        <div>
          <h2 id="historial" className="panel__title">
            <History size={16} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 6 }} />
            Propuestas guardadas
          </h2>
          <p className="panel__sub">
            Se guardan en la base de CREAR, separadas por modo <ModeBadge mode={mode} />. Nunca se editan: cada cambio es una
            versión nueva.
          </p>
        </div>
      </div>
      <QueryView query={history} skeletonLines={3}>
        {(page) => {
          const lots = new Map<string, ProposalOut[]>();
          for (const item of page.items) {
            const list = lots.get(item.lote_id) ?? [];
            list.push(item);
            lots.set(item.lote_id, list);
          }
          if (!lots.size) {
            return <EmptyState title="Todavía no hay propuestas en este modo">Genere las primeras en los pasos 1 y 2.</EmptyState>;
          }
          return (
            <ul className={styles.history}>
              {[...lots.entries()].slice(0, 12).map(([batchId, items]) => {
                const originals = items.filter((p) => p.version === 1);
                const first = originals[0] ?? items[items.length - 1]!;
                const engines = [...new Set(items.map((p) => ENGINE[p.motor] ?? p.motor))].join(" y ");
                return (
                  <li key={batchId} className={styles.historyItem} data-current={batchId === currentBatch}>
                    <div className="stack" style={{ gap: 2 }}>
                      <strong>{first.tema_nombre}</strong>
                      <span className="small muted">
                        {ORIGIN[first.origen]}. {items.length} {items.length === 1 ? "versión" : "versiones"} con {engines}. Creado{" "}
                        <Time value={first.creado} />.
                      </span>
                    </div>
                    <span className="row">
                      <a className="btn btn--ghost" href={pdfUrl(mode, batchId)} download aria-label={`Descargar PDF de ${first.tema_nombre}`}>
                        <FileDown size={15} aria-hidden="true" />
                        PDF
                      </a>
                      <button type="button" className="btn" onClick={() => onOpen(batchId)} aria-pressed={batchId === currentBatch}>
                        {batchId === currentBatch ? "Abierto" : "Abrir"}
                      </button>
                    </span>
                  </li>
                );
              })}
            </ul>
          );
        }}
      </QueryView>
    </section>
  );
}

export function LabView() {
  const mode = useDataMode();
  const options = useCrearOptions();
  const history = useProposalHistory(mode);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [settings, setSettings] = useState<Settings>({ plataforma: "tiktok", audiencia: "", detalle: "", pais: "" });
  const [lot, setLot] = useState<Lot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<OficinaError | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const refetchHistory = history.refetch;

  // Cada modo de datos es independiente: al cambiarlo se empieza de cero.
  useEffect(() => {
    setSelection(null);
    setLot(null);
    setError(null);
  }, [mode]);

  const defaultAudience = options.data?.audiencia_por_defecto;
  useEffect(() => {
    if (defaultAudience) setSettings((prev) => (prev.audiencia ? prev : { ...prev, audiencia: defaultAudience }));
  }, [defaultAudience]);

  useEffect(() => {
    if (lot) headingRef.current?.focus();
  }, [lot?.batchId]);

  async function generate() {
    if (!selection || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await generateBatch({
        data_mode: mode,
        origen: selection.origen,
        ...(selection.origen === "manual" ? { tema_texto: selection.texto } : { tema_id: selection.temaId }),
        audiencia: settings.audiencia || defaultAudience || "general_latam",
        audiencia_detalle: settings.detalle.trim() || null,
        plataforma: settings.plataforma,
        pais: settings.pais || null,
      });
      setLot({ batchId: result.lote_id, context: result.contexto, proposals: result.propuestas });
      refetchHistory();
    } catch (caught) {
      setError(toError(caught, "No se pudieron generar las propuestas"));
    } finally {
      setBusy(false);
    }
  }

  const regenerate = useCallback(
    async (proposalId: string, changes: RegenerationChanges) => {
      const proposal = await regenerateProposal(proposalId, { data_mode: mode, ...changes });
      setLot((prev) => (prev && prev.batchId === proposal.lote_id ? { ...prev, proposals: [...prev.proposals, proposal] } : prev));
      refetchHistory();
    },
    [mode, refetchHistory],
  );

  async function open(batchId: string) {
    setError(null);
    try {
      const loaded = await loadBatch(mode, batchId);
      if (loaded.proposals.length) setLot({ batchId, context: loaded.context, proposals: loaded.proposals });
    } catch (caught) {
      setError(toError(caught, "No se pudo abrir el lote"));
    }
  }

  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="page-title">Laboratorio creativo</h1>
          <p className="page-lede">
            Convierta lo que detecta DETECTAR en ideas de contenido para Latinoamérica: elija una brecha entre inglés y
            español o un tema, defina audiencia y plataforma, y obtenga tres propuestas (educativa, controversial y
            narrativa) que puede regenerar. Modo&nbsp;<ModeBadge mode={mode} />
          </p>
        </div>
        <QueryView query={options} skeletonLines={1}>
          {(data) => (
            <div className="row">
              <span className="small muted">Motor:</span>
              <EngineBadge engine={data.motor} />
              <InfoTip label="motor de generación">{data.motor.detalle}</InfoTip>
            </div>
          )}
        </QueryView>
      </header>

      <div className={styles.steps}>
        <section className="panel" aria-labelledby="paso-1">
          <div id="paso-1">
            <StepHead number={1} done={selection !== null} title="De qué partir">
              Una brecha (más atención en inglés que en español), un tema que detectó DETECTAR o un tema propio.
            </StepHead>
          </div>
          <StartPicker mode={mode} selected={selection} onSelect={setSelection} />
        </section>
        <QueryView query={options} skeletonLines={8}>
          {(data) => (
            <SettingsPanel
              options={data}
              selection={selection}
              settings={settings}
              onChange={(next) => setSettings((prev) => ({ ...prev, ...next }))}
              onClear={() => setSelection(null)}
              onGenerate={generate}
              busy={busy}
              error={error}
            />
          )}
        </QueryView>
      </div>

      {lot ? (
        <Board mode={mode} lot={lot} options={options.data} onRegenerate={regenerate} headingRef={headingRef} />
      ) : (
        <section className="panel" aria-labelledby="propuestas-vacio" style={{ marginBottom: 24 }}>
          <StepHead number={3} done={false} title="Propuestas" />
          <p id="propuestas-vacio" className="muted small">
            Aquí aparecerán las tres propuestas: <Badge tone="neutral" outline icon={null}>Educativa</Badge>{" "}
            <Badge tone="neutral" outline icon={null}>Controversial</Badge>{" "}
            <Badge tone="neutral" outline icon={null}>Narrativa</Badge>, con su estructura, el llamado a la acción, la
            adaptación a Latinoamérica y los datos de DETECTAR que usaron.
          </p>
        </section>
      )}

      <HistoryPanel mode={mode} currentBatch={lot?.batchId ?? null} onOpen={open} history={history} />
      <p className="faint small" style={{ marginTop: 16 }}>
        El laboratorio lee DETECTAR sin modificarlo y guarda las propuestas en la base de CREAR.
      </p>
    </>
  );
}
