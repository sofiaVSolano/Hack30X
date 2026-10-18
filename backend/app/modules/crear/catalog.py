"""Catálogo del laboratorio creativo: enfoques, plataformas, audiencias y países.

Es la única fuente de verdad de estas opciones: la API las publica (``GET /opciones``), los
motores de generación las usan y la oficina las muestra. Añadir una opción aquí basta para
que aparezca en todas partes.
"""

from dataclasses import dataclass
from enum import StrEnum


class Approach(StrEnum):
    EDUCATIVO = "educativo"
    CONTROVERSIAL = "controversial"
    NARRATIVO = "narrativo"


# Orden fijo de las tres propuestas de un lote (RF-09).
BATCH_APPROACHES = (Approach.EDUCATIVO, Approach.CONTROVERSIAL, Approach.NARRATIVO)


class Platform(StrEnum):
    TIKTOK = "tiktok"
    REELS = "instagram_reels"
    SHORTS = "youtube_shorts"
    YOUTUBE = "youtube"
    CARRUSEL = "instagram_carrusel"
    HILO_X = "x_hilo"
    LINKEDIN = "linkedin"
    PODCAST = "podcast"
    BLOG = "blog"


class Format(StrEnum):
    """Familia de formato: decide la forma de la estructura (tiempos, diapositivas, bloques)."""

    VIDEO_CORTO = "video_corto"
    VIDEO_LARGO = "video_largo"
    CARRUSEL = "carrusel"
    HILO = "hilo"
    PUBLICACION = "publicacion"
    AUDIO = "audio"
    ARTICULO = "articulo"


@dataclass(frozen=True)
class ApproachInfo:
    id: Approach
    name: str
    description: str
    goal: str


@dataclass(frozen=True)
class PlatformInfo:
    id: Platform
    name: str
    format: Format
    format_text: str
    # La pieza con su demostrativo, para textos como «Guarda este video».
    this_piece: str
    guidelines: tuple[str, ...]


@dataclass(frozen=True)
class AudienceInfo:
    id: str
    name: str
    # Cómo se nombra dentro de una frase: «explicar el tema para {phrase}».
    phrase: str
    description: str
    tone: str


APPROACHES: dict[Approach, ApproachInfo] = {
    Approach.EDUCATIVO: ApproachInfo(
        Approach.EDUCATIVO,
        "Educativo",
        "Explica qué es, por qué importa y qué hacer con ello.",
        "que la audiencia entienda el tema y se quede con una idea útil",
    ),
    Approach.CONTROVERSIAL: ApproachInfo(
        Approach.CONTROVERSIAL,
        "Controversial",
        "Abre un debate con argumentos de ambos lados, sin desinformar ni atacar a nadie.",
        "provocar una conversación respetuosa con posturas contrapuestas",
    ),
    Approach.NARRATIVO: ApproachInfo(
        Approach.NARRATIVO,
        "Narrativo",
        "Cuenta una historia con personaje, conflicto, giro y desenlace.",
        "conectar emocionalmente a través de una historia",
    ),
}

PLATFORMS: dict[Platform, PlatformInfo] = {
    info.id: info
    for info in (
        PlatformInfo(
            Platform.TIKTOK, "TikTok", Format.VIDEO_CORTO, "Video vertical de 45 a 60 segundos", "este video",
            ("Gancho en los primeros 3 segundos", "Subtítulos en pantalla", "Una sola idea por video"),
        ),
        PlatformInfo(
            Platform.REELS, "Instagram Reels", Format.VIDEO_CORTO, "Reel vertical de 30 a 60 segundos", "este reel",
            ("Gancho visual en el primer segundo", "Texto en pantalla legible sin sonido", "Portada clara para la cuadrícula"),
        ),
        PlatformInfo(
            Platform.SHORTS, "YouTube Shorts", Format.VIDEO_CORTO, "Short vertical de hasta 60 segundos", "este short",
            ("Gancho inmediato", "Ritmo sin pausas", "Cierre que invite a ver más del canal"),
        ),
        PlatformInfo(
            Platform.YOUTUBE, "YouTube (video largo)", Format.VIDEO_LARGO, "Video horizontal de 8 a 12 minutos", "este video",
            ("Título y miniatura que prometan algo concreto", "Capítulos con marcas de tiempo", "Adelanta lo que viene para retener"),
        ),
        PlatformInfo(
            Platform.CARRUSEL, "Carrusel de Instagram", Format.CARRUSEL, "Carrusel de 7 diapositivas", "este carrusel",
            ("Portada con una promesa clara", "Una idea por diapositiva", "Última diapositiva para guardar o compartir"),
        ),
        PlatformInfo(
            Platform.HILO_X, "Hilo en X", Format.HILO, "Hilo de 7 publicaciones", "este hilo",
            ("La primera publicación debe funcionar sola", "Frases cortas", "Cierre con resumen y pregunta"),
        ),
        PlatformInfo(
            Platform.LINKEDIN, "LinkedIn", Format.PUBLICACION, "Publicación de 150 a 250 palabras", "esta publicación",
            ("Primera línea que invite a leer más", "Aprendizaje profesional concreto", "Pregunta final para comentar"),
        ),
        PlatformInfo(
            Platform.PODCAST, "Pódcast", Format.AUDIO, "Episodio de 15 a 20 minutos", "este episodio",
            ("Presenta la pregunta del episodio al inicio", "Bloques con transiciones claras", "Resumen final de 3 ideas"),
        ),
        PlatformInfo(
            Platform.BLOG, "Blog o newsletter", Format.ARTICULO, "Artículo de 800 a 1200 palabras", "este artículo",
            ("Título con la palabra clave", "Subtítulos fáciles de escanear", "Enlaces a las fuentes citadas"),
        ),
    )
}

