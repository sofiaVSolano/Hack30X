"""Motor ``plantillas-v1``: propuestas deterministas, sin red ni modelos de lenguaje.

Se usa cuando no hay credencial de Claude (o Claude falla) y en las pruebas. Compone cada
propuesta con piezas fijas por enfoque y formato, el nombre del tema, la audiencia, la
plataforma y el país, y solo cita cifras copiadas de los hechos del contexto.

Las variantes de título, gancho y llamado a la acción se eligen con una semilla derivada de los
parámetros y de la versión: la misma solicitud produce siempre el mismo resultado y una versión
nueva puede variar. Las variantes que afirman algo (por ejemplo, «en español casi nadie lo
explica») solo se usan si el contexto lo respalda.
"""

import hashlib
import random
from dataclasses import dataclass

from app.modules.crear.catalog import (
    APPROACHES,
    AUDIENCES,
    BATCH_APPROACHES,
    PLATFORMS,
    Approach,
    Format,
    country_name,
)
from app.modules.crear.context import CreativeContext, Origin
from app.modules.crear.gaps.rules import Verdict
from app.modules.crear.generation.base import (
    CreativeParams,
    PreviousProposal,
    ProposalContent,
    normalize,
)
from app.modules.detectar.storage.models import DataMode, TrendStage

ENGINE_ID = "plantillas-v1"

# Cinco momentos por formato; cada enfoque aporta su contenido para cada momento.
SLOTS: dict[Format, tuple[str, str, str, str, str]] = {
    Format.VIDEO_CORTO: ("0–3 s", "3–15 s", "15–35 s", "35–50 s", "50–60 s"),
    Format.VIDEO_LARGO: ("0:00", "0:45", "3:00", "6:00", "9:00"),
    Format.CARRUSEL: ("Diapositiva 1", "Diapositivas 2–3", "Diapositivas 4–5", "Diapositiva 6", "Diapositiva 7"),
    Format.HILO: ("1/7", "2/7 y 3/7", "4/7 y 5/7", "6/7", "7/7"),
    Format.PUBLICACION: ("Primera línea", "Párrafo 1", "Párrafo 2", "Párrafo 3", "Cierre"),
    Format.AUDIO: ("Intro (1 min)", "Bloque 1 (5 min)", "Bloque 2 (6 min)", "Bloque 3 (5 min)", "Cierre (2 min)"),
    Format.ARTICULO: ("Introducción", "Sección 1", "Sección 2", "Sección 3", "Conclusión"),
}

BEATS: dict[Approach, tuple[str, str, str, str, str]] = {
    Approach.EDUCATIVO: (
        "El gancho: la pregunta que la pieza va a responder.",
        "Qué es {tema}, en una frase y sin tecnicismos.",
        "Por qué se habla de esto ahora. {dato}",
        "Qué cambia para {audiencia} {en_pais}, con un ejemplo cercano.",
        "La idea para recordar y el llamado a la acción.",
    ),
    Approach.CONTROVERSIAL: (
        "Una afirmación provocadora sobre {tema}, sin atacar a personas ni a grupos.",
        "La postura a favor, con su mejor argumento.",
        "La postura en contra, con su mejor argumento. {dato}",
        "Tu opinión, dicha claramente como opinión.",
        "La pregunta abierta: pide argumentos, no solo reacciones.",
    ),
    Approach.NARRATIVO: (
        "La escena inicial: una persona {en_pais}, un lugar y un momento concretos.",
        "El conflicto: qué cambió con {tema} y qué estaba en juego.",
        "El giro: lo que descubre sobre {tema}. {dato}",
        "El desenlace y la lección para {audiencia}.",
        "El cierre: invita a contar una experiencia parecida.",
    ),
}

# (texto, condición). Condiciones: "" siempre; "etapa": hay una etapa que se puede contar;
# "brecha": brecha confirmada; "ingles": el inglés lleva la delantera (confirmada, por
# confirmar o mixta).
TITLES: dict[Approach, tuple[tuple[str, str], ...]] = {
    Approach.EDUCATIVO: (
        ("{Tema}, explicado {tiempo}", ""),
        ("Qué es {tema} y por qué te importa", ""),
        ("{Tema}: lo esencial para entenderlo {en_pais}", ""),
        ("{Tema}: lo que se dice en inglés, explicado en español", "ingles"),
    ),
    Approach.CONTROVERSIAL: (
        ("¿{Tema} está sobrevalorado?", ""),
        ("{Tema}: a favor y en contra", ""),
        ("La pregunta incómoda sobre {tema}", ""),
        ("¿Por qué {tema} se discute tan poco en español?", "brecha"),
    ),
    Approach.NARRATIVO: (
        ("La historia detrás de {tema}", ""),
        ("Un día con {tema} {en_pais}", ""),
        ("{Tema}, contado desde {pais}", ""),
        ("{Tema}: de conversación en inglés a historia en español", "ingles"),
    ),
}

