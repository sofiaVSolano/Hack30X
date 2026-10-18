"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

/** Tamaño de un elemento, actualizado con ResizeObserver (una medida por cambio, no por fotograma). */
export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setSize({ width: el.clientWidth, height: el.clientHeight });
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, size] as const;
}

function mediaStore(query: string) {
  return {
    subscribe(cb: () => void) {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const mq = window.matchMedia(query);
      mq.addEventListener?.("change", cb);
      return () => mq.removeEventListener?.("change", cb);
    },
    get() {
      return typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(query).matches : false;
    },
  };
}

const reduced = mediaStore("(prefers-reduced-motion: reduce)");
const finePointer = mediaStore("(hover: hover) and (pointer: fine)");

// --- preferencia de animaciones -----------------------------------------------------------
// «sistema» sigue prefers-reduced-motion; «completo» y «reducido» la sustituyen. Se guarda solo en
// el navegador y se refleja en <html data-motion> para que el CSS la respete.

export type MotionPref = "sistema" | "completo" | "reducido";
const MOTION_KEY = "hack30x:movimiento";
const motionListeners = new Set<() => void>();

function readMotion(): MotionPref {
  try {
    const v = window.localStorage.getItem(MOTION_KEY);
    return v === "completo" || v === "reducido" ? v : "sistema";
  } catch {
    return "sistema";
  }
}

function applyMotion(pref: MotionPref) {
  if (typeof document === "undefined") return;
  if (pref === "sistema") delete document.documentElement.dataset.motion;
  else document.documentElement.dataset.motion = pref;
}

export function useMotionPref() {
  const pref = useSyncExternalStore(
    (cb) => {
      motionListeners.add(cb);
      return () => motionListeners.delete(cb);
    },
    readMotion,
    () => "sistema" as MotionPref,
  );
  useEffect(() => applyMotion(pref), [pref]);
  const setPref = useCallback((next: MotionPref) => {
    try {
      window.localStorage.setItem(MOTION_KEY, next);
    } catch {
      /* almacenamiento bloqueado: se aplica solo en esta visita */
    }
    applyMotion(next);
    motionListeners.forEach((cb) => cb());
  }, []);
  return { pref, setPref };
}

/** ¿Reducir el movimiento? Lo decide la persona en la oficina o, si no eligió, su sistema. */
export function useReducedMotion() {
  const system = useSyncExternalStore(reduced.subscribe, reduced.get, () => false);
  const { pref } = useMotionPref();
  return pref === "completo" ? false : pref === "reducido" ? true : system;
}

/** Lo que pide el sistema operativo (para explicar el botón de animaciones). */
export const useSystemReducedMotion = () => useSyncExternalStore(reduced.subscribe, reduced.get, () => false);
export const useFinePointer = () => useSyncExternalStore(finePointer.subscribe, finePointer.get, () => false);

// --- sonido opcional ------------------------------------------------------------------------

const SOUND_KEY = "hack30x:sonido";
const soundListeners = new Set<() => void>();

function readSound(): boolean {
  try {
    return window.localStorage.getItem(SOUND_KEY) === "on";
  } catch {
    return false;
  }
}

let audio: AudioContext | null = null;

/** Dos tonos breves y suaves generados con Web Audio: sin archivos ni dependencias. */
function tone(kind: "entrar" | "salir") {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    audio ??= new Ctx();
    const now = audio.currentTime;
    const notes = kind === "entrar" ? [523.25, 783.99] : [783.99, 523.25];
    notes.forEach((freq, i) => {
      const osc = audio!.createOscillator();
      const gain = audio!.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      const t = now + i * 0.09;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.05, t + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
      osc.connect(gain).connect(audio!.destination);
      osc.start(t);
      osc.stop(t + 0.18);
    });
  } catch {
    /* sin audio disponible: la interfaz no depende del sonido */
  }
}

/** Preferencia de sonido del visitante: apagada por defecto, guardada solo en su navegador. */
export function useSound() {
  const enabled = useSyncExternalStore(
    (cb) => {
      soundListeners.add(cb);
      return () => soundListeners.delete(cb);
    },
    readSound,
    () => false,
  );
  const toggle = useCallback(() => {
    try {
      window.localStorage.setItem(SOUND_KEY, readSound() ? "off" : "on");
    } catch {
      /* almacenamiento bloqueado: el sonido sigue apagado */
    }
    soundListeners.forEach((cb) => cb());
  }, []);
  const play = useCallback((kind: "entrar" | "salir") => {
    if (readSound()) tone(kind);
  }, []);
  return { enabled, toggle, play };
}
