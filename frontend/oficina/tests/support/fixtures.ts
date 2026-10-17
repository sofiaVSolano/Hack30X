/**
 * Datos de PRUEBA con la forma exacta de los modelos Pydantic de DETECTAR. Solo se usan en
 * pruebas automatizadas; la aplicación nunca los importa.
 */
import type { Agent, AgentRun, Classification, MetricValue, SchedulerStatus, Topic } from "@/lib/schemas";

export function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "run_0001",
    agente: "trend_hunter",
    data_mode: "real",
    estado: "completed",
    disparador: "manual",
    solicitado: "2026-10-16T21:00:00Z",
    inicio: "2026-10-16T21:00:01Z",
    fin: "2026-10-16T21:00:31Z",
    resultado: { agente: "trend_hunter", limitaciones: ["GDELT no validada"] },
    codigo_error: null,
    detalle_error: null,
    ...overrides,
  };
}

const AGENT_IDS = ["trend_hunter", "format_hunter", "analyst", "audience_filter", "strategist", "supervisor"] as const;
const IMPLEMENTED = new Set(["trend_hunter", "supervisor"]);

export function agent(id: string, overrides: Partial<Agent> = {}): Agent {
  const implemented = IMPLEMENTED.has(id);
  return {
    id,
    nombre: `Agente ${id}`,
    descripcion: `Descripción de ${id} para pruebas.`,
    responsabilidad: "Responsabilidad de prueba.",
    alcance: id === "supervisor" ? "transversal" : "detectar",
    colabora_con: ["detectar"],
    fuentes_permitidas: [],
    herramientas_permitidas: [],
    estado_implementacion: implemented ? "available" : "planned",
    estado_asignacion: "provisional",
    preguntas_abiertas: [],
    frecuencia_minutos: null,
    definido: true,
    implementado: implemented,
    ejecutado: false,
    actividad: "sin_ejecuciones",
    ultima_ejecucion: null,
    ...overrides,
  };
}

export function agentList(overrides: Record<string, Partial<Agent>> = {}, mode: "real" | "simulated" = "real") {
  return { data_mode: mode, agentes: AGENT_IDS.map((id) => agent(id, overrides[id])) };
}

export function scheduler(overrides: Partial<SchedulerStatus> = {}): SchedulerStatus {
  return {
    habilitado: false,
    en_ejecucion: false,
    intervalo_tick_segundos: 60,
    umbral_abandono_segundos: 3600,
    agentes: AGENT_IDS.map((id) => ({
      agente: id,
      programado: false,
      motivo_omision: IMPLEMENTED.has(id) ? "sin_frecuencia" : "no_implementado",
      frecuencia_minutos: null,
      data_mode: null,
    })),
    ultimo_tick: null,
    ...overrides,
  };
}

export const TOPIC_ID = "tpc_0123456789abcdef";

export function topic(overrides: Partial<Topic> = {}): Topic {
  return {
    id: TOPIC_ID,
    data_mode: "real",
    nombre: "Tema de prueba",
    clave_normalizada: "tema de prueba",
    ambiguo: false,
    motivo_ambiguedad: null,
    creado_por: "linker",
    creado: "2026-10-10T10:00:00Z",
    actualizado: "2026-10-15T10:00:00Z",
    vinculos_por_fuente: { wikimedia: 3 },
    ...overrides,
  };
}

export const page = <T,>(items: T[], extra: Record<string, unknown> = {}) => ({
  data_mode: "real",
  total: items.length,
  limite: 20,
  desplazamiento: 0,
  items,
  ...extra,
});

export function classification(overrides: Partial<Classification> = {}): Classification {
  return {
    id: 1,
    tema_id: TOPIC_ID,
    data_mode: "real",
    etapa: "acelerando",
    motivo: null,
    fecha_referencia: "2026-10-15",
    calculado: "2026-10-16T02:00:00Z",
    version: "stages-v1",
    version_metricas: "metrics-v1",
    calibrado: false,
    reemplazada: null,
    evidencia: [
      { fuente: "wikimedia", rol: "primary", fuente_validada: true, etapa_propuesta: "acelerando", motivo: "señal consistente", ambitos: [] },
      { fuente: "gdelt", rol: "complementary", fuente_validada: false, etapa_propuesta: "emergente", motivo: "fuente no validada", ambitos: [] },
    ],
    metricas_consideradas: [],
    explicacion: { provisional: true, notes: ["Umbrales provisionales"] },
    ...overrides,
  };
}

export function metric(overrides: Partial<MetricValue> = {}): MetricValue {
  return {
    tema_id: TOPIC_ID,
    data_mode: "real",
    fuente: "wikimedia",
    ambito: "es.wikipedia",
    metrica: "wiki_views_total",
    unidad: "views",
    valor: 100,
    estado: "ok",
    motivo: null,
    ventana_dias: 7,
    periodo_inicio: "2026-10-09T00:00:00Z",
    periodo_fin: "2026-10-16T00:00:00Z",
    fecha_referencia: "2026-10-15",
    calculado: "2026-10-16T02:00:00Z",
    version: "metrics-v1",
    fuente_validada: true,
    observaciones_usadas: 7,
    detalles: {},
    ...overrides,
  };
}

export const rules = {
  version: "stages-v1",
  version_metricas: "metrics-v1",
  provisional: true,
  calibrado: false,
  parametros: { calibrated: false },
  parametros_sha256: "a".repeat(64),
  registrada: true,
  etapas: { emergente: "Señal nueva", acelerando: "Crece", punto_maximo: "Máximo", saturada: "No asignada", datos_insuficientes: "Sin datos" },
  capacidades_por_fuente: { wikimedia: ["emergente", "acelerando", "punto_maximo"], gdelt: [] },
  metricas_usadas: { wikimedia: ["wiki_views_growth"] },
};

export const definitions = {
  version: "metrics-v1",
  parametros: {},
  metricas: [
    {
      key: "wiki_views_total",
      source: "wikimedia",
      unit: "views",
      scope: "artículo",
      description: "Visitas en la ventana.",
      formula: "suma",
      required_data: "pageviews",
      min_period: "7 días",
      insufficient_when: "sin días",
      limitations: "solo artículos vinculados",
    },
  ],
};