HOOKS: dict[Approach, tuple[tuple[str, str], ...]] = {
    Approach.EDUCATIVO: (
        ("¿Has oído hablar de «{tema}» y no sabes bien qué es? Te lo explico {tiempo}.", ""),
        ("Tres cosas que tienes que saber sobre «{tema}».", ""),
        ("«{tema}» {etapa}. Esto es lo que necesitas saber.", "etapa"),
        ("En inglés ya se habla mucho de «{tema}»; en español, mucho menos. Te lo explico.", "brecha"),
    ),
    Approach.CONTROVERSIAL: (
        ("Voy a decir algo sobre «{tema}» que no a todos les va a gustar.", ""),
        ("Hay dos bandos sobre «{tema}». Te explico los dos y tú decides.", ""),
        ("¿«{tema}» es una buena o una mala noticia para quienes viven {en_pais}?", ""),
        ("¿Por qué en inglés se habla tanto de «{tema}» y en español tan poco?", "brecha"),
    ),
    Approach.NARRATIVO: (
        ("Esta es la historia de alguien {en_pais} que se topó con «{tema}» sin buscarlo.", ""),
        ("Imagina que mañana «{tema}» cambia tu rutina. Así podría empezar todo.", ""),
        ("«{tema}» {etapa}. Pero todo empezó con una pregunta muy simple.", "etapa"),
        ("Mientras en inglés ya se hablaba de «{tema}», {en_pais} se hablaba poco de él. Hasta que…", "brecha"),
    ),
}

CTAS: dict[Approach, tuple[str, ...]] = {
    Approach.EDUCATIVO: (
        "Guarda {esta_pieza} para cuando alguien te pregunte qué es {tema}.",
        "Comparte {esta_pieza} con alguien que todavía no sabe qué es {tema}.",
    ),
    Approach.CONTROVERSIAL: (
        "¿A favor o en contra? Déjalo en los comentarios con un argumento, no solo con un emoji.",
        "Responde con tu postura y la razón más fuerte que tengas.",
    ),
    Approach.NARRATIVO: (
        "¿Te pasó algo parecido? Cuéntalo en los comentarios.",
        "Comparte {esta_pieza} con alguien que necesita escuchar esta historia.",
    ),
}

KEYWORD: dict[Approach, str] = {
    Approach.EDUCATIVO: "qué es {tema}",
    Approach.CONTROVERSIAL: "{tema} debate",
    Approach.NARRATIVO: "historia de {tema}",
}

STAGE_PHRASES: dict[TrendStage, str] = {
    TrendStage.EMERGENTE: "empieza a aparecer en las señales que sigue DETECTAR",
    TrendStage.ACELERANDO: "crece cada vez más rápido, según DETECTAR",
    TrendStage.PUNTO_MAXIMO: "está en su nivel más alto reciente, según DETECTAR",
}

_SHORT_TIME = {Format.VIDEO_CORTO: "en menos de un minuto"}

# Hechos que se muestran como «dato» de la pieza, por orden de preferencia.
_KEY_FACTS = ("comparacion:wikimedia", "comparacion:google_trends_rss", "etapa", "comparacion:gdelt")


@dataclass(frozen=True)
class _Vars:
    tema: str
    pais: str
    en_pais: str
    audiencia: str
    tiempo: str
    esta_pieza: str
    etapa: str
    dato: str

    def fill(self, template: str) -> str:
        values = {name: getattr(self, name) for name in self.__dataclass_fields__}
        values["Tema"] = self.tema[:1].upper() + self.tema[1:]
        return " ".join(template.format(**values).split())


def _seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:16], 16)


def _conditions(context: CreativeContext) -> set[str]:
    conditions = {""}
    if context.etapa in STAGE_PHRASES:
        conditions.add("etapa")
    if context.veredicto_brecha is Verdict.BRECHA_CONFIRMADA:
        conditions.add("brecha")
    if context.english_leads:
        conditions.add("ingles")
    return conditions


def _key_fact(context: CreativeContext) -> str | None:
    by_key = {fact.clave: fact.texto for fact in context.hechos}
    for key in _KEY_FACTS:
        if key in by_key:
            return by_key[key]
    return None


