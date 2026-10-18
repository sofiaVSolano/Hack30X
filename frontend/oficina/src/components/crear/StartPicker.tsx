"use client";

import { ChevronDown, ChevronRight, Languages, PenLine, Search, Tags } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { StageBadge } from "@/components/ui/Badges";
import { EmptyState, QueryView } from "@/components/ui/States";
import { Day } from "@/components/ui/Time";
import { useCrearTopics, useGaps } from "@/hooks/crear";
import { VERDICT } from "@/lib/crear/labels";
import { VERDICTS, type GapOut, type Verdict } from "@/lib/crear/schemas";
import type { DataMode, Stage } from "@/lib/schemas";

import { VerdictBadge } from "./CrearBadges";
import { GapEvidence } from "./GapEvidence";
import styles from "./Lab.module.css";

export type Selection =
  | { origen: "brecha" | "tema"; temaId: string; nombre: string; veredicto: Verdict | null; etapa: Stage | null }
  | { origen: "manual"; texto: string };

export function selectionName(selection: Selection): string {
  return selection.origen === "manual" ? selection.texto : selection.nombre;
}

type Tab = "brechas" | "temas" | "manual";

function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

function isSelected(selected: Selection | null, origin: "brecha" | "tema", topicId: string): boolean {
  return selected !== null && selected.origen === origin && selected.temaId === topicId;
}

