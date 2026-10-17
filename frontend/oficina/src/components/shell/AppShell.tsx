"use client";

import {
  Bot,
  CalendarClock,
  ChartLine,
  FlaskConical,
  History,
  Layers,
  LayoutDashboard,
  Tags,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { useCurrentPath, useDataMode, useModeHref } from "@/hooks/useDataMode";

import { BrandMark } from "./BrandMark";
import styles from "./AppShell.module.css";

export const NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/", label: "Oficina", icon: LayoutDashboard },
  { href: "/agentes", label: "Agentes", icon: Bot },
  { href: "/ejecuciones", label: "Ejecuciones", icon: History },
  { href: "/programador", label: "Programador", icon: CalendarClock },
  { href: "/temas", label: "Temas", icon: Tags },
  { href: "/metricas", label: "Métricas", icon: ChartLine },
  { href: "/clasificaciones", label: "Clasificaciones", icon: Layers },
];

function ModeSwitch() {
  const mode = useDataMode();
  const path = useCurrentPath();
  return (
    <div className={styles.mode} role="group" aria-label="Modo de datos">
      <Link href={path} className={styles.modeOption} aria-current={mode === "real" ? "true" : undefined}>
        Real
      </Link>
      <Link
        href={`${path}?modo=simulated`}
        className={`${styles.modeOption} ${styles.modeSim}`}
        aria-current={mode === "simulated" ? "true" : undefined}
      >
        <FlaskConical size={13} aria-hidden="true" /> Simulado
      </Link>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const path = useCurrentPath();
  const href = useModeHref();
  const mode = useDataMode();
  return (
    <div className={styles.shell}>
      <a className="skip-link" href="#contenido">
        Saltar al contenido
      </a>
      <aside className={styles.side}>
        <Link href={href("/")} className={styles.brand} aria-label="HACK 30X, oficina de agentes: inicio">
          <BrandMark />
          <span className={styles.brandText}>
            <span className={styles.brandName}>HACK 30X</span>
            <span className={styles.brandSub}>Oficina de agentes</span>
          </span>
        </Link>
        <nav aria-label="Secciones de la oficina" className={styles.nav}>
          <ul>
            {NAV.map((item) => {
              const active = item.href === "/" ? path === "/" : path.startsWith(item.href);
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link href={href(item.href)} className={styles.navLink} aria-current={active ? "page" : undefined}>
                    <Icon size={17} aria-hidden="true" />
                    <span>{item.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className={styles.sideFoot}>
          <span className="eyebrow">Modo de datos</span>
          <ModeSwitch />
          <p className={styles.readonly}>Solo lectura, uso local</p>
        </div>
      </aside>
      <div className={styles.main}>
        {mode === "simulated" ? (
          <div className={styles.simBanner} role="note">
            <FlaskConical size={16} aria-hidden="true" />
            <span>
              <strong>Modo simulado con un conjunto sintético de demostración.</strong> Todo lo que ves aquí son datos{" "}
              <code>simulated</code> calculados sobre valores inventados: no describen tendencias reales y no se mezclan con
              los datos reales.
            </span>
          </div>
        ) : null}
        <main id="contenido" className={styles.content} tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
