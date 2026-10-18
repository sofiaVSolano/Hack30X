"use client";

import { FlaskConical } from "lucide-react";
import Link from "next/link";

import { useCurrentPath, useDataMode } from "@/hooks/useDataMode";

import styles from "./ModeSwitch.module.css";

/** Cambia entre datos reales y el conjunto sintético; el modo vive en la URL (?modo=simulated). */
export function ModeSwitch() {
  const mode = useDataMode();
  const path = useCurrentPath();
  return (
    <div className={styles.mode} role="group" aria-label="Modo de datos">
      <Link href={path} className={styles.option} aria-current={mode === "real" ? "true" : undefined} scroll={false}>
        Real
      </Link>
      <Link
        href={`${path}?modo=simulated`}
        className={`${styles.option} ${styles.sim}`}
        aria-current={mode === "simulated" ? "true" : undefined}
        scroll={false}
      >
        <FlaskConical size={13} aria-hidden="true" /> Simulado
      </Link>
    </div>
  );
}

/** Aviso permanente del modo simulado: nunca se confunde con datos reales. */
export function SimulatedBanner() {
  const mode = useDataMode();
  if (mode !== "simulated") return null;
  return (
    <div className={styles.banner} role="note">
      <FlaskConical size={16} aria-hidden="true" />
      <span>
        <strong>Modo simulado con un conjunto sintético de demostración.</strong> Todo lo que ves aquí son datos{" "}
        <code>simulated</code> calculados sobre valores inventados: no describen tendencias reales y no se mezclan con los
        datos reales.
      </span>
    </div>
  );
}
