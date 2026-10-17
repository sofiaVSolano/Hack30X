from datetime import UTC, datetime


def format_utc(moment: datetime) -> str:
    """Devuelve RFC 3339 en UTC con sufijo ``Z`` y precisión de segundos."""
    if moment.tzinfo is None:
        raise ValueError("Se requiere una fecha con zona horaria")
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
