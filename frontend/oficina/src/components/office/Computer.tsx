"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { ViewTransition, useEffect, useRef, type ReactNode } from "react";

import { ModeSwitch, SimulatedBanner } from "@/components/shell/ModeSwitch";
import { useCurrentPath, useModeHref } from "@/hooks/useDataMode";

import { ComputerCursor } from "./ComputerCursor";
import { MODULE_TABS, ZONE, type Station } from "./scene";
import type { StationInfo } from "./OfficeWorld";
import styles from "./Computer.module.css";

/**
 * El interior del computador de un puesto: la aplicación real (las mismas vistas, consultas y
 * rutas) dentro de un entorno digital con su propia navegación contextual y su cursor.
 */
export function Computer({
  station,
  info,
  onExit,
  sound,
  focusOnMount = false,
  children,
}: {
  station: Station;
  info: StationInfo;
  onExit: () => void;
  /** Mover el foco a la pantalla al montarse (al entrar desde la oficina). */
  focusOnMount?: boolean;
  sound: ReactNode;
  children: ReactNode;
}) {
  const path = useCurrentPath();
  const href = useModeHref();
  const zone = ZONE[station.zone];
  const tabs = MODULE_TABS[station.zone];
  const root = useRef<HTMLDivElement | null>(null);
  const main = useRef<HTMLElement | null>(null);

  // Al entrar desde la oficina, el foco pasa a la pantalla para teclado y lectores de pantalla.
  useEffect(() => {
    if (focusOnMount) main.current?.focus({ preventScroll: true });
    // Solo al montarse: cambiar de sección no mueve el foco.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div ref={root} className={styles.computer} data-cursor="computador" data-module={zone.id}>
      <header className={styles.bar}>
        <nav aria-label="Ubicación" className={styles.crumbs}>
          <ol>
            <li>
              <Link href="/">HACK 30X</Link>
            </li>
            <li>
              <button type="button" className={styles.crumbBtn} onClick={onExit}>
                Oficina
              </button>
            </li>
            <li>{zone.room}</li>
            <li>Computador</li>
            <li aria-current="page">{zone.module}</li>
          </ol>
        </nav>
        <div className={styles.tools}>
          <ModeSwitch />
          {sound}
          <button type="button" className={styles.exit} onClick={onExit} aria-label="Volver a la oficina">
            <ArrowLeft size={16} aria-hidden="true" /> Volver<span className={styles.exitLong}> a la oficina</span>
          </button>
        </div>
      </header>
      <SimulatedBanner />
      <div className={styles.moduleBar}>
        <p className={styles.station}>
          <span className={styles.module}>{zone.module}</span>
          <span className={styles.stationName}>{info.title}</span>
          <span className={styles.stationStatus}>{info.status}</span>
        </p>
        {tabs ? (
          <nav aria-label={`Secciones de ${zone.module}`}>
            <ul className={styles.tabs}>
              {tabs.map((tab) => {
                const active = path === tab.href || path.startsWith(`${tab.href}/`);
                return (
                  <li key={tab.href}>
                    <Link
                      href={href(tab.href)}
                      className={styles.tab}
                      aria-current={active ? "page" : undefined}
                      transitionTypes={["pestana"]}
                      scroll={false}
                    >
                      {tab.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        ) : null}
      </div>
      <main ref={main} id="contenido" className={styles.screen} tabIndex={-1}>
        <ViewTransition key={path} enter={{ pestana: "pestana-entra", default: "none" }} exit={{ pestana: "pestana-sale", default: "none" }} default="none">
          <div className={styles.content}>{children}</div>
        </ViewTransition>
      </main>
      <ComputerCursor scope={root} />
    </div>
  );
}
