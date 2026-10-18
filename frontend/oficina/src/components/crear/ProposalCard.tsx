"use client";

import {
  BookOpen,
  ClipboardCheck,
  ClipboardCopy,
  GraduationCap,
  Info,
  MessagesSquare,
  RefreshCw,
  TriangleAlert,
  WandSparkles,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useId, useState, type FormEvent } from "react";

import { ErrorNotice } from "@/components/ui/States";
import { Time } from "@/components/ui/Time";
import type { RegenerationRequest } from "@/hooks/crear";
import { OficinaError } from "@/lib/api-client";
import { APPROACH, CHANGE } from "@/lib/crear/labels";
import { APPROACHES, type Approach, type CrearOptions, type ProposalOut } from "@/lib/crear/schemas";

import { EngineBadge } from "./CrearBadges";
import styles from "./Lab.module.css";

const APPROACH_ICON: Record<Approach, LucideIcon> = {
  educativo: GraduationCap,
  controversial: MessagesSquare,
  narrativo: BookOpen,
};

export type RegenerationChanges = Omit<RegenerationRequest, "data_mode">;

function nameOf(list: { id: string; nombre: string }[] | undefined, id: string | null): string {
  if (id === null) return "Toda Latinoamérica";
  return list?.find((item) => item.id === id)?.nombre ?? id;
}

/** Texto plano de la propuesta, listo para pegar en un guion o documento. */
export function proposalText(p: ProposalOut, options?: CrearOptions): string {
  const c = p.contenido;
  return [
    c.titulo,
    `Enfoque: ${APPROACH[p.enfoque]}. Plataforma: ${nameOf(options?.plataformas, p.plataforma)}. Audiencia: ${nameOf(options?.audiencias, p.audiencia)}. País: ${nameOf(options?.paises, p.pais)}.`,
    "",
    `Gancho: ${c.gancho}`,
    `Idea central: ${c.idea_central}`,
    "",
    "Estructura:",
    ...c.estructura.map((step, i) => `${i + 1}. ${step}`),
    "",
    `Formato: ${c.formato}`,
    `Llamado a la acción: ${c.llamado_a_la_accion}`,
    "",
    "Adaptación a Latinoamérica:",
    ...c.adaptacion_latam.map((item) => `- ${item}`),
    "",
    `Palabras clave: ${c.palabras_clave.join(", ")}`,
    "",
    "Precauciones:",
    ...c.precauciones.map((item) => `- ${item}`),
  ].join("\n");
}

