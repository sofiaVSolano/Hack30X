"use client";

import { Film } from "lucide-react";

import { useMotionPref, useReducedMotion, useSystemReducedMotion } from "./hooks";
import styles from "./OfficeWorld.module.css";

/**
 * Animaciones completas o reducidas. Por defecto sigue al sistema; si el sistema pide reducirlas
 * (por ejemplo, «Efectos de animación» desactivado en Windows), la persona puede activarlas aquí.
 */
export function MotionToggle() {
  const { pref, setPref } = useMotionPref();
  const reduced = useReducedMotion();
  const system = useSystemReducedMotion();
  const next = reduced ? "completo" : "reducido";
  return (
    <button
      type="button"
      className={styles.motionBtn}
      aria-pressed={!reduced}
      onClick={() => setPref(next === (system ? "reducido" : "completo") ? "sistema" : next)}
      title={
        reduced
          ? system && pref === "sistema"
            ? "Tu sistema tiene las animaciones reducidas. Pulsa para ver la animación completa."
            : "Animaciones reducidas. Pulsa para verlas completas."
          : "Animaciones completas. Pulsa para reducirlas."
      }
    >
      <Film size={16} aria-hidden="true" />
      <span>Animaciones: {reduced ? "reducidas" : "completas"}</span>
    </button>
  );
}