class TemplateEngine:
    id = ENGINE_ID
    model: str | None = None

    def generate_batch(self, context: CreativeContext, params: CreativeParams) -> dict[Approach, ProposalContent]:
        return {approach: self._compose(context, approach, params, version=1) for approach in BATCH_APPROACHES}

    def regenerate(
        self,
        context: CreativeContext,
        previous: PreviousProposal,
        approach: Approach,
        params: CreativeParams,
        instruction: str | None,
        version: int,
    ) -> ProposalContent:
        # Las plantillas no interpretan indicaciones libres; el generador lo avisa.
        return self._compose(context, approach, params, version=version)

    def _compose(self, context: CreativeContext, approach: Approach, params: CreativeParams, *, version: int) -> ProposalContent:
        platform = PLATFORMS[params.plataforma]
        audience = AUDIENCES[params.audiencia]
        country = country_name(params.pais)
        fact = _key_fact(context)
        values = _Vars(
            tema=context.tema_nombre,
            pais=country,
            en_pais=f"en {country}",
            audiencia=audience.phrase,
            tiempo=_SHORT_TIME.get(platform.format, "sin rodeos"),
            esta_pieza=platform.this_piece,
            etapa=STAGE_PHRASES.get(context.etapa, "") if context.etapa else "",
            dato=f"Dato de DETECTAR para mostrar: «{fact}»" if fact else "Usa solo datos que puedas verificar.",
        )
        rng = random.Random(_seed(context.tema_nombre, approach, params.plataforma, params.audiencia, params.pais, version))
        conditions = _conditions(context)

        def pick(options: tuple[tuple[str, str], ...]) -> str:
            eligible = [text for text, condition in options if condition in conditions]
            return values.fill(rng.choice(eligible))

        title = pick(TITLES[approach])
        hook = pick(HOOKS[approach])
        structure = [f"{slot} · {values.fill(beat)}" for slot, beat in zip(SLOTS[platform.format], BEATS[approach], strict=True)]
        content = ProposalContent(
            titulo=title,
            gancho=hook,
            idea_central=self._idea(context, approach, values),
            estructura=structure,
            formato=f"{platform.format_text} para {platform.name}. {'. '.join(platform.guidelines)}.",
            llamado_a_la_accion=values.fill(rng.choice(CTAS[approach])),
            adaptacion_latam=self._adaptation(context, params, values, audience.tone),
            palabras_clave=[
                context.tema_nombre,
                values.fill(KEYWORD[approach]),
                f"{context.tema_nombre} en español",
                country,
            ],
            precauciones=self._cautions(context, approach, platform.format),
        )
        return normalize(content)

    @staticmethod
    def _idea(context: CreativeContext, approach: Approach, values: _Vars) -> str:
        ideas = {
            Approach.EDUCATIVO: (
                "Explicar {tema} de forma sencilla para {audiencia}: qué es, por qué está dando de "
                "qué hablar y qué significa para quienes viven {en_pais}."
            ),
            Approach.CONTROVERSIAL: (
                "Abrir un debate respetuoso sobre {tema}: la mejor versión de cada postura, hechos "
                "separados de opiniones y una invitación a que {audiencia} opine con argumentos."
            ),
            Approach.NARRATIVO: (
                "Contar {tema} con una historia cercana {en_pais}: un personaje, un conflicto, un giro "
                "y una lección que {audiencia} pueda reconocer."
            ),
        }
        idea = values.fill(ideas[approach])
        if context.veredicto_brecha in (Verdict.BRECHA_CONFIRMADA, Verdict.SENALES_MIXTAS):
            idea += f" Según DETECTAR, el tema recibe más atención en inglés: la pieza lo adapta a {values.pais}."
        elif context.veredicto_brecha is Verdict.BRECHA_POR_CONFIRMAR:
            idea += f" Hay atención en inglés y el lado en español aún no se midió: la pieza prepara una versión para {values.pais}."
        return idea

    @staticmethod
    def _adaptation(context: CreativeContext, params: CreativeParams, values: _Vars, tone: str) -> list[str]:
        items = [f"Usa ejemplos, nombres y lugares reconocibles {values.en_pais}."]
        if params.pais:
            items.append(f"Habla como se habla en {values.pais}: revisa expresiones y evita las que no se entiendan allí.")
        else:
            items.append("Usa un español neutro y evita expresiones que solo se entiendan en un país.")
        if context.english_leads:
            items.append("La conversación está en inglés: traduce y contextualiza esas fuentes, cítalas y no copies su contenido.")
        items.append(f"Tono para {values.audiencia}: {tone[:1].lower()}{tone[1:]}")
        if params.audiencia_detalle:
            items.append(f"Piensa en esta audiencia concreta: {params.audiencia_detalle}.")
        return items

    @staticmethod
    def _cautions(context: CreativeContext, approach: Approach, platform_format: Format) -> list[str]:
        items = ["Verifica cada dato con una fuente confiable antes de publicarlo."]
        if context.data_mode is DataMode.SIMULATED:
            items.append("Datos de demostración: no presentes estas cifras ni el tema como reales.")
        if context.origen is Origin.MANUAL:
            items.append("Este tema no tiene datos de DETECTAR: no afirmes que es tendencia sin comprobarlo.")
        elif context.etapa_calibrada is False:
            items.append("La etapa de DETECTAR usa reglas provisionales: preséntala como señal, no como certeza.")
        if approach is Approach.CONTROVERSIAL:
            items.extend(("Separa hechos de opiniones y dilo en voz alta.", "Debate ideas: no ataques a personas ni a grupos."))
        elif approach is Approach.NARRATIVO:
            items.append("Si la historia es ficticia o una recreación, acláralo.")
        else:
            items.append("Cita las fuentes en pantalla o en la descripción.")
        if platform_format in (Format.VIDEO_CORTO, Format.VIDEO_LARGO, Format.AUDIO):
            items.append("Usa música e imágenes con licencia.")
        return items


def describe() -> str:
    names = ", ".join(info.name.lower() for info in APPROACHES.values())
    return f"Plantillas deterministas ({names}); no requieren red ni credenciales."
