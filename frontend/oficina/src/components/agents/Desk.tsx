import type { Activity } from "@/lib/schemas";

import styles from "./Desk.module.css";

/**
 * Puesto de trabajo de un agente, visto desde arriba: mesa, monitor, lámpara, silla y agente.
 *
 * Todo lo que cambia sale de la API:
 * - `implemented = false` → silla vacía y pantalla apagada (rol sin tarea);
 * - `activity` pendiente/en_curso → pantalla encendida con líneas que se escriben y lámpara
 *   encendida: es el ÚNICO estado con movimiento, y se detiene con prefers-reduced-motion;
 * - completada/fallida/bloqueada → pantalla en reposo con el símbolo del último resultado;
 * - sin_ejecuciones → pantalla en espera.
 */
export function Desk({ activity, implemented, size = 120 }: { activity: Activity; implemented: boolean; size?: number }) {
  const working = implemented && (activity === "pendiente" || activity === "en_curso");
  const state = !implemented ? "vacante" : working ? "trabajando" : activity;
  return (
    <svg
      className={styles.desk}
      data-state={state}
      viewBox="0 0 120 92"
      width={size}
      height={(size * 92) / 120}
      aria-hidden="true"
      focusable="false"
    >
      {/* Mesa */}
      <rect className={styles.table} x="8" y="18" width="104" height="34" rx="4" />
      {/* Lámpara (encendida solo con trabajo real) */}
      <circle className={styles.lampGlow} cx="99" cy="30" r="12" />
      <circle className={styles.lamp} cx="99" cy="30" r="4" />
      {/* Monitor y pie */}
      <rect className={styles.stand} x="56" y="40" width="8" height="5" rx="1" />
      <rect className={styles.monitor} x="34" y="12" width="52" height="29" rx="3" />
      <rect className={styles.screen} x="37" y="15" width="46" height="23" rx="1.5" />
      {state === "trabajando" ? (
        <g className={styles.code}>
          <rect className={styles.line} x="41" y="19" width="26" height="2.6" rx="1.3" />
          <rect className={styles.line} x="41" y="24.5" width="34" height="2.6" rx="1.3" />
          <rect className={styles.line} x="41" y="30" width="20" height="2.6" rx="1.3" />
        </g>
      ) : null}
      {state === "completada" ? <path className={styles.glyphOk} d="M51 27 l6 5 l11 -10" /> : null}
      {state === "fallida" ? <path className={styles.glyphBad} d="M53 21 l14 12 M67 21 l-14 12" /> : null}
      {state === "bloqueada" ? (
        <g className={styles.glyphWarn}>
          <circle cx="60" cy="26.5" r="7" />
          <path d="M55 31.5 l10 -10" />
        </g>
      ) : null}
      {state === "sin_ejecuciones" ? <circle className={styles.standby} cx="60" cy="26.5" r="2" /> : null}
      {/* Teclado */}
      <rect className={styles.keyboard} x="45" y="45" width="30" height="5" rx="1.2" />
      {/* Silla */}
      <circle className={styles.chair} cx={implemented ? 60 : 72} cy={implemented ? 70 : 76} r="11" />
      {/* Agente (cabeza y hombros, de espaldas al observador) */}
      {implemented ? (
        <g className={styles.agent}>
          <ellipse className={styles.shoulders} cx="60" cy="69" rx="15" ry="8" />
          <circle className={styles.head} cx="60" cy="60" r="7.5" />
        </g>
      ) : null}
    </svg>
  );
}