AUDIENCES: dict[str, AudienceInfo] = {
    info.id: info
    for info in (
        AudienceInfo(
            "general_latam", "Público general latinoamericano", "el público general latinoamericano",
            "Personas adultas sin conocimientos previos del tema.",
            "Claro y cercano, sin tecnicismos; ejemplos cotidianos.",
        ),
        AudienceInfo(
            "jovenes_genz", "Jóvenes Gen Z", "jóvenes de la Gen Z",
            "Nativos digitales que consumen contenido corto.",
            "Ritmo rápido, humor y referencias de internet; frases cortas.",
        ),
        AudienceInfo(
            "profesionales", "Profesionales", "profesionales",
            "Personas que quieren aplicar el tema en su trabajo.",
            "Práctico y directo; impacto, decisiones y oportunidades concretas.",
        ),
        AudienceInfo(
            "emprendedores", "Emprendedores y pymes", "emprendedores y pymes",
            "Dueños de negocios pequeños y medianos.",
            "Orientado a la acción: clientes, costos y cómo aprovecharlo.",
        ),
        AudienceInfo(
            "estudiantes", "Estudiantes", "estudiantes",
            "Estudiantes de colegio y universidad.",
            "Didáctico; analogías, ejemplos y recursos para profundizar.",
        ),
        AudienceInfo(
            "familias", "Madres, padres y familias", "madres, padres y familias",
            "Adultos que toman decisiones para su hogar.",
            "Cercano y tranquilizador; consejos prácticos y seguros.",
        ),
        AudienceInfo(
            "curiosos_tecnologia", "Curiosos de ciencia y tecnología", "curiosos de la ciencia y la tecnología",
            "Personas que disfrutan entender cómo funcionan las cosas.",
            "Detalle técnico moderado, con analogías para lo complejo.",
        ),
    )
}

DEFAULT_AUDIENCE = "general_latam"

# Países hispanohablantes de Latinoamérica que se pueden elegir para adaptar el contenido.
COUNTRIES: dict[str, str] = {
    "AR": "Argentina",
    "BO": "Bolivia",
    "CL": "Chile",
    "CO": "Colombia",
    "CR": "Costa Rica",
    "DO": "República Dominicana",
    "EC": "Ecuador",
    "GT": "Guatemala",
    "MX": "México",
    "PA": "Panamá",
    "PE": "Perú",
    "PY": "Paraguay",
    "UY": "Uruguay",
    "VE": "Venezuela",
}


def country_name(code: str | None) -> str:
    """Nombre del país o «Latinoamérica» si no se eligió ninguno."""
    return COUNTRIES.get(code or "", "Latinoamérica")


def catalog_texts() -> list[str]:
    """Textos del catálogo con cifras propias (duraciones, palabras, edades).

    La verificación de cifras los admite: no son datos de tendencias sino pautas de formato.
    """
    texts: list[str] = []
    for platform in PLATFORMS.values():
        texts.extend((platform.format_text, *platform.guidelines))
    for audience in AUDIENCES.values():
        texts.extend((audience.description, audience.tone))
    return texts
