"""
logros.py — Insignias que se desbloquean con Ribby (lógica pura).

`evaluar(ctx)` devuelve los logros que se cumplen con los datos disponibles.
Si a ctx le falta un dato (por ejemplo el número de reseñas), los logros que
dependen de él simplemente no se evalúan en esa llamada.
"""

from __future__ import annotations

from typing import Any

import secretos

# clave: (emoji, nombre, cómo se consigue, es_secreto)
LOGROS: dict[str, tuple[str, str, str, bool]] = {
    "primera_charla": ("👋", "Hola, Ribby", "Habla con Ribby por primera vez", False),
    "amigo": ("🤝", "Un amigo en la biblioteca", "Que Ribby te considere su amigo", False),
    "mejor_amigo": ("💛", "Inseparables", "Que Ribby te considere su mejor amigo", False),
    "algo_mas": ("💗", "Mariposas en el estómago", "Que Ribby sienta algo más que amistad", False),
    "pareja": ("💞", "Corazón conquistado", "Conviértete en la pareja de Ribby", False),
    "racha_7": ("🔥", "Una semana juntos", "Habla con Ribby 7 días seguidos", False),
    "racha_30": ("☄️", "Un mes sin faltar", "Habla con Ribby 30 días seguidos", False),
    "charlas_100": ("💬", "Cotorra", "Habla con Ribby 100 veces", False),
    "primera_cita": ("🌹", "Primera cita", "Ten tu primera cita con Ribby", False),
    "citas_10": ("🗓️", "Agenda llena", "Ten 10 citas con Ribby", False),
    "primer_regalo": ("🎁", "Detallista", "Hazle tu primer regalo a Ribby", False),
    "regalos_20": ("🛍️", "Sin límite de gastos", "Hazle 20 regalos a Ribby", False),
    "lector": ("📖", "Primer encargo", "Completa tu primera misión de lectura", False),
    "lector_10": ("📚", "Ratón de biblioteca", "Completa 10 misiones de lectura", False),
    "critico": ("🖋️", "Crítico literario", "Escribe 5 reseñas de historias", False),
    "festivo": ("🎉", "Espíritu festivo", "Celebra un evento de temporada con Ribby", False),
    "cumple": ("🎂", "Que no se me olvide", "Cuéntale a Ribby cuándo es tu cumpleaños", False),
    "primer_capitulo": ("📜", "Érase una vez", "Lee el primer capítulo de la historia de Ribby", False),
    "lore_completo": ("📕", "El libro de Ribby", "Lee todos los capítulos de la historia de Ribby", False),
    "te_conozco": ("🧠", "Te conozco bien", "Acierta 10 preguntas de «¿Me conoces?»", False),
    "escarabajo": ("🪲", "Entomólogo incomprendido", "Regálale a Ribby algo que odia", True),
    "rechazado": ("💔", "Lo intentaste", "Declárate a Ribby antes de tiempo", True),
}

# Un logro oculto por cada secreto de Ribby (secretos.py): se ven como "???" hasta descubrirlos
LOGROS.update({s.logro: (s.emoji, s.nombre, s.descripcion, True) for s in secretos.SECRETOS})

_ORDEN_NIVEL = ["desconocido", "amigo", "mejor_amigo", "algo_mas", "enamorada", "pareja"]

# (logro, dato del contexto, mínimo)
_UMBRALES = [
    ("primera_charla", "total_interacciones", 1),
    ("charlas_100", "total_interacciones", 100),
    ("racha_7", "racha_dias", 7),
    ("racha_30", "racha_dias", 30),
    ("primera_cita", "citas_total", 1),
    ("citas_10", "citas_total", 10),
    ("primer_regalo", "regalos_total", 1),
    ("regalos_20", "regalos_total", 20),
    ("lector", "misiones", 1),
    ("lector_10", "misiones", 10),
    ("critico", "resenas", 5),
    ("te_conozco", "quiz_aciertos", 10),
    ("primer_capitulo", "capitulos", 1),
    ("lore_completo", "capitulos", 4),
]


def evaluar(ctx: dict[str, Any]) -> set[str]:
    cumplidos = {clave for clave, dato, minimo in _UMBRALES if dato in ctx and (ctx[dato] or 0) >= minimo}
    if "nivel" in ctx:
        orden = _ORDEN_NIVEL.index(ctx["nivel"]) if ctx["nivel"] in _ORDEN_NIVEL else 0
        for clave, minimo in (("amigo", 1), ("mejor_amigo", 2), ("algo_mas", 3), ("pareja", 5)):
            if orden >= minimo:
                cumplidos.add(clave)
    return cumplidos


def formatear(clave: str) -> str:
    emoji, nombre, _, _ = LOGROS[clave]
    return f"{emoji} **{nombre}**"
