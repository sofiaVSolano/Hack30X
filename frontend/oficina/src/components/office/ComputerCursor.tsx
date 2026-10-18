"use client";

import { useEffect, useRef, type RefObject } from "react";

import { useFinePointer, useReducedMotion } from "./hooks";
import styles from "./Computer.module.css";

const INTERACTIVE = "a[href], button:not(:disabled), [role='tab'], summary, select, label, [role='button']";
const TEXT_ENTRY = "input:not([type='checkbox']):not([type='radio']):not([type='range']), textarea, [contenteditable='true']";

/**
 * Halo del cursor dentro del computador: sigue al puntero con un leve retardo, crece sobre los
 * controles y late al hacer clic. Solo con puntero fino y sin movimiento reducido; en campos de
 * texto se oculta para dejar el cursor de escritura nativo. Se mueve escribiendo `transform` en
 * el elemento (sin estado de React por fotograma).
 */
export function ComputerCursor({ scope }: { scope: RefObject<HTMLElement | null> }) {
  const fine = useFinePointer();
  const reduced = useReducedMotion();
  const ring = useRef<HTMLDivElement | null>(null);
  const enabled = fine && !reduced;

  useEffect(() => {
    const root = scope.current;
    const el = ring.current;
    if (!enabled || !root || !el) return;
    let x = -100;
    let y = -100;
    let tx = -100;
    let ty = -100;
    let frame = 0;
    let mode: "base" | "hover" | "hidden" = "hidden";

    const paint = () => {
      x += (tx - x) * 0.35;
      y += (ty - y) * 0.35;
      el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`;
      frame = Math.abs(tx - x) + Math.abs(ty - y) > 0.3 ? requestAnimationFrame(paint) : 0;
    };
    const setMode = (next: typeof mode) => {
      if (next !== mode) {
        mode = next;
        el.dataset.mode = next;
      }
    };
    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return setMode("hidden");
      tx = e.clientX;
      ty = e.clientY;
      if (mode === "hidden") {
        x = tx;
        y = ty;
      }
      const target = e.target instanceof Element ? e.target : null;
      setMode(target?.closest(TEXT_ENTRY) ? "hidden" : target?.closest(INTERACTIVE) ? "hover" : "base");
      if (!frame) frame = requestAnimationFrame(paint);
    };
    const onLeave = () => setMode("hidden");
    const onDown = () => {
      if (mode === "hidden") return;
      if (typeof el.animate === "function") el.animate([{ scale: "0.72" }, { scale: "1" }], { duration: 260, easing: "cubic-bezier(0.23, 1, 0.32, 1)" });
    };
    root.addEventListener("pointermove", onMove);
    root.addEventListener("pointerleave", onLeave);
    root.addEventListener("pointerdown", onDown);
    return () => {
      cancelAnimationFrame(frame);
      root.removeEventListener("pointermove", onMove);
      root.removeEventListener("pointerleave", onLeave);
      root.removeEventListener("pointerdown", onDown);
    };
  }, [enabled, scope]);

  if (!enabled) return null;
  return (
    <div className={styles.cursorLayer} aria-hidden="true">
      <div ref={ring} className={styles.cursorRing} data-mode="hidden" data-testid="cursor-halo" />
    </div>
  );
}
