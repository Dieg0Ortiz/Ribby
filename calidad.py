"""
calidad.py — Filtro de textos basura en reseñas y resúmenes (sin red ni Discord).

El formulario de reseñas pedía 60 caracteres como mínimo, y bastaba con escribir
"IsraelIsraelIsrael..." o 60 puntos para pasarlo (y encima completar una misión
de lectura y ganar corazones). Aquí se rechazan los textos que no son una
reseña de verdad: repetitivos, sin palabras reales, con "palabras" gigantes,
solo símbolos o demasiado cortos. El filtro de toxicidad (Hugging Face) se
aplica aparte, en el cog.
"""

from __future__ import annotations

import re
from typing import Optional

MIN_PALABRAS = 8
MAX_LONGITUD_PALABRA = 25          # "electroencefalografista" tiene 23 letras
MIN_PROPORCION_UNICAS = 0.45       # Palabras distintas / palabras totales
MAX_PROPORCION_REPETIDA = 0.35     # Parte del texto que es un mismo trozo repetido
MIN_LETRAS_DISTINTAS = 10
MIN_PROPORCION_LETRAS = 0.55       # Letras / caracteres (sin espacios)

_RE_URL = re.compile(r"https?://\S+", re.I)
_RE_PALABRA = re.compile(r"[^\W\d_]+", re.UNICODE)
_RE_REPETICION = re.compile(r"(.{2,20}?)\1{3,}", re.S)

MENSAJES = {
    "corto": "Eso no es una reseña, es un suspiro. Cuéntame un poco más: qué te gustó, qué no, qué sentiste. 📝",
    "palabra_gigante": "¿Qué idioma es ese? Las palabras tienen espacios, ¿sabes? Escribe una reseña de verdad. 🙄",
    "repetitivo": "Repetir lo mismo muchas veces no lo convierte en una reseña. Inténtalo otra vez, con ganas. 😒",
    "sin_letras": "Puntos, símbolos, letras sueltas… Eso no me cuenta nada de la historia. Escribe algo de verdad. 📚",
    "ofensivo": "No pienso guardar eso en mi biblioteca. Si no te gustó, dilo con respeto: el autor también lee. 😤",
}


def problema_texto(texto: str, minimo_palabras: int = MIN_PALABRAS) -> Optional[str]:
    """Motivo por el que el texto no vale (clave de MENSAJES), o None si es un texto normal."""
    limpio = _RE_URL.sub(" ", texto or "").strip()
    palabras = _RE_PALABRA.findall(limpio.lower())
    if any(len(p) > MAX_LONGITUD_PALABRA for p in palabras):
        return "palabra_gigante"
    if len(palabras) < minimo_palabras:
        return "corto"
    # Letras sueltas ("a b c d e...") no son palabras
    if sum(1 for p in palabras if len(p) >= 3) < minimo_palabras * 0.6:
        return "sin_letras"
    if len(set(palabras)) / len(palabras) < MIN_PROPORCION_UNICAS:
        return "repetitivo"
    compacto = re.sub(r"\s+", "", limpio.lower())
    repetido = sum(len(m.group(0)) for m in _RE_REPETICION.finditer(compacto))
    if compacto and repetido / len(compacto) > MAX_PROPORCION_REPETIDA:
        return "repetitivo"
    letras = [c for c in compacto if c.isalpha()]
    if len(set(letras)) < MIN_LETRAS_DISTINTAS or len(letras) / max(len(compacto), 1) < MIN_PROPORCION_LETRAS:
        return "sin_letras"
    return None
