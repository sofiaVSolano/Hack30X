"use client";

import { Clock3, Network } from "lucide-react";

import { ActivityBadge } from "@/components/ui/Badges";
import { label, SCOPE } from "@/lib/labels";
import type { Agent, SchedulerStatus } from "@/lib/schemas";

import { Desk } from "./Desk";
import styles from "./OfficeFloor.module.css";

const ROOM_ORDER = ["detectar", "entender", "crear", "validar", "transversal"];

function roomName(scope: string): string {
  return scope === "transversal" ? "Coordinación" : `Sala ${label(SCOPE, scope)}`;
}

/**
 * Planta de la oficina: una sala por módulo (según `alcance` de la API) y un puesto por agente.
 *
 * Lo que se ve sale solo de `/agentes` y `/agentes/programador`:
 * - el dibujo del puesto refleja `implementado` y `actividad` (ver Desk);
 * - el pulso y la animación aparecen SOLO con `pendiente` o `en_curso` y se detienen con
 *   prefers-reduced-motion;
 * - el reloj del pasillo muestra el estado real del programador, no un temporizador.
 */
export function OfficeFloor({
  agents,
  onSelect,
  scheduler,
}: {
  agents: Agent[];
  onSelect: (agent: Agent) => void;
  scheduler?: SchedulerStatus;
}) {
  const scopes = [...new Set(agents.map((a) => a.alcance))].sort(
    (a, b) => (ROOM_ORDER.indexOf(a) + 1 || 99) - (ROOM_ORDER.indexOf(b) + 1 || 99),
  );
  const implemented = agents.filter((a) => a.implementado).length;
  return (
    <div className={styles.floor} role="group" aria-label="Estaciones de agentes">
      <div className={styles.rooms}>
        {scopes.map((scope) => {
          const members = agents.filter((a) => a.alcance === scope);
          return (
            <section
              key={scope}
              className={styles.room}
              data-scope={scope}
              aria-label={roomName(scope)}
              // La sala crece con sus puestos (mínimo 250px por puesto) y pasa a la fila siguiente si no cabe.
              style={{ flex: `${members.length} 1 ${members.length * 250}px` }}
            >
              <h3 className={styles.roomName}>{roomName(scope)}</h3>
              <ul className={styles.desks}>
                {members.map((agent) => {
                  const live = agent.actividad === "pendiente" || agent.actividad === "en_curso";
                  return (
                    <li key={agent.id}>
                      <button
                        type="button"
                        className={styles.station}
                        data-activity={agent.actividad}
                        data-implemented={agent.implementado}
                        onClick={() => onSelect(agent)}
                        aria-label={`${agent.nombre}: ${agent.implementado ? "tarea implementada" : "sin tarea implementada"}. Ver detalle`}
                      >
                        <span className={`${styles.deskArt} ${live ? styles.live : ""}`} data-live={live}>
                          <Desk who={agent.id} activity={agent.actividad} implemented={agent.implementado} />
                        </span>
                        <span className={styles.plate}>
                          <span className={styles.name}>{agent.nombre}</span>
                          <span className={styles.id} translate="no">
                            {agent.id}
                          </span>
                        </span>
                        <span className={styles.status}>
                          <ActivityBadge activity={agent.actividad} />
                        </span>
                        {!agent.implementado ? <span className={styles.vacant}>Sin tarea implementada</span> : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
      </div>

      <div className={styles.corridor}>
        <div className={styles.coordinator}>
          <Network size={18} aria-hidden="true" />
          <span>
            <strong>Mesa del coordinador</strong>
            <span className={styles.corridorSub}>
              {implemented} de {agents.length} puestos con tarea implementada
            </span>
          </span>
        </div>
        {scheduler ? (
          <div className={styles.clock} data-on={scheduler.habilitado && scheduler.en_ejecucion}>
            <Clock3 size={18} aria-hidden="true" />
            <span>
              <strong>Programador {scheduler.habilitado ? (scheduler.en_ejecucion ? "en marcha" : "habilitado, detenido") : "apagado"}</strong>
              <span className={styles.corridorSub}>
                {(() => {
                  const n = scheduler.agentes.filter((a) => a.programado).length;
                  return `${n} ${n === 1 ? "agente" : "agentes"} con ejecución periódica`;
                })()}
              </span>
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
