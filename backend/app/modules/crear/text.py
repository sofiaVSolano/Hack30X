"""Formato de cifras y fechas en español para los textos de CREAR.

Todas las cifras que CREAR escribe pasan por aquí (punto de miles desde cinco cifras, como la
oficina; coma decimal), para que la verificación de cifras de las propuestas las reconozca.
"""

from datetime import date

_MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def fmt_int(value: float) -> str:
    """1295 -> «1295»; 24500 -> «24.500» (como Intl.NumberFormat("es") en la oficina)."""
    number = round(value)
    text = str(abs(number))
    if len(text) >= 5:
        groups = []
        while text:
            groups.insert(0, text[-3:])
            text = text[:-3]
        text = ".".join(groups)
    return f"-{text}" if number < 0 else text


def fmt_decimal(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def fmt_ratio(value: float) -> str:
    """19.46 -> «19,5×»."""
    return f"{fmt_decimal(value)}×"


def fmt_pct(fraction: float) -> str:
    """Tasa como fracción -> porcentaje con signo: 0.4015 -> «+40 %»; -0.05 -> «-5 %»."""
    pct = round(fraction * 100)
    return f"+{pct} %" if pct > 0 else f"{pct} %"


def fmt_day(day: date) -> str:
    return f"{day.day} de {_MONTHS[day.month - 1]} de {day.year}"


def sentence(text: str) -> str:
    """Cierra una frase con punto sin duplicarlo («…en EE. UU.» no termina en «..»)."""
    return text if text.endswith((".", "…", "?", "!")) else f"{text}."


def join_es(items: list[str]) -> str:
    """["a", "b", "c"] -> «a, b y c»."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} y {items[-1]}"