function RegenerateForm({
  current,
  options,
  onSubmit,
  onCancel,
}: {
  current: ProposalOut;
  options: CrearOptions | undefined;
  onSubmit: (changes: RegenerationChanges) => Promise<void>;
  onCancel: () => void;
}) {
  const [approach, setApproach] = useState<Approach>(current.enfoque);
  const [audience, setAudience] = useState(current.audiencia);
  const [detail, setDetail] = useState(current.audiencia_detalle ?? "");
  const [platform, setPlatform] = useState(current.plataforma);
  const [country, setCountry] = useState(current.pais ?? "");
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<OficinaError | null>(null);
  const formId = useId();

  async function submit(event: FormEvent) {
    event.preventDefault();
    // Solo se envía lo que cambió: el resto se conserva de la versión actual.
    const changes: RegenerationChanges = {};
    if (approach !== current.enfoque) changes.enfoque = approach;
    if (audience !== current.audiencia) changes.audiencia = audience;
    if ((detail.trim() || null) !== current.audiencia_detalle) changes.audiencia_detalle = detail.trim() || null;
    if (platform !== current.plataforma) changes.plataforma = platform;
    if ((country || null) !== current.pais) changes.pais = country || null;
    if (instruction.trim()) changes.indicacion = instruction.trim();
    setBusy(true);
    setError(null);
    try {
      await onSubmit(changes);
    } catch (caught) {
      setError(caught instanceof OficinaError ? caught : new OficinaError("invalid", "No se pudo crear la versión"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={styles.regenerate} onSubmit={submit} aria-busy={busy} aria-labelledby={`${formId}-title`}>
      <p id={`${formId}-title`} className={styles.blockLabel}>
        Nueva versión: cambie el ángulo, la audiencia o la plataforma
      </p>
      <div className={styles.formRow}>
        <label className="field">
          Enfoque
          <select className="select" value={approach} onChange={(e) => setApproach(e.target.value as Approach)}>
            {APPROACHES.map((a) => (
              <option key={a} value={a}>
                {APPROACH[a]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Plataforma
          <select className="select" value={platform} onChange={(e) => setPlatform(e.target.value)}>
            {(options?.plataformas ?? [{ id: current.plataforma, nombre: current.plataforma }]).map((p) => (
              <option key={p.id} value={p.id}>
                {p.nombre}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Audiencia
          <select className="select" value={audience} onChange={(e) => setAudience(e.target.value)}>
            {(options?.audiencias ?? [{ id: current.audiencia, nombre: current.audiencia }]).map((a) => (
              <option key={a.id} value={a.id}>
                {a.nombre}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          País
          <select className="select" value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="">Toda Latinoamérica</option>
            {(options?.paises ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.nombre}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="field">
        Detalle de la audiencia (opcional)
        <input className="input" value={detail} maxLength={200} onChange={(e) => setDetail(e.target.value)} />
      </label>
      <label className="field">
        Indicación libre (opcional)
        <input
          className="input"
          value={instruction}
          maxLength={300}
          placeholder="Por ejemplo, más humor o un cierre con pregunta"
          onChange={(e) => setInstruction(e.target.value)}
        />
      </label>
      {error ? <ErrorNotice error={error} /> : null}
      <div className="row">
        <button type="submit" className="btn" disabled={busy}>
          <RefreshCw size={15} aria-hidden="true" className={busy ? "spin" : undefined} />
          {busy ? "Creando versión…" : "Crear versión nueva"}
        </button>
        <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={busy}>
          Cancelar
        </button>
      </div>
    </form>
  );
}

export function ProposalCard({
  versions,
  options,
  onRegenerate,
}: {
  /** Todas las versiones de una propuesta, de la primera a la última. */
  versions: ProposalOut[];
  options: CrearOptions | undefined;
  onRegenerate: (proposalId: string, changes: RegenerationChanges) => Promise<void>;
}) {
  const latest = versions[versions.length - 1];
  const [currentId, setCurrentId] = useState(latest?.id);
  const [editing, setEditing] = useState(false);
  const [copied, setCopied] = useState(false);
  const titleId = useId();

  // Una versión nueva se muestra en cuanto llega.
  useEffect(() => {
    setCurrentId(latest?.id);
  }, [latest?.id]);

  const current = versions.find((v) => v.id === currentId) ?? latest;
  if (!current) return null;
  const c = current.contenido;
  const Icon = APPROACH_ICON[current.enfoque];

  async function copy() {
    if (!current) return;
    try {
      await navigator.clipboard.writeText(proposalText(current, options));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <article className={`panel ${styles.card}`} aria-labelledby={titleId}>
      <div className={styles.cardHead}>
        <span className={styles.approach}>
          <Icon size={17} aria-hidden="true" />
          {APPROACH[current.enfoque]}
        </span>
        <EngineBadge engine={current.motor} model={current.modelo} />
      </div>
      {versions.length > 1 ? (
        <div className={styles.versions} role="group" aria-label="Versiones de la propuesta">
          {versions.map((v) => (
            <button
              key={v.id}
              type="button"
              className="btn btn--ghost"
              aria-pressed={v.id === current.id}
              onClick={() => setCurrentId(v.id)}
            >
              Versión {v.version}
            </button>
          ))}
        </div>
      ) : null}
      <p className="small muted">
        Plataforma: <strong>{nameOf(options?.plataformas, current.plataforma)}</strong>. Audiencia:{" "}
        <strong>{nameOf(options?.audiencias, current.audiencia)}</strong>. País: <strong>{nameOf(options?.paises, current.pais)}</strong>.
        {current.audiencia_detalle ? <> Detalle: {current.audiencia_detalle}.</> : null}
        {current.version > 1 && current.cambios.length ? (
          <> Cambios frente a la versión anterior: {current.cambios.map((x) => CHANGE[x] ?? x).join(", ")}.</>
        ) : null}
      </p>
      <h3 id={titleId} className={styles.cardTitle}>
        {c.titulo}
      </h3>
      <blockquote className={styles.hook} aria-label="Gancho">
        {c.gancho}
      </blockquote>
      <p style={{ fontSize: 14 }}>{c.idea_central}</p>

      {current.cifras_sin_respaldo.length ? (
        <div className="notice notice--warn small" role="note">
          <TriangleAlert size={16} aria-hidden="true" color="var(--warn)" />
          <p>
            <strong>Cifras sin respaldo en DETECTAR:</strong> {current.cifras_sin_respaldo.join(", ")}. Verifícalas con una
            fuente o quítalas antes de publicar.
          </p>
        </div>
      ) : null}
      {current.aviso_motor ? (
        <div className="notice notice--info small" role="note">
          <Info size={16} aria-hidden="true" color="var(--info)" />
          <p>{current.aviso_motor}</p>
        </div>
      ) : null}

      <div className={styles.block}>
        <span className={styles.blockLabel}>Estructura</span>
        <ol>
          {c.estructura.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </div>
      <div className={styles.block}>
        <span className={styles.blockLabel}>Formato</span>
        <p>{c.formato}</p>
      </div>
      <div className={styles.block}>
        <span className={styles.blockLabel}>Llamado a la acción</span>
        <p>{c.llamado_a_la_accion}</p>
      </div>
      <div className={styles.block}>
        <span className={styles.blockLabel}>Adaptación a Latinoamérica</span>
        <ul>
          {c.adaptacion_latam.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
      <div className={styles.block}>
        <span className={styles.blockLabel}>Palabras clave</span>
        <ul className={styles.keywords}>
          {c.palabras_clave.map((word) => (
            <li key={word}>
              <span className="badge badge--outline">{word}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className={styles.block}>
        <span className={styles.blockLabel}>Precauciones</span>
        <ul className={styles.cautions}>
          {c.precauciones.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
      <p className="faint small">
        Versión {current.version} creada <Time value={current.creado} />.
      </p>

      {editing ? (
        <RegenerateForm
          current={current}
          options={options}
          onCancel={() => setEditing(false)}
          onSubmit={async (changes) => {
            await onRegenerate(current.id, changes);
            setEditing(false);
          }}
        />
      ) : (
        <div className={styles.cardActions}>
          <button type="button" className="btn" onClick={() => setEditing(true)}>
            <WandSparkles size={15} aria-hidden="true" />
            Regenerar con otro enfoque
          </button>
          <button type="button" className="btn btn--ghost" onClick={copy}>
            {copied ? <ClipboardCheck size={15} aria-hidden="true" /> : <ClipboardCopy size={15} aria-hidden="true" />}
            {copied ? "Copiada" : "Copiar texto"}
          </button>
          <span className="visually-hidden" aria-live="polite">
            {copied ? "Propuesta copiada al portapapeles" : ""}
          </span>
        </div>
      )}
    </article>
  );
}