function GapOption({ gap, selected, onSelect }: { gap: GapOut; selected: boolean; onSelect: () => void }) {
  const [open, setOpen] = useState(false);
  const evidenceId = useId();
  return (
    <li className={styles.option} data-selected={selected}>
      <div className={styles.optionHead}>
        <span className={styles.optionName}>{gap.tema_nombre}</span>
        <span className="row">
          <VerdictBadge verdict={gap.veredicto} />
          {gap.etapa ? <StageBadge stage={gap.etapa.etapa} /> : null}
        </span>
      </div>
      <p className={styles.optionSummary}>{gap.resumen}</p>
      <div className={styles.optionActions}>
        <button type="button" className="btn" aria-pressed={selected} onClick={onSelect}>
          {selected ? "Elegido" : "Crear a partir de esta brecha"}
        </button>
        <button type="button" className="btn btn--ghost" aria-expanded={open} aria-controls={evidenceId} onClick={() => setOpen((v) => !v)}>
          {open ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronRight size={15} aria-hidden="true" />}
          Ver la evidencia
        </button>
      </div>
      <div id={evidenceId} hidden={!open} style={{ marginTop: 12 }}>
        {open ? (
          <div className="stack">
            <GapEvidence comparisons={gap.comparaciones} />
            {gap.notas.length ? (
              <ul className="structured__list small muted">
                {gap.notas.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}

function GapsTab({ mode, selected, onSelect }: { mode: DataMode; selected: Selection | null; onSelect: (s: Selection) => void }) {
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const all = useGaps(mode);
  const counts = all.data?.por_veredicto ?? {};
  const items = all.data?.items.filter((g) => verdict === null || g.veredicto === verdict) ?? [];
  return (
    <QueryView query={all} skeletonLines={5}>
      {(page) =>
        page.fecha_referencia === null ? (
          <EmptyState title="DETECTAR todavía no tiene métricas en este modo">
            {mode === "simulated"
              ? "Prepare la demostración de DETECTAR y su complemento de CREAR (ver la guía del laboratorio)."
              : "Cuando DETECTAR recolecte y calcule métricas, aquí aparecerán las brechas. Mientras tanto, puede escribir un tema."}
          </EmptyState>
        ) : (
          <div className="stack">
            <p className="small muted">
              Compara la atención que recibe cada tema en inglés y en español con las métricas de DETECTAR al{" "}
              <Day value={page.fecha_referencia} />. Reglas <code>{page.version}</code>
              {page.calibrado ? "." : ", provisionales y sin calibrar."}
            </p>
            <div className={styles.chips} role="group" aria-label="Filtrar por veredicto">
              <button type="button" className={styles.chip} aria-pressed={verdict === null} onClick={() => setVerdict(null)}>
                Todas ({page.total})
              </button>
              {VERDICTS.map((v) => (
                <button
                  key={v}
                  type="button"
                  className={styles.chip}
                  aria-pressed={verdict === v}
                  disabled={!counts[v]}
                  onClick={() => setVerdict(v)}
                >
                  {VERDICT[v].text} ({counts[v] ?? 0})
                </button>
              ))}
            </div>
            {items.length ? (
              <ul className={styles.list} aria-label="Temas con su comparación inglés–español">
                {items.map((gap) => (
                  <GapOption
                    key={gap.tema_id}
                    gap={gap}
                    selected={isSelected(selected, "brecha", gap.tema_id)}
                    onSelect={() =>
                      onSelect({
                        origen: "brecha",
                        temaId: gap.tema_id,
                        nombre: gap.tema_nombre,
                        veredicto: gap.veredicto,
                        etapa: gap.etapa?.etapa ?? null,
                      })
                    }
                  />
                ))}
              </ul>
            ) : (
              <EmptyState title="Ningún tema con mediciones comparables">
                DETECTAR tiene métricas, pero ningún tema se midió a la vez en inglés y en español.
              </EmptyState>
            )}
            <details>
              <summary className="small muted">Qué significa cada veredicto y qué limita la comparación</summary>
              <ul className="structured__list small muted" style={{ marginTop: 8 }}>
                {VERDICTS.map((v) => (
                  <li key={v}>
                    <strong>{VERDICT[v].text}:</strong> {VERDICT[v].hint}
                  </li>
                ))}
                {page.limitaciones.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            </details>
          </div>
        )
      }
    </QueryView>
  );
}

function TopicsTab({ mode, selected, onSelect }: { mode: DataMode; selected: Selection | null; onSelect: (s: Selection) => void }) {
  const [text, setText] = useState("");
  const query = useDebounced(text.trim());
  const topics = useCrearTopics(mode, { q: query.length >= 2 ? query : undefined });
  return (
    <div className="stack">
      <label className="field">
        Buscar un tema de DETECTAR
        <span className="row" style={{ position: "relative" }}>
          <Search size={16} aria-hidden="true" style={{ position: "absolute", left: 10, color: "var(--text-faint)" }} />
          <input
            className="input"
            type="search"
            value={text}
            maxLength={100}
            autoComplete="off"
            placeholder="Al menos 2 caracteres"
            onChange={(e) => setText(e.target.value)}
            style={{ paddingLeft: 32, width: "100%" }}
          />
        </span>
      </label>
      <QueryView query={topics} skeletonLines={4}>
        {(page) =>
          page.items.length ? (
            <ul className={styles.list} aria-label="Temas detectados">
              {page.items.map((topic) => {
                const chosen = isSelected(selected, "tema", topic.id);
                return (
                  <li key={topic.id} className={styles.option} data-selected={chosen}>
                    <div className={styles.optionHead}>
                      <span className={styles.optionName}>{topic.nombre}</span>
                      <span className="row">
                        {topic.veredicto_brecha ? <VerdictBadge verdict={topic.veredicto_brecha} /> : null}
                        {topic.etapa ? <StageBadge stage={topic.etapa.etapa} /> : null}
                      </span>
                    </div>
                    <div className={styles.optionActions}>
                      <button
                        type="button"
                        className="btn"
                        aria-pressed={chosen}
                        onClick={() =>
                          onSelect({
                            origen: "tema",
                            temaId: topic.id,
                            nombre: topic.nombre,
                            veredicto: topic.veredicto_brecha,
                            etapa: topic.etapa?.etapa ?? null,
                          })
                        }
                      >
                        {chosen ? "Elegido" : "Crear a partir de este tema"}
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState title={query.length >= 2 ? "Ningún tema coincide" : "Sin temas en este modo"}>
              {query.length >= 2 ? `Sin resultados para «${query}».` : "DETECTAR todavía no tiene temas normalizados en este modo."}
            </EmptyState>
          )
        }
      </QueryView>
    </div>
  );
}

function ManualTab({ selected, onSelect }: { selected: Selection | null; onSelect: (s: Selection) => void }) {
  const [text, setText] = useState(selected?.origen === "manual" ? selected.texto : "");
  const clean = text.replace(/\s+/g, " ").trim();
  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        if (clean.length >= 2) onSelect({ origen: "manual", texto: clean });
      }}
    >
      <label className="field">
        Tema o tendencia
        <input
          className="input"
          value={text}
          minLength={2}
          maxLength={120}
          placeholder="Por ejemplo, ahorro para el primer empleo"
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <p className="small muted">
        Sin datos de DETECTAR: las propuestas no citarán cifras ni afirmarán que el tema es tendencia.
      </p>
      <div>
        <button type="submit" className="btn" disabled={clean.length < 2}>
          Usar este tema
        </button>
      </div>
    </form>
  );
}

const TABS: { id: Tab; label: string; icon: typeof Languages }[] = [
  { id: "brechas", label: "Brechas inglés–español", icon: Languages },
  { id: "temas", label: "Temas detectados", icon: Tags },
  { id: "manual", label: "Escribir un tema", icon: PenLine },
];

export function StartPicker({
  mode,
  selected,
  onSelect,
}: {
  mode: DataMode;
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
}) {
  const [tab, setTab] = useState<Tab>("brechas");
  const baseId = useId();
  return (
    <div>
      <div className={styles.tabs} role="tablist" aria-label="Punto de partida">
        {TABS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              id={`${baseId}-${item.id}`}
              type="button"
              role="tab"
              className="btn"
              aria-selected={tab === item.id}
              aria-controls={`${baseId}-${item.id}-panel`}
              onClick={() => setTab(item.id)}
            >
              <Icon size={15} aria-hidden="true" />
              {item.label}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" id={`${baseId}-${tab}-panel`} aria-labelledby={`${baseId}-${tab}`}>
        {tab === "brechas" ? <GapsTab mode={mode} selected={selected} onSelect={onSelect} /> : null}
        {tab === "temas" ? <TopicsTab mode={mode} selected={selected} onSelect={onSelect} /> : null}
        {tab === "manual" ? <ManualTab selected={selected} onSelect={onSelect} /> : null}
      </div>
    </div>
  );
}
