"use client";

import { ArrowRight, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Desk } from "@/components/agents/Desk";
import { BrandMark } from "@/components/shell/BrandMark";
import { StageBadge } from "@/components/ui/Badges";
import { useAgents, useClassifications, useMetrics, useStageRules, useTopics } from "@/hooks/queries";
import { ACTIVITY } from "@/lib/labels";
import { displayName, plainReason, plainSources, STAGE_PLAIN } from "@/lib/plain";
import type { Classification, Stage } from "@/lib/schemas";

import styles from "./LandingView.module.css";

/**
 * Portada de DETECTAR, pensada para el jurado de HACK 30X: la programación de tendencias del día
 * como una guía de TV impresa. Todo lo que cambia (temas, etapas, umbrales, agentes) sale de la API
 * en modo real; si no hay datos, se dice, nunca se rellena.
 */

const ORDER: Stage[] = ["acelerando", "emergente", "punto_maximo", "saturada", "datos_insuficientes"];
const percent = new Intl.NumberFormat("es", { style: "percent", maximumFractionDigits: 0 });
const longDay = new Intl.DateTimeFormat("es", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });

function day(value?: string) {
  return value ? longDay.format(new Date(`${value}T00:00:00Z`)) : "";
}

function num(params: unknown, key: string): number | null {
  const v = (params as Record<string, unknown> | null)?.[key];
  return typeof v === "number" ? v : null;
}

/** La misma regla que la página Tendencias: si a la fecha más reciente le faltan días de Wikipedia, se usa la anterior. */
function useProgramme() {
  const latest = useClassifications("real", { limite: 100 });
  const dates = [...new Set((latest.data?.items ?? []).map((i) => i.fecha_referencia))].sort().reverse();
  const growth = useMetrics("real", { metrica: "wiki_views_growth", fecha_referencia: dates[0], limite: 200 }, dates[0] !== undefined);
  const missing = (growth.data?.items ?? []).filter((m) => (m.motivo ?? "").startsWith("current_missing_days")).length;
  const incomplete = growth.data !== undefined && growth.data.items.length > 0 && missing / growth.data.items.length >= 0.5;
  const asOf = growth.data === undefined ? undefined : incomplete && dates[1] ? dates[1] : dates[0];
  const list = useClassifications("real", { fecha_referencia: asOf, limite: 100 }, asOf !== undefined);
  const items = [...(list.data?.items ?? [])].sort((a, b) => ORDER.indexOf(a.etapa) - ORDER.indexOf(b.etapa));
  const loading = latest.loading || (dates.length > 0 && list.data === undefined && !list.error);
  return { asOf, items, loading, failed: Boolean(latest.error || list.error), empty: latest.data !== undefined && dates.length === 0 };
}

