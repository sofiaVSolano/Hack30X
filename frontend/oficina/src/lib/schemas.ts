/**
 * Esquemas de las respuestas de DETECTAR, transcritos de los modelos Pydantic reales:
 *
 * - backend/app/modules/detectar/api/agents.py          (AgentList, AgentRunList, SchedulerStatusOut)
 * - backend/app/modules/detectar/api/topics.py          (TopicPage, TopicDetail, LinkPage)
 * - backend/app/modules/detectar/api/metrics.py         (DefinitionsOut, MetricPage)
 * - backend/app/modules/detectar/api/classifications.py (RulesOut, ClassificationPage)
 * - backend/app/modules/detectar/api/collections.py     (CollectionPage)
 * - backend/app/modules/detectar/api/router.py          (HealthResponse)
 *
 * Los objetos ignoran campos que no conocen (zod los descarta). Un campo obligatorio ausente
 * o de otro tipo invalida la respuesta: el intermediario responde 502 en lugar de mostrar
 * datos incompletos como si fueran correctos.
 *
 * No hay campos de saturación, oportunidad ni confianza: no existen en la API.
 */
import { z } from "zod";

export const DATA_MODES = ["real", "simulated"] as const;
export const DataMode = z.enum(DATA_MODES);
export type DataMode = z.infer<typeof DataMode>;

export const SOURCES = ["google_trends_rss", "wikimedia", "gdelt", "youtube", "instagram", "x"] as const;
export const Source = z.enum(SOURCES);
export type Source = z.infer<typeof Source>;

const Json = z.record(z.string(), z.unknown());

// --- agentes -------------------------------------------------------------------------------

export const AGENT_RUN_STATUSES = ["pending", "running", "completed", "failed", "blocked"] as const;
export const AgentRunStatus = z.enum(AGENT_RUN_STATUSES);
export type AgentRunStatus = z.infer<typeof AgentRunStatus>;

export const ACTIVITIES = ["sin_ejecuciones", "pendiente", "en_curso", "completada", "fallida", "bloqueada"] as const;
export const Activity = z.enum(ACTIVITIES);
export type Activity = z.infer<typeof Activity>;

export const AgentRun = z.object({
  id: z.string(),
  agente: z.string(),
  data_mode: DataMode,
  estado: AgentRunStatus,
  disparador: z.string(),
  solicitado: z.string(),
  inicio: z.string().nullable(),
  fin: z.string().nullable(),
  resultado: Json.nullable(),
  codigo_error: z.string().nullable(),
  detalle_error: z.string().nullable(),
});
export type AgentRun = z.infer<typeof AgentRun>;

export const Agent = z.object({
  id: z.string(),
  nombre: z.string(),
  descripcion: z.string(),
  responsabilidad: z.string(),
  alcance: z.string(),
  colabora_con: z.array(z.string()),
  fuentes_permitidas: z.array(z.string()),
  herramientas_permitidas: z.array(z.string()),
  estado_implementacion: z.string(),
  estado_asignacion: z.string(),
  preguntas_abiertas: z.array(z.string()),
  frecuencia_minutos: z.number().int().nullable(),
  definido: z.boolean(),
  implementado: z.boolean(),
  ejecutado: z.boolean(),
  actividad: Activity,
  ultima_ejecucion: AgentRun.nullable(),
});
export type Agent = z.infer<typeof Agent>;

export const AgentList = z.object({ data_mode: DataMode, agentes: z.array(Agent) });
export type AgentList = z.infer<typeof AgentList>;

export const AgentRunList = z.object({
  agente: z.string(),
  data_mode: DataMode,
  limite: z.number().int(),
  ejecuciones: z.array(AgentRun),
});
export type AgentRunList = z.infer<typeof AgentRunList>;

export const ScheduledAgent = z.object({
  agente: z.string(),
  programado: z.boolean(),
  motivo_omision: z.string().nullable(),
  frecuencia_minutos: z.number().int().nullable(),
  data_mode: DataMode.nullable(),
});
export type ScheduledAgent = z.infer<typeof ScheduledAgent>;

