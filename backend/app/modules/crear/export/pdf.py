"""Documento PDF de un lote de propuestas: el entregable para el equipo de contenido.

Diseño (misma identidad que la oficina: azul noche y señal lima):

- portada: tarjeta con el tema, tarjetas de resumen (veredicto de brecha, etapa, fecha de los
  datos y motor), las tres propuestas de un vistazo y los datos de DETECTAR que se usaron;
- una página por propuesta (su versión más reciente), con un color por enfoque: ficha de
  plataforma, audiencia y país, gancho destacado, guion por tiempos, adaptación a
  Latinoamérica, palabras clave y precauciones;
- si los datos son simulados, cada página lo advierte.

Usa ReportLab (extra opcional ``crear``) con las fuentes estándar del PDF, que solo admiten
Windows-1252: el texto se normaliza a ese juego de caracteres antes de escribirlo.
"""

import io
import unicodedata
from collections import defaultdict
from datetime import datetime
from xml.sax.saxutils import escape

from app.modules.crear.catalog import (
    APPROACHES,
    AUDIENCES,
    BATCH_APPROACHES,
    PLATFORMS,
    Approach,
    country_name,
)
from app.modules.crear.context import STAGE_LABELS, CreativeContext, Origin
from app.modules.crear.storage.models import Proposal
from app.modules.crear.text import fmt_day
from app.modules.detectar.storage.models import DataMode

ORIGIN_LABELS = {
    Origin.BRECHA: "Brecha inglés–español",
    Origin.TEMA: "Tema detectado por DETECTAR",
    Origin.MANUAL: "Tema escrito a mano",
}
VERDICT_LABELS = {
    "brecha_confirmada": "Brecha confirmada",
    "brecha_por_confirmar": "Brecha por confirmar",
    "senales_mixtas": "Señales mixtas",
    "sin_brecha": "Sin brecha",
    "datos_insuficientes": "Datos insuficientes",
}
ENGINE_LABELS = {"plantillas-v1": "Plantillas (sin IA)", "claude": "Claude"}
CHANGE_LABELS = {
    "enfoque": "enfoque",
    "audiencia": "audiencia",
    "plataforma": "plataforma",
    "pais": "país",
    "indicacion": "indicación",
    "nueva_variante": "otra variante",
}
SIMULATED_WARNING = (
    "DATOS SIMULADOS DE DEMOSTRACIÓN: el tema y sus cifras son inventados y no describen hechos reales."
)

# Paleta: tinta y superficies para impresión; azul noche y lima solo en la portada.
INK, MUTED, LINE, SOFT = "#14202B", "#5B6B7C", "#DCE3EA", "#F4F7FA"
NIGHT, LIME, NIGHT_TEXT = "#0F1A26", "#B6E36B", "#C9D6E2"
APPROACH_COLORS: dict[Approach, tuple[str, str]] = {
    Approach.EDUCATIVO: ("#1D5FD6", "#EAF1FE"),
    Approach.CONTROVERSIAL: ("#C2410C", "#FDF0E8"),
    Approach.NARRATIVO: ("#7C3AED", "#F3EDFE"),
}
VERDICT_COLORS = {
    "brecha_confirmada": ("#15803D", "#E7F6EC"),
    "brecha_por_confirmar": ("#1D4ED8", "#E8EFFE"),
    "senales_mixtas": ("#B45309", "#FEF3E2"),
}
NEUTRAL = ("#334155", SOFT)

_REPLACEMENTS = {"≥": ">=", "≤": "<=", "→": "->", "←": "<-", " ": " ", " ": " ", " ": " "}


class PdfUnavailableError(RuntimeError):
    """ReportLab no está instalado (extra opcional «crear»)."""


def _plain(text: str) -> str:
    """Texto representable con las fuentes estándar del PDF (Windows-1252)."""
    out: list[str] = []
    for char in text:
        char = _REPLACEMENTS.get(char, char)
        try:
            char.encode("cp1252")
            out.append(char)
        except UnicodeEncodeError:
            # Letras con diacríticos poco comunes pierden el diacrítico; emojis y símbolos se omiten.
            out.append(unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode())
    return "".join(out)


