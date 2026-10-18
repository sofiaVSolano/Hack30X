"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { useMotionPref } from "@/components/office/hooks";
import { OfficeScene } from "@/components/office/OfficeScene";
import { BrandMark } from "@/components/shell/BrandMark";
import { useAgents } from "@/hooks/queries";

import styles from "./LandingView.module.css";

/** Recorte del mundo: la Sala de tendencias (DETECTAR) y el arranque de la sala de análisis. */
const CROP = { x: 300, y: 36, width: 780, height: 440 };

/**
 * Portada de HACK 30X: una idea, una acción. La ilustración es la oficina real (los puestos se
 * dibujan con el estado que devuelve la API en modo real).
 */
export function LandingView() {
  const agents = useAgents("real");
  useMotionPref(); // aplica la preferencia de animaciones guardada
  const map = useMemo(() => (agents.data ? new Map(agents.data.agentes.map((a) => [a.id, a])) : null), [agents.data]);

  return (
    <div className={styles.page}>
      <a className="skip-link" href="#contenido">
        Saltar al contenido
      </a>
      <header className={styles.top}>
        <Link href="/" className={styles.brand} aria-label="HACK 30X: portada">
          <BrandMark size={36} />
          <span>HACK 30X</span>
        </Link>
      </header>

      <main id="contenido" className={styles.hero} tabIndex={-1}>
        <div className={styles.copy}>
          <h1 className={styles.title}>
            Las tendencias no esperan. <span className={styles.accent}>Anticípate.</span>
          </h1>
          <p className={styles.lede}>
            HACK 30X detecta qué temas empiezan a crecer en América Latina antes de que se saturen, con datos públicos y la
            evidencia a la vista. Recorre la oficina: cada puesto es un computador con su parte del trabajo.
          </p>
          <Link className={styles.cta} href="/oficina" transitionTypes={["entrar-oficina"]}>
            Entrar a la oficina <ArrowRight size={19} aria-hidden="true" />
          </Link>
        </div>

        <div className={styles.view} aria-hidden="true">
          <div className={styles.scene}>
            <OfficeScene agents={map} crop={CROP} interactive={false} selected="trend_hunter" className={styles.svg} />
          </div>
        </div>
      </main>
    </div>
  );
}