export const SchedulerStatus = z.object({
  habilitado: z.boolean(),
  en_ejecucion: z.boolean(),
  intervalo_tick_segundos: z.number(),
  umbral_abandono_segundos: z.number().int(),
  agentes: z.array(ScheduledAgent),
  ultimo_tick: Json.nullable(),
});
export type SchedulerStatus = z.infer<typeof SchedulerStatus>;

// --- temas ---------------------------------------------------------------------------------

export const LINK_STATUSES = ["linked", "needs_review", "unlinked", "rejected"] as const;
export const LinkStatus = z.enum(LINK_STATUSES);
export type LinkStatus = z.infer<typeof LinkStatus>;

export const Topic = z.object({
  id: z.string(),
  data_mode: DataMode,
  nombre: z.string(),
  clave_normalizada: z.string(),
  ambiguo: z.boolean(),
  motivo_ambiguedad: z.string().nullable(),
  creado_por: z.string(),
  creado: z.string(),
  actualizado: z.string(),
  vinculos_por_fuente: z.record(z.string(), z.number().int()),
});
export type Topic = z.infer<typeof Topic>;

export const TopicPage = z.object({
  data_mode: DataMode,
  total: z.number().int(),
  limite: z.number().int(),
  desplazamiento: z.number().int(),
  items: z.array(Topic),
});
export type TopicPage = z.infer<typeof TopicPage>;

export const TopicAlias = z.object({
  texto: z.string(),
  normalizado: z.string(),
  tipo: z.string(),
  origen: z.string(),
  creado: z.string(),
});

export const TopicDetail = z.object({
  tema: Topic,
  alias: z.array(TopicAlias),
  sujetos: z.array(z.object({ fuente: z.string(), sujeto_original: z.string(), observaciones: z.number().int() })),
});
export type TopicDetail = z.infer<typeof TopicDetail>;

export const TopicLink = z.object({
  id: z.number().int(),
  observacion_id: z.number().int(),
  data_mode: DataMode,
  fuente: Source,
  sujeto_original: z.string(),
  candidato: z.string().nullable(),
  candidato_normalizado: z.string().nullable(),
  estado: LinkStatus,
  tema_id: z.string().nullable(),
  regla: z.string(),
  certeza: z.string(),
  origen: z.string(),
  motivo: z.string().nullable(),
  creado: z.string(),
  reemplazado: z.string().nullable(),
  reemplaza_a: z.number().int().nullable(),
});
export type TopicLink = z.infer<typeof TopicLink>;

export const LinkPage = z.object({
  data_mode: DataMode,
  limite: z.number().int(),
  desplazamiento: z.number().int(),
  items: z.array(TopicLink),
});
export type LinkPage = z.infer<typeof LinkPage>;

// --- métricas ------------------------------------------------------------------------------

export const METRIC_STATUSES = ["ok", "insufficient"] as const;
export const MetricStatus = z.enum(METRIC_STATUSES);

export const MetricDefinition = z.object({
  key: z.string(),
  source: z.string(),
  unit: z.string(),
  scope: z.string(),
  description: z.string(),
  formula: z.string(),
  required_data: z.string(),
  min_period: z.string(),
  insufficient_when: z.string(),
  limitations: z.string(),
});
export type MetricDefinition = z.infer<typeof MetricDefinition>;

export const MetricDefinitions = z.object({
  version: z.string(),
  parametros: Json,
  metricas: z.array(MetricDefinition),
});
export type MetricDefinitions = z.infer<typeof MetricDefinitions>;

export const MetricValue = z.object({
  tema_id: z.string(),
  data_mode: DataMode,
  fuente: Source,
  ambito: z.string(),
  metrica: z.string(),
  unidad: z.string(),
  valor: z.number().nullable(),
  estado: MetricStatus,
  motivo: z.string().nullable(),
  ventana_dias: z.number().int(),
  periodo_inicio: z.string(),
  periodo_fin: z.string(),
  fecha_referencia: z.string(),
  calculado: z.string(),
  version: z.string(),
  fuente_validada: z.boolean(),
  observaciones_usadas: z.number().int(),
  detalles: Json,
});
export type MetricValue = z.infer<typeof MetricValue>;

