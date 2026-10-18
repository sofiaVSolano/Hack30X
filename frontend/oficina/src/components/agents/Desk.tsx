import type { Activity } from "@/lib/schemas";

import styles from "./Desk.module.css";

const SKIN = ["#f1c7a0", "#c98d5e", "#8d5a3b", "#e0a979", "#a86b45"];
const HAIR = ["#16130f", "#5a3a22", "#8a5a2b", "#2a2620", "#b5a98f"];
const SHIRT = ["#d21f2b", "#1f56b3", "#f2c230", "#136136", "#6a3fa3", "#e07a1f"];
// Camiseta fija para los agentes conocidos, para que no coincidan; el resto, por su identificador.
const SHIRT_OF: Record<string, string> = {
  trend_hunter: "#d21f2b",
  format_hunter: "#e07a1f",
  analyst: "#136136",
  audience_filter: "#6a3fa3",
  strategist: "#f2c230",
  supervisor: "#1f56b3",
};
const PANTS = ["#2a2620", "#24324f", "#4a443a"];

/** Aspecto estable por agente (mismo identificador, misma persona); solo es ilustración. */
function look(who: string) {
  let h = 0;
  for (const c of who) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return {
    skin: SKIN[h % SKIN.length]!,
    hair: HAIR[(h >>> 3) % HAIR.length]!,
    shirt: SHIRT_OF[who] ?? SHIRT[(h >>> 6) % SHIRT.length]!,
    pants: PANTS[(h >>> 9) % PANTS.length]!,
    longHair: ((h >>> 12) & 1) === 1,
  };
}

/**
 * Una personita sentada en su silla, de perfil, trabajando en su escritorio. Nada se superpone a la
 * pantalla: el cartel «al aire» va en la pared, encima del monitor.
 *
 * Todo lo que cambia sale de la API:
 * - `implemented = false` → silla vacía y monitor apagado (rol sin tarea);
 * - `activity` pendiente/en_curso → teclea, la pantalla se enciende y la luz «al aire» se pone en
 *   rojo: es el ÚNICO estado con movimiento, y se detiene con prefers-reduced-motion;
 * - completada/fallida/bloqueada → descansa con las manos en las piernas y la pantalla muestra el
 *   símbolo del último resultado;
 * - sin_ejecuciones → descansa con la pantalla en espera.
 */
export function Desk({
  activity,
  implemented,
  size = 170,
  who = "",
}: {
  activity: Activity;
  implemented: boolean;
  size?: number;
  who?: string;
}) {
  const working = implemented && (activity === "pendiente" || activity === "en_curso");
  const state = !implemented ? "vacante" : working ? "trabajando" : activity;
  const p = look(who);
  return (
    <svg
      className={styles.desk}
      data-state={state}
      viewBox="0 0 176 124"
      width={size}
      height={(size * 124) / 176}
      aria-hidden="true"
      focusable="false"
    >
      {/* Luz «al aire» en la pared, sobre el monitor */}
      <g className={styles.onAir}>
        <rect x="104" y="2" width="40" height="13" rx="2" />
        <text x="124" y="11.5" textAnchor="middle">
          AL AIRE
        </text>
      </g>

      {/* Monitor, de frente */}
      <rect className={styles.monitor} x="96" y="24" width="56" height="38" rx="3" />
      <rect className={styles.screen} x="100" y="28" width="48" height="30" rx="1.5" />
      {state === "trabajando" ? (
        <g className={styles.code}>
          <rect className={styles.line} x="105" y="34" width="26" height="3" rx="1.5" />
          <rect className={styles.line} x="105" y="41" width="34" height="3" rx="1.5" />
          <rect className={styles.line} x="105" y="48" width="20" height="3" rx="1.5" />
        </g>
      ) : null}
      {state === "completada" ? <path className={styles.glyph} data-tone="ok" d="M116 43 l6 6 l12 -12" /> : null}
      {state === "fallida" ? <path className={styles.glyph} data-tone="danger" d="M117 36 l14 14 M131 36 l-14 14" /> : null}
      {state === "bloqueada" ? (
        <g className={styles.glyph} data-tone="warn">
          <circle cx="124" cy="43" r="8" />
          <path d="M118.5 48.5 l11 -11" />
        </g>
      ) : null}
      {state === "sin_ejecuciones" ? <circle className={styles.standby} cx="124" cy="43" r="2.4" /> : null}
      <rect className={styles.stand} x="120" y="62" width="8" height="7" />
      <rect className={styles.stand} x="112" y="68" width="24" height="4" rx="1" />

      {/* Escritorio con teclado y taza */}
      <rect className={styles.keyboard} x="70" y="68" width="30" height="4" rx="1" />
      <rect className={styles.mug} x="140" y="63" width="8" height="9" rx="1.5" />
      <rect className={styles.table} x="58" y="72" width="112" height="6" rx="1.5" />
      <rect className={styles.leg} x="62" y="78" width="4" height="42" />
      <rect className={styles.leg} x="162" y="78" width="4" height="42" />
      <rect className={styles.floor} x="0" y="120" width="176" height="2" />

      {/* Silla de oficina */}
      <g className={styles.chair}>
        <rect x="6" y="50" width="7" height="40" rx="3" />
        <rect x="6" y="86" width="42" height="6" rx="3" />
        <rect x="25" y="92" width="5" height="16" />
        <rect x="11" y="108" width="34" height="4" rx="2" />
        <circle cx="14" cy="116" r="3" />
        <circle cx="42" cy="116" r="3" />
      </g>

      {/* La personita, sentada de perfil mirando su monitor */}
      {implemented ? (
        <g className={styles.person}>
          {p.longHair ? <rect x="17" y="32" width="9" height="20" rx="4.5" fill={p.hair} /> : null}
          <rect className={styles.torso} x="16" y="50" width="22" height="40" rx="10" fill={p.shirt} />
          <rect x="24" y="82" width="36" height="10" rx="5" fill={p.pants} />
          <rect x="52" y="84" width="9" height="29" rx="4" fill={p.pants} />
          <rect x="50" y="111" width="18" height="6" rx="3" className={styles.shoe} />
          <circle className={styles.head} cx="30" cy="36" r="12" fill={p.skin} />
          <path d="M18.4 38 A12 12 0 0 1 41.6 32.5 Q33 30 29 34 Q24 39 18.4 38 Z" fill={p.hair} />
          <circle className={styles.eye} cx="37" cy="37" r="1.5" />
          {working ? (
            <g className={styles.armsWork}>
              <path d="M28 58 L44 74 L69 70" stroke={p.shirt} />
              <circle cx="71" cy="69" r="3.5" fill={p.skin} />
            </g>
          ) : (
            <g className={styles.armsRest}>
              <path d="M28 58 L35 78 L50 82" stroke={p.shirt} />
              <circle cx="52" cy="82" r="3.5" fill={p.skin} />
            </g>
          )}
        </g>
      ) : null}

    </svg>
  );
}
