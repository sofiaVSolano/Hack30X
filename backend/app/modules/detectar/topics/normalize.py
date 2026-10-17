"""Normalización textual determinista (reglas ``topics-v1``).

Pasos, en orden:

1. Unicode NFKC (unifica formas compatibles, p. ej. anchos y ligaduras).
2. Guiones bajos a espacios (títulos de Wikipedia).
3. Se eliminan los acentos y diacríticos, EXCEPTO la tilde de la ñ
   ("México" -> "mexico", pero "año" no se convierte en "ano").
4. ``casefold`` (minúsculas sin distinción de mayúsculas, también para "ß").
5. Siglas con puntos entre letras sueltas pierden los puntos ("I.A." -> "ia",
   "U.S.A." -> "usa"); no afecta a "Dr." ni a números como "1.5".
6. Todo carácter que no sea letra, número o espacio pasa a espacio
   ("AC/DC" -> "ac dc", "covid-19" -> "covid 19").
7. Se colapsan los espacios y se recortan los extremos.

No hay eliminación de palabras vacías, raíces, plurales ni sinónimos: dos textos solo son
"iguales" si coinciden tras estos pasos. Por eso "IA" e "inteligencia artificial" NO se
unen automáticamente (se relacionan mediante un alias registrado).
"""

import re
import unicodedata

RULES_VERSION = "topics-v1"
MIN_KEY_LENGTH = 2
MAX_KEY_LENGTH = 300

_COMBINING_TILDE = chr(0x0303)  # tilde combinante (la de la ñ)
_NON_WORD = re.compile(r"[^\w\s]|_", re.UNICODE)
_SPACES = re.compile(r"\s+")
# Dos o más letras sueltas seguidas de punto, sin letra previa: "i.a." o "u.s.a".
_DOTTED_ACRONYM = re.compile(r"(?<![^\W\d_])((?:[^\W\d_]\.){1,}[^\W\d_])\.?(?![^\W\d_])")
# "Mercurio (planeta)" -> base "Mercurio": convención de desambiguación de Wikipedia.
_DISAMBIGUATION = re.compile(r"^(?P<base>.+?)\s+\((?P<qualifier>[^()]+)\)$")


def _strip_diacritics_keep_enye(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    kept: list[str] = []
    for char in decomposed:
        if unicodedata.combining(char):
            # Se conserva la tilde solo si acompaña a una n (ñ / Ñ).
            if char == _COMBINING_TILDE and kept and kept[-1] in "nN":
                kept.append(char)
            continue
        kept.append(char)
    return unicodedata.normalize("NFC", "".join(kept))


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).replace("_", " ")
    value = _strip_diacritics_keep_enye(value).casefold()
    value = _DOTTED_ACRONYM.sub(lambda m: m.group(1).replace(".", ""), value)
    value = _NON_WORD.sub(" ", value)
    return _SPACES.sub(" ", value).strip()[:MAX_KEY_LENGTH]


def is_usable_key(key: str) -> bool:
    return len(key) >= MIN_KEY_LENGTH


def disambiguation_base(title: str) -> str | None:
    """Base de un título con calificador entre paréntesis, o None si no lo tiene."""
    match = _DISAMBIGUATION.match(title.strip())
    return match["base"].strip() if match else None