export const MetricPage = z.object({
  data_mode: DataMode,
  total: z.number().int(),
  limite: z.number().int(),
  desplazamiento: z.number().int(),
  items: z.array(MetricValue),
});
export type MetricPage = z.infer<typeof MetricPage>;

// --- clasificaciones -----------------------------------------------------------------------

export const STAGES = ["emergente", "acelerando", "punto_maximo", "saturada", "datos_insuficientes"] as const;
export const Stage = z.enum(STAGES);
export type Stage = z.infer<typeof Stage>;

export const EVIDENCE_ROLES = ["primary", "complementary", "excluded"] as const;

export const Evidence = z.object({
  fuente: Source,
  rol: z.enum(EVIDENCE_ROLES),
  fuente_validada: z.boolean(),
  etapa_propuesta: Stage.nullable(),
  motivo: z.string(),
  ambitos: z.array(Json),
});
export type Evidence = z.infer<typeof Evidence>;

export const Classification = z.object({
  id: z.number().int(),
  tema_id: z.string(),
  data_mode: DataMode,
  etapa: Stage,
  motivo: z.string().nullable(),
  fecha_referencia: z.string(),
  calculado: z.string(),
  version: z.string(),
  version_metricas: z.string(),
  calibrado: z.boolean(),
  reemplazada: z.string().nullable(),
  evidencia: z.array(Evidence),
  metricas_consideradas: z.array(Json),
  explicacion: Json,
});
export type Classification = z.infer<typeof Classification>;

export const ClassificationPage = z.object({
  data_mode: DataMode,
  total: z.number().int(),
  limite: z.number().int(),
  desplazamiento: z.number().int(),
  items: z.array(Classification),
});
export type ClassificationPage = z.infer<typeof ClassificationPage>;

export const StageRules = z.object({
  version: z.string(),
  version_metricas: z.string(),
  provisional: z.boolean(),
  calibrado: z.boolean(),
  parametros: Json,
  parametros_sha256: z.string(),
  registrada: z.boolean(),
  etapas: z.record(z.string(), z.string()),
  capacidades_por_fuente: z.record(z.string(), z.array(z.string())),
  metricas_usadas: z.record(z.string(), z.array(z.string())),
});
export type StageRules = z.infer<typeof StageRules>;

// --- recolecciones y salud -----------------------------------------------------------------

export const COLLECTION_STATUSES = ["queued", "running", "ok", "partial", "failed"] as const;

export const CollectionPage = z.object({
  data_mode: DataMode,
  estado: z.enum(COLLECTION_STATUSES).nullable(),
  total: z.number().int(),
  limite: z.number().int(),
  desplazamiento: z.number().int(),
  items: z.array(
    z.object({
      run_id: z.string(),
      data_mode: DataMode,
      estado: z.enum(COLLECTION_STATUSES),
      creado: z.string(),
      inicio: z.string().nullable(),
      fin: z.string().nullable(),
      fuentes_solicitadas: z.array(z.string()),
      paises: z.array(z.string()),
      fuentes: z.array(
        z.object({
          fuente: Source,
          estado: z.string(),
          observaciones_nuevas: z.number().int(),
          codigo_error: z.string().nullable(),
        }),
      ),
    }),
  ),
});
export type CollectionPage = z.infer<typeof CollectionPage>;

export const Health = z.object({
  status: z.literal("ok"),
  module: z.literal("detectar"),
  version: z.string(),
  rules_version: z.string(),
  time: z.string(),
  checks: z.object({
    database: z.object({ status: z.string(), detail: z.string() }),
    rules: z.object({ status: z.string(), detail: z.string() }),
  }),
});
export type Health = z.infer<typeof Health>;

// --- errores del intermediario -------------------------------------------------------------

export const OficinaProblem = z.object({
  code: z.string(),
  title: z.string(),
  detail: z.string().optional(),
  errors: z.array(z.object({ campo: z.string(), mensaje: z.string() })).optional(),
});
export type OficinaProblem = z.infer<typeof OficinaProblem>;