function Board({ items, names, sources }: { items: Classification[]; names: Map<string, string>; sources: Map<string, string> }) {
  const staged = items.filter((i) => i.etapa !== "datos_insuficientes" && i.etapa !== "saturada");
  const rows = (staged.length >= 5 ? staged : [...staged, ...items.filter((i) => !staged.includes(i))]).slice(0, 8);
  const [open, setOpen] = useState(0);
  return (
    <ol className={styles.board} data-ui="parrilla">
      {rows.map((item, index) => {
        const name = displayName(names.get(item.tema_id) ?? item.tema_id);
        const isOpen = index === open;
        const plain = item.etapa === "datos_insuficientes" ? plainReason(item) : STAGE_PLAIN[item.etapa].sentence;
        return (
          <li key={item.id} className={styles.row} data-open={isOpen} data-stage={item.etapa}>
            <button type="button" className={styles.rowButton} aria-expanded={isOpen} onClick={() => setOpen(index)}>
              <span className={styles.rowName}>{name}</span>
              <span className={styles.rowStage}>
                <StageBadge stage={item.etapa} />
              </span>
            </button>
            {isOpen ? (
              <div className={styles.rowDetail}>
                <p className={styles.rowSentence}>{plain}</p>
                <p className={styles.rowMeta}>{sources.get(item.tema_id) ? `Visto en ${sources.get(item.tema_id)}.` : null}</p>
                <Link className={styles.rowLink} href={`/clasificaciones?tema_id=${encodeURIComponent(item.tema_id)}`}>
                  Ver la evidencia <ArrowUpRight size={18} aria-hidden="true" />
                </Link>
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

export function LandingView() {
  const programme = useProgramme();
  const topics = useTopics("real", { limite: 100 });
  const rules = useStageRules();
  const agents = useAgents("real");

  const names = useMemo(() => new Map((topics.data?.items ?? []).map((t) => [t.id, t.nombre])), [topics.data]);
  const sources = useMemo(
    () => new Map((topics.data?.items ?? []).map((t) => [t.id, plainSources(t.vinculos_por_fuente)])),
    [topics.data],
  );
  const counts = useMemo(() => {
    const c: Partial<Record<Stage, number>> = {};
    for (const i of programme.items) c[i.etapa] = (c[i.etapa] ?? 0) + 1;
    return c;
  }, [programme.items]);
  const params = rules.data?.parametros;
  const growthMin = num(params, "growth_min");
  const accelMin = num(params, "acceleration_min");
  const flat = num(params, "flat_band");
  const windowDays = num(params, "window_days");
  const onAir = programme.items
    .filter((i) => i.etapa === "acelerando" || i.etapa === "emergente" || i.etapa === "punto_maximo")
    .slice(0, 3)
    .map((i) => displayName(names.get(i.tema_id) ?? ""))
    .filter(Boolean);
  const agentList = agents.data?.agentes ?? [];
  const withTask = agentList.filter((a) => a.implementado).length;

  return (
    <div className={styles.page}>
      <a className={styles.skip} href="#contenido">
        Saltar al contenido
      </a>

      <header className={styles.masthead}>
        <div className={styles.nameBand}>
          <Link href="/" className={styles.mark} aria-label="HACK 30X DETECTAR, inicio">
            <BrandMark size={44} inverse />
          </Link>
          <p className={styles.name} aria-hidden="true">
            DETECTAR
          </p>
          <p className={styles.edition}>
            {programme.asOf ? (
              <>
                Programación del <strong>{day(programme.asOf)}</strong>
              </>
            ) : (
              "HACK 30X"
            )}
          </p>
        </div>
        <nav className={styles.linkTiles} aria-label="Secciones de la portada">
          <a href="#parrilla">La parrilla de hoy</a>
          <a href="#como">Cómo decide</a>
          <a href="#reglas">Las reglas</a>
          <a href="#agentes">Los agentes</a>
        </nav>
      </header>

      <main id="contenido">
        <section className={styles.hero} aria-labelledby="titular">
          <div className={styles.leftRail}>
            <figure className={styles.portrait}>
              <img src="/landing/oficina.png" width={2256} height={960} alt="Plano de la oficina de agentes de DETECTAR con sus seis puestos." />
            </figure>
            <ul className={styles.facts}>
              <li>
                <strong>8</strong> países de América Latina
              </li>
              <li>
                <strong>2</strong> fuentes públicas: Google Trends y Wikipedia
              </li>
              <li>
                <strong>45</strong> días de visitas por tema
              </li>
              <li>
                <strong>{agentList.length || 6}</strong> agentes, {withTask || 2} con tarea
              </li>
              <li>
                <strong>1</strong> parrilla nueva cada día
              </li>
            </ul>
          </div>

          <div className={styles.centre}>
            <figure className={styles.shutter}>
              <img src="/landing/tendencias.png" width={2384} height={2818} alt="Página Tendencias de la oficina con los temas agrupados por etapa." />
            </figure>
            <div className={styles.statement}>
              <h1 id="titular" className={styles.headline}>
                Tendencias, antes de que se gasten
              </h1>
              <p>Qué temas crecen en América Latina y en qué momento está cada uno, con la evidencia a la vista.</p>
              {onAir.length ? (
                <p className={styles.onAir}>
                  En emisión: <strong>{onAir.join(", ")}</strong>
                </p>
              ) : null}
            </div>
          </div>

          <div className={styles.rightRail} aria-live="polite">
            <p className={styles.tile} data-tone="1">
              <strong>{programme.loading ? "…" : programme.items.length}</strong> temas clasificados
            </p>
            <p className={styles.tile} data-tone="2">
              <strong>{programme.loading ? "…" : (counts.acelerando ?? 0)}</strong> creciendo cada vez más rápido
            </p>
            <p className={styles.tile} data-tone="3">
              <strong>{programme.loading ? "…" : (counts.emergente ?? 0)}</strong> empezando a crecer
            </p>
            <p className={styles.tile} data-tone="4">
              <strong>{programme.loading ? "…" : (counts.punto_maximo ?? 0)}</strong> en su punto más alto
            </p>
            <Link className={styles.actionTile} href="/tendencias">
              <span>Abrir la oficina</span>
              <ArrowRight size={28} aria-hidden="true" />
            </Link>
          </div>
        </section>

        <section id="parrilla" className={styles.showcase} aria-labelledby="t-parrilla">
          <div className={styles.showcaseHead}>
            <h2 id="t-parrilla" className={styles.sectionTitle}>
              La parrilla de hoy
            </h2>
            <p className={styles.lede}>
              Datos reales hasta el {programme.asOf ? day(programme.asOf) : "último día completo"}. Elija una fila para ver por qué
              está en esa etapa.
            </p>
          </div>
          {programme.failed ? (
            <p className={styles.boardNote}>
              No se pudo leer la parrilla. Compruebe que el backend está en marcha (<code>npm run backend</code>).
            </p>
          ) : programme.empty ? (
            <p className={styles.boardNote}>
              Todavía no hay tendencias calculadas. Ejecute <code>npm run tendencias:actualizar</code>.
            </p>
          ) : programme.loading ? (
            <p className={styles.boardNote}>Cargando la parrilla…</p>
          ) : (
            <Board items={programme.items} names={names} sources={sources} />
          )}
        </section>

        <section id="como" className={styles.how} aria-labelledby="t-como">
          <h2 id="t-como" className={styles.bigTitle}>
            Cómo decide
          </h2>
          <ol className={styles.stagesBar}>
            <li style={{ flexGrow: 1 }} data-tone="1">
              <strong>Google Trends</strong>
              <span>Lo que se busca hoy en 8 países. Segundos.</span>
            </li>
            <li style={{ flexGrow: 2 }} data-tone="2">
              <strong>Wikipedia</strong>
              <span>45 días de visitas de cada tema. Un minuto.</span>
            </li>
            <li style={{ flexGrow: 5 }} data-tone="3">
              <strong>Espera</strong>
              <span>Wikipedia cierra cada día con uno o dos de retraso: se clasifica el último día completo.</span>
            </li>
            <li style={{ flexGrow: 1.4 }} data-tone="4">
              <strong>Etapa</strong>
              <span>Mide y clasifica. Segundos.</span>
            </li>
          </ol>
        </section>

        <section id="reglas" className={styles.rules} aria-labelledby="t-reglas">
          <h2 id="t-reglas" className={styles.giantWord}>
            Reglas
          </h2>
          <div className={styles.bars}>
            <details open>
              <summary>Creciendo cada vez más rápido</summary>
              <p>
                {growthMin !== null && accelMin !== null && windowDays !== null
                  ? `Las visitas de ${windowDays} días suben al menos un ${percent.format(growthMin)} y ese crecimiento aumenta al menos ${percent.format(accelMin)} frente a la ventana anterior.`
                  : "Crecimiento y aumento de ese crecimiento en tres ventanas comparables."}
              </p>
            </details>
            <details>
              <summary>Empezando a crecer</summary>
              <p>{rules.data?.etapas.emergente ?? "Señales recientes de crecimiento, sin aceleración demostrada."}</p>
            </details>
            <details>
              <summary>En su punto más alto</summary>
              <p>
                {flat !== null
                  ? `Subió en la ventana anterior y ahora se mueve menos de un ${percent.format(flat)}: una meseta. No anticipa la caída.`
                  : rules.data?.etapas.punto_maximo}
              </p>
            </details>
            <details>
              <summary>Lo que todavía no sabe</summary>
              <p>
                No mide saturación, oportunidad ni confianza. Las reglas {rules.data?.version ?? "stages-v1"} son{" "}
                {rules.data?.calibrado ? "calibradas" : "provisionales, sin calibrar con datos reales"}. Si encaja con su audiencia lo
                decide el módulo ENTENDER.
              </p>
            </details>
          </div>
        </section>

        <section id="agentes" className={styles.agents} aria-labelledby="t-agentes">
          <h2 id="t-agentes" className={styles.sectionTitle}>
            Los agentes de la oficina
          </h2>
          {agentList.length ? (
            <ul className={styles.agentTiles}>
              {agentList.map((agent, index) => (
                <li key={agent.id} data-tone={(index % 4) + 1}>
                  <Link href="/oficina" className={styles.agentTile} aria-label={`${agent.nombre}: ${ACTIVITY[agent.actividad].text}. Abrir la oficina`}>
                    <span className={styles.agentArt}>
                      <Desk who={agent.id} activity={agent.actividad} implemented={agent.implementado} size={140} />
                    </span>
                    <strong>{agent.nombre}</strong>
                    <span>{agent.implementado ? ACTIVITY[agent.actividad].text : "Puesto sin tarea todavía"}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.boardNote}>{agents.error ? "No se pudo leer la lista de agentes." : "Cargando los agentes…"}</p>
          )}
        </section>

        <section className={styles.cta} aria-labelledby="t-cta">
          <figure className={styles.ctaImage}>
            <img src="/landing/evidencia.png" width={2256} height={1048} alt="Evidencia de una clasificación: reglas aplicadas a las visitas de Wikipedia." />
          </figure>
          <div className={styles.ctaTile}>
            <h2 id="t-cta">Cada etapa trae su evidencia</h2>
            <p>Abra la oficina y siga cualquier tema hasta los datos que lo clasificaron.</p>
            <Link className={styles.ctaButton} href="/tendencias">
              Abrir la oficina <ArrowRight size={20} aria-hidden="true" />
            </Link>
          </div>
          <figure className={styles.ctaSide}>
            <img src="/landing/serie.png" width={2156} height={990} alt="Serie diaria de visitas en Wikipedia de un tema que se acelera." />
          </figure>
        </section>
      </main>

      <footer className={styles.footer}>
        <p className={styles.blocks} role="img" aria-label="HACK 30X">
          {["H", "A", "C", "K", "3", "0", "X"].map((letter, i) => (
            <span key={i} data-tone={(i % 4) + 1} aria-hidden="true">
              {letter}
            </span>
          ))}
        </p>
        <div className={styles.columns}>
          <nav aria-label="La oficina">
            <h2>La oficina</h2>
            <Link href="/tendencias">Tendencias</Link>
            <Link href="/oficina">Oficina de agentes</Link>
            <Link href="/clasificaciones">Evidencias</Link>
            <Link href="/metricas">Métricas</Link>
          </nav>
          <div>
            <h2>La cadena</h2>
            <p>DETECTAR encuentra el tema y su momento. ENTENDER decide si encaja con su audiencia. CREAR propone la pieza. VALIDAR la comprueba.</p>
          </div>
          <div>
            <h2>Los datos</h2>
            <p>Google Trends (RSS diario por país) y vistas diarias de Wikipedia. Datos públicos; nada se inventa.</p>
          </div>
        </div>
        <p className={styles.legal}>
          <span>HACK 30X · DETECTAR · Uso local, solo lectura</span>
          <a href="#contenido" className={styles.toTop}>
            Volver arriba
          </a>
        </p>
      </footer>
    </div>
  );
}
