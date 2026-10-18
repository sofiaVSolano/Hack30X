/**
 * Datos de PRUEBA con la forma exacta de los modelos Pydantic de CREAR. Solo para pruebas.
 */
import type {
  Approach,
  BatchOut,
  CrearOptions,
  CreativeContext,
  GapOut,
  GapPage,
  ProposalOut,
  ProposalPage,
} from "@/lib/crear/schemas";

export const TOPIC = "tpc_00000000000000e1";

export function options(overrides: Partial<CrearOptions> = {}): CrearOptions {
  return {
    enfoques: [
      { id: "educativo", nombre: "Educativo", descripcion: "Explica." },
      { id: "controversial", nombre: "Controversial", descripcion: "Debate." },
      { id: "narrativo", nombre: "Narrativo", descripcion: "Historia." },
    ],
    plataformas: [
      { id: "tiktok", nombre: "TikTok", formato: "Video vertical de 45 a 60 segundos", pautas: ["Gancho"] },
      { id: "instagram_carrusel", nombre: "Carrusel de Instagram", formato: "Carrusel de 7 diapositivas", pautas: ["Portada"] },
    ],
    audiencias: [
      { id: "general_latam", nombre: "Público general latinoamericano", descripcion: "Personas adultas.", tono: "Claro y cercano." },
      { id: "jovenes_genz", nombre: "Jóvenes Gen Z", descripcion: "Nativos digitales.", tono: "Ritmo rápido." },
    ],
    audiencia_por_defecto: "general_latam",
    paises: [
      { id: "CO", nombre: "Colombia" },
      { id: "MX", nombre: "México" },
    ],
    motor: { id: "plantillas-v1", nombre: "Plantillas (sin IA)", modelo: null, detalle: "Sin credencial de Anthropic." },
    ...overrides,
  };
}

export function gap(overrides: Partial<GapOut> = {}): GapOut {
  return {
    tema_id: TOPIC,
    tema_nombre: "Tema Eta",
    veredicto: "brecha_confirmada",
    resumen: "Hay brecha: en Wikipedia se lee 25,0× más en inglés.",
    etapa: { etapa: "acelerando", motivo: null, fecha_referencia: "2026-09-30", version: "stages-v1", calibrado: false },
    comparaciones: [
      {
        fuente: "wikimedia",
        fuente_validada: true,
        metrica: "wiki_views_total",
        unidad: "views",
        ingles: { idioma: "en", estado: "medido", valor: 9800, ambitos: [] },
        espanol: { idioma: "es", estado: "medido", valor: 392, ambitos: [] },
        razon: 25,
        resultado: "brecha",
        explicacion: "9800 visitas en inglés frente a 392 en español en 7 días: 25,0× más en inglés.",
        tendencia: null,
      },
      {
        fuente: "google_trends_rss",
        fuente_validada: true,
        metrica: "gtr_presence_share",
        unidad: "ratio",
        ingles: {
          idioma: "en",
          estado: "medido",
          valor: 1,
          ambitos: [{ ambito: "US", valor: 1, crecimiento: null, motivo: null, capturas_con_tema: 7, capturas_conocidas: 7 }],
        },
        espanol: { idioma: "es", estado: "sin_medicion", valor: null, ambitos: [] },
        razon: null,
        resultado: "sin_medicion_espanol",
        explicacion: "Aparece en 7 de 7 capturas de EE. UU.; no hay capturas de Latinoamérica en la ventana.",
        tendencia: null,
      },
    ],
    notas: [],
    ...overrides,
  };
}

export function gapPage(items: GapOut[] = [gap()], overrides: Partial<GapPage> = {}): GapPage {
  const counts: Record<string, number> = { brecha_confirmada: 0, brecha_por_confirmar: 0, senales_mixtas: 0, sin_brecha: 0, datos_insuficientes: 0 };
  for (const item of items) counts[item.veredicto] = (counts[item.veredicto] ?? 0) + 1;
  return {
    data_mode: "real",
    fecha_referencia: "2026-09-30",
    version: "brechas-v1",
    calibrado: false,
    total: items.length,
    limite: 100,
    desplazamiento: 0,
    por_veredicto: counts,
    items,
    limitaciones: ["Reglas brechas-v1 provisionales y no calibradas con datos reales."],
    ...overrides,
  };
}

export function context(overrides: Partial<CreativeContext> = {}): CreativeContext {
  return {
    origen: "brecha",
    data_mode: "real",
    tema_id: TOPIC,
    tema_nombre: "Tema Eta",
    fecha_referencia: "2026-09-30",
    etapa: "acelerando",
    etapa_calibrada: false,
    veredicto_brecha: "brecha_confirmada",
    resumen_brecha: "Hay brecha.",
    hechos: [{ clave: "comparacion:wikimedia", texto: "Wikipedia: 9800 visitas en inglés frente a 392.", fuente: "CREAR · brechas-v1" }],
    limitaciones: ["La etapa usa reglas provisionales sin calibrar."],
    ...overrides,
  };
}

const IDS: Record<Approach, string> = {
  educativo: "prp_000000000000000a",
  controversial: "prp_000000000000000b",
  narrativo: "prp_000000000000000c",
};

export function proposal(approach: Approach = "educativo", overrides: Partial<ProposalOut> = {}): ProposalOut {
  const id = overrides.id ?? IDS[approach];
  return {
    id,
    lote_id: "lot_0000000000000001",
    raiz_id: IDS[approach],
    padre_id: null,
    version: 1,
    data_mode: "real",
    origen: "brecha",
    tema_id: TOPIC,
    tema_nombre: "Tema Eta",
    enfoque: approach,
    audiencia: "general_latam",
    audiencia_detalle: null,
    plataforma: "tiktok",
    pais: "MX",
    indicacion: null,
    cambios: [],
    contenido: {
      titulo: `Título ${approach}`,
      gancho: `Gancho ${approach}`,
      idea_central: "Idea central.",
      estructura: ["0–3 s · Gancho", "3–15 s · Desarrollo"],
      formato: "Video vertical de 45 a 60 segundos para TikTok.",
      llamado_a_la_accion: "Comenta.",
      adaptacion_latam: ["Ejemplos de México."],
      palabras_clave: ["Tema Eta"],
      precauciones: ["Verifica cada dato."],
    },
    motor: "plantillas-v1",
    modelo: null,
    aviso_motor: null,
    cifras_sin_respaldo: [],
    creado: "2026-10-17T12:00:00Z",
    ...overrides,
  };
}

export function batch(overrides: Partial<BatchOut> = {}): BatchOut {
  return {
    lote_id: "lot_0000000000000001",
    data_mode: "real",
    contexto: context(),
    propuestas: [proposal("educativo"), proposal("controversial"), proposal("narrativo")],
    ...overrides,
  };
}

export function proposalPage(items: ProposalOut[] = []): ProposalPage {
  return { data_mode: "real", total: items.length, limite: 100, desplazamiento: 0, items };
}