def _p(text: str) -> str:
    """Texto seguro para un Paragraph de ReportLab (que interpreta marcado XML)."""
    return escape(_plain(text))


def latest_versions(proposals: list[Proposal]) -> list[tuple[Proposal, int]]:
    """Versión más reciente de cada propuesta y su número de versiones.

    Se ordenan por el enfoque de su PRIMERA versión (como las tarjetas de la oficina): una versión
    regenerada con otro enfoque no cambia de lugar.
    """
    by_root: dict[str, list[Proposal]] = defaultdict(list)
    for proposal in proposals:
        by_root[proposal.root_id].append(proposal)
    ordered = sorted(
        by_root.values(), key=lambda items: BATCH_APPROACHES.index(min(items, key=lambda p: p.version).approach)
    )
    return [(max(items, key=lambda p: p.version), len(items)) for items in ordered]


def _split_step(step: str) -> tuple[str, str]:
    """«0–3 s · Gancho…» -> («0–3 s», «Gancho…»). Sin marca de tiempo, la columna queda vacía."""
    slot, separator, text = step.partition(" · ")
    return (slot, text) if separator and len(slot) <= 24 else ("", step)


def batch_pdf(
    proposals: list[Proposal], context: CreativeContext, *, generated_at: datetime, compress: bool = True
) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            KeepTogether,
            ListFlowable,
            ListItem,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        raise PdfUnavailableError("Instale el extra «crear» del backend para exportar PDF.") from exc

    c = colors.HexColor
    width = A4[0] - 36 * mm  # ancho útil con márgenes de 18 mm
    simulated = context.data_mode is DataMode.SIMULATED

    def style(name: str, **kw: object) -> ParagraphStyle:
        base: dict[str, object] = {"fontName": "Helvetica", "fontSize": 10, "leading": 14.5, "textColor": c(INK)}
        return ParagraphStyle(name, **{**base, **kw})

    styles = {
        "body": style("body"),
        "small": style("small", fontSize=8.5, leading=12, textColor=c(MUTED)),
        "label": style("label", fontSize=7.5, leading=10, textColor=c(MUTED)),
        "value": style("value", fontName="Helvetica-Bold", fontSize=10.5, leading=13.5),
        "h2": style("h2", fontName="Helvetica-Bold", fontSize=14, leading=18, spaceBefore=6, spaceAfter=6),
        "h3": style("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=3),
        "item": style("item", fontSize=9.2, leading=12.8),
        "hero_eyebrow": style("hero_eyebrow", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=c(LIME)),
        "hero_title": style("hero_title", fontName="Helvetica-Bold", fontSize=27, leading=31, textColor=colors.white),
        "hero_sub": style("hero_sub", fontSize=11, leading=15.5, textColor=c(NIGHT_TEXT)),
        "title": style("title", fontName="Helvetica-Bold", fontSize=17, leading=21),
        "hook": style("hook", fontName="Helvetica-Oblique", fontSize=12.5, leading=17),
        "quote": style("quote", fontName="Helvetica-Bold", fontSize=34, leading=34, textColor=c("#C47F17")),
        "cell": style("cell", fontSize=9.2, leading=12.8),
        "chip": style("chip", fontName="Helvetica-Bold", fontSize=8.5, leading=16),
    }

    def para(text: str, key: str = "body", **overrides: object) -> Paragraph:
        st = styles[key] if not overrides else ParagraphStyle(f"{key}-x", parent=styles[key], **overrides)
        return Paragraph(_p(text), st)

    def card(
        rows: list[list[object]],
        col_widths: list[float],
        background: str,
        *,
        border: str | None = None,
        radius: float = 6,
        padding: float = 10,
        extra: list[tuple] | None = None,
        row_heights: list[float] | None = None,
    ) -> Table:
        table = Table(rows, colWidths=col_widths, rowHeights=row_heights, hAlign="LEFT")
        commands: list[tuple] = [
            ("BACKGROUND", (0, 0), (-1, -1), c(background)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), padding),
            ("TOPPADDING", (0, 0), (-1, -1), padding * 0.7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), padding * 0.7),
            ("ROUNDEDCORNERS", [radius] * 4),
        ]
        if border:
            commands.append(("LINEBEFORE", (0, 0), (0, -1), 3, c(border)))
        table.setStyle(TableStyle(commands + (extra or [])))
        return table

    def bullets(items: list[str], color: str = MUTED, key: str = "body") -> ListFlowable:
        return ListFlowable(
            [ListItem(para(item, key), leftIndent=12) for item in items],
            bulletType="bullet",
            start="•",
            leftIndent=12,
            bulletColor=c(color),
            bulletFontName="Helvetica-Bold",
            bulletFontSize=10,
        )

    def chips(words: list[str], color: str, tint: str) -> Paragraph:
        """Palabras clave como etiquetas en línea: el párrafo las reparte en las líneas que hagan falta."""
        tags = [
            f'<span backColor="{tint}" color="{color}">&nbsp;&nbsp;{_p(word)}&nbsp;&nbsp;</span>' for word in words
        ]
        return Paragraph("&nbsp;&nbsp; ".join(tags), styles["chip"])

    latest = latest_versions(proposals)
    engines = sorted({ENGINE_LABELS.get(p.engine, p.engine) + (f" · {p.model}" if p.model else "") for p in proposals})
    verdict = context.veredicto_brecha.value if context.veredicto_brecha else ""
    verdict_color = VERDICT_COLORS.get(verdict, NEUTRAL)

    # --- portada ---------------------------------------------------------------------------------
    story: list[object] = []
    hero = Table(
        [
            [para("HACK 30X  ·  CREAR  ·  PROPUESTAS DE CONTENIDO", "hero_eyebrow")],
            [para(context.tema_nombre, "hero_title")],
            [
                para(
                    f"{ORIGIN_LABELS[context.origen]}. Tres propuestas con enfoques distintos (educativo, "
                    "controversial y narrativo), listas para producir y publicar.",
                    "hero_sub",
                )
            ],
        ],
        colWidths=[width],
        hAlign="LEFT",
    )
    hero.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), c(NIGHT)),
                ("ROUNDEDCORNERS", [10, 10, 10, 10]),
                ("LEFTPADDING", (0, 0), (-1, -1), 22),
                ("RIGHTPADDING", (0, 0), (-1, -1), 22),
                ("TOPPADDING", (0, 0), (-1, 0), 22),
                ("TOPPADDING", (0, 1), (-1, -1), 6),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 24),
            ]
        )
    )
    story += [hero, Spacer(1, 12)]

    def kpi(label: str, value: str, accent: tuple[str, str]) -> Table:
        return card(
            [[para(label, "label")], [para(value, "value", textColor=c(accent[0]))]],
            [width / 4 - 6],
            accent[1],
            radius=6,
            padding=9,
            extra=[("LINEABOVE", (0, 0), (-1, 0), 2.5, c(accent[0]))],
            row_heights=[22, 40],  # misma altura en las cuatro tarjetas (valores de hasta dos líneas)
        )

    if context.etapa:
        stage = STAGE_LABELS[context.etapa] + ("" if context.etapa_calibrada else " (provisional)")
    else:
        stage = "Sin etapa"
    data_date = fmt_day(context.fecha_referencia) if context.fecha_referencia else "Sin datos"
    kpis = Table(
        [
            [
                kpi("Brecha inglés–español", VERDICT_LABELS.get(verdict, "Sin análisis"), verdict_color),
                kpi("Etapa en DETECTAR", stage, NEUTRAL),
                kpi("Datos de DETECTAR al", data_date, NEUTRAL),
                kpi("Motor de generación", ", ".join(engines), NEUTRAL),
            ]
        ],
        colWidths=[width / 4] * 4,
        hAlign="LEFT",
    )
    kpis.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story += [kpis, Spacer(1, 14), para("Las tres propuestas", "h2")]

    overview_rows: list[list[object]] = [[para("Enfoque", "label"), para("Título", "label"), para("Plataforma", "label")]]
    overview_style: list[tuple] = [
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, c(LINE)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]
    for row, (proposal, _versions) in enumerate(latest, start=1):
        accent = APPROACH_COLORS[proposal.approach][0]
        overview_rows.append(
            [
                para(APPROACHES[proposal.approach].name, "value", textColor=c(accent), fontSize=10),
                para(str(proposal.content["titulo"]), "cell"),
                para(PLATFORMS[proposal.platform].name, "cell"),
            ]
        )
        overview_style.append(("LINEBEFORE", (0, row), (0, row), 3, c(accent)))
    overview = Table(overview_rows, colWidths=[32 * mm, width - 70 * mm, 38 * mm], hAlign="LEFT")
    overview.setStyle(TableStyle(overview_style))
    story += [overview, Spacer(1, 14)]

    facts = [fact.texto for fact in context.hechos] or [
        "No hay datos de DETECTAR para este tema: las propuestas no citan cifras."
    ]
    data_card = card([[bullets(facts, color=verdict_color[0])]], [width], SOFT, radius=8, padding=12)
    story.append(KeepTogether([para("Lo que dicen los datos", "h2"), data_card]))
    if context.limitaciones:
        story += [para("Limitaciones", "h3"), bullets(context.limitaciones, key="small")]
    story += [
        Spacer(1, 8),
        para(
            "Antes de publicar: verifique cada dato con una fuente confiable. Las cifras citadas provienen de "
            "DETECTAR; las marcadas como «sin respaldo» no se encontraron en sus datos. Documento generado el "
            f"{fmt_day(generated_at.date())} a las {generated_at:%H:%M} UTC.",
            "small",
        ),
    ]

    # --- una página por propuesta ------------------------------------------------------------------
    total = len(latest)
    for number, (proposal, versions) in enumerate(latest, start=1):
        content = proposal.content
        accent, tint = APPROACH_COLORS[proposal.approach]
        approach = APPROACHES[proposal.approach].name
        story.append(PageBreak())

        header = card(
            [
                [para(f"Propuesta {number} de {total} · Enfoque {approach.lower()}", "value", textColor=c(accent), fontSize=9.5)],
                [para(str(content["titulo"]), "title")],
                [chips([str(w) for w in content["palabras_clave"]], accent, "#FFFFFF")],
            ],
            [width],
            tint,
            border=accent,
            radius=6,
            padding=12,
        )
        audience = AUDIENCES[proposal.audience].name + (f" ({proposal.audience_detail})" if proposal.audience_detail else "")
        version = f"{proposal.version} de {versions}" if versions > 1 else str(proposal.version)
        meta = Table(
            [
                [
                    [para("Plataforma", "label"), para(PLATFORMS[proposal.platform].name, "value", fontSize=9.5)],
                    [para("Audiencia", "label"), para(audience, "value", fontSize=9.5)],
                    [para("País", "label"), para(country_name(proposal.country), "value", fontSize=9.5)],
                    [para("Versión", "label"), para(version, "value", fontSize=9.5)],
                ]
            ],
            colWidths=[width * 0.27, width * 0.37, width * 0.2, width * 0.16],
            hAlign="LEFT",
        )
        meta.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), c(SOFT)),
                    ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                    ("LINEAFTER", (0, 0), (-2, -1), 1.5, colors.white),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story += [header, Spacer(1, 8), meta]
        if proposal.version > 1 and proposal.changes:
            changes = ", ".join(CHANGE_LABELS.get(change, change) for change in proposal.changes)
            story += [Spacer(1, 4), para(f"Cambios frente a la versión anterior: {changes}.", "small")]

        hook = card(
            [[para("“", "quote"), para(str(content["gancho"]), "hook")]],
            [12 * mm, width - 12 * mm],
            "#FFF7E8",
            radius=8,
            padding=12,
            extra=[("LEFTPADDING", (1, 0), (1, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 0)],
        )
        story += [Spacer(1, 10), hook]

        left = [para("Idea central", "h3"), para(str(content["idea_central"]))]
        right = [
            para("Formato", "h3"),
            para(str(content["formato"])),
            para("Llamado a la acción", "h3"),
            para(str(content["llamado_a_la_accion"])),
        ]
        columns = Table([[left, right]], colWidths=[width * 0.55, width * 0.45], hAlign="LEFT")
        columns.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (0, 0), 0),
                    ("LEFTPADDING", (1, 0), (1, 0), 14),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("LINEBEFORE", (1, 0), (1, 0), 0.5, c(LINE)),
                ]
            )
        )
        story.append(columns)

        steps = [_split_step(str(step)) for step in content["estructura"]]
        script = Table(
            [
                [para(slot or str(i), "value", textColor=c(accent), fontSize=9.5), para(text, "cell")]
                for i, (slot, text) in enumerate(steps, start=1)
            ],
            colWidths=[30 * mm, width - 30 * mm],
            hAlign="LEFT",
        )
        script.setStyle(
            TableStyle(
                [
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, c(SOFT)]),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, c(LINE)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story += [para("Estructura del guion", "h3"), script]

        half = (width - 10) / 2
        adaptation = card(
            [[para("Adaptación a Latinoamérica", "h3", spaceBefore=0)],
             [bullets([str(x) for x in content["adaptacion_latam"]], color="#15803D", key="item")]],
            [half], "#EEF8EA", radius=8,
        )
        cautions = card(
            [[para("Precauciones", "h3", spaceBefore=0)],
             [bullets([str(x) for x in content["precauciones"]], color="#B45309", key="item")]],
            [half], "#FFF6E5", radius=8,
        )
        pair = Table([[adaptation, "", cautions]], colWidths=[half, 10, half], hAlign="LEFT")
        pair.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), *[(k, (0, 0), (-1, -1), 0) for k in ("LEFTPADDING", "RIGHTPADDING", "TOPPADDING", "BOTTOMPADDING")]]))
        story += [Spacer(1, 10), pair]
        if proposal.unsupported_figures:
            warning = (
                "Cifras sin respaldo en DETECTAR: " + ", ".join(proposal.unsupported_figures)
                + ". Verifíquelas con una fuente o quítelas antes de publicar."
            )
            story += [
                Spacer(1, 8),
                card([[para(warning, "body", textColor=c("#991B1B"))]], [width], "#FDECEC", border="#B91C1C", radius=6),
            ]
        if proposal.engine_notice:
            story += [Spacer(1, 6), para(f"Nota del motor: {proposal.engine_notice}", "small")]

    topic = _plain(context.tema_nombre)

    def decorate(canvas, doc) -> None:  # type: ignore[no-untyped-def]
        canvas.saveState()
        page_w, page_h = A4
        if simulated:
            canvas.setFillColor(c("#EDE4FF"))
            canvas.rect(0, page_h - 6 * mm, page_w, 6 * mm, stroke=0, fill=1)
            canvas.setFillColor(c("#4B2A8A"))
            canvas.setFont("Helvetica-Bold", 7.5)
            canvas.drawCentredString(page_w / 2, page_h - 4 * mm, _plain(SIMULATED_WARNING))
        if doc.page > 1:
            canvas.setFont("Helvetica-Bold", 8)
            canvas.setFillColor(c(INK))
            canvas.drawString(18 * mm, page_h - 11 * mm, "HACK 30X · CREAR")
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(c(MUTED))
            canvas.drawRightString(page_w - 18 * mm, page_h - 11 * mm, topic[:80])
            canvas.setStrokeColor(c(LINE))
            canvas.setLineWidth(0.6)
            canvas.line(18 * mm, page_h - 13 * mm, page_w - 18 * mm, page_h - 13 * mm)
        canvas.setStrokeColor(c(LINE))
        canvas.setLineWidth(0.6)
        canvas.line(18 * mm, 13 * mm, page_w - 18 * mm, 13 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(c(MUTED))
        canvas.drawString(18 * mm, 9 * mm, "Generado por CREAR a partir de los datos de DETECTAR. Verifique antes de publicar.")
        canvas.drawRightString(page_w - 18 * mm, 9 * mm, f"Página {doc.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=_plain(f"Propuestas de contenido: {context.tema_nombre}"),
        author="HACK 30X · CREAR",
        subject="Propuestas de contenido generadas a partir de DETECTAR",
        pageCompression=1 if compress else 0,
    )
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()
