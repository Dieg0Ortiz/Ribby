"""
temporadas.py — Eventos de temporada de Ribby (lógica pura).

Durante cada evento:
  - Ribby lo menciona en sus conversaciones (contexto extra para la IA).
  - /ribby evento ofrece un regalo especial y una cita especial (una vez por evento).
  - /ribby cita puede tocar una escena de temporada.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

EVENTOS: list[dict[str, Any]] = [
    {
        "id": "san_valentin",
        "anuncio": "La biblioteca amaneció llena de corazones de papel. Ribby dice que es una cursilería... pero los colgó ella.",
        "nombre": "💘 San Valentín",
        "inicio": (2, 10), "fin": (2, 15),
        "contexto": "Es la semana de San Valentín. La biblioteca está decorada con corazones de papel y tú finges "
                    "que te parece cursi, aunque en el fondo te encanta. Estás un poco más sensible de lo normal.",
        "regalo": {"nombre": "💌 Una carta de amor escrita a mano", "delta": 1.5,
                   "respuesta": "*la lee tres veces seguidas* ...¿L-la escribiste tú? La guardaré dentro de mi libro favorito. Por si acaso. 💌"},
        "cita": {
            "titulo": "💘 Cena de San Valentín",
            "escena": "Una mesa para dos entre las estanterías, velas y un pastel en forma de corazón. Ribby lleva un listón nuevo.",
            "opciones": [
                ("Decirle que el listón le queda precioso", 2.0, "*se pone roja hasta las orejas* ¡N-no lo elegí para ti! ...Bueno, un poco. 💗"),
                ("Leerle un poema de amor", 1.5, "...Eso ha sido ridículamente cursi. Léelo otra vez. 🌹"),
                ("Comerte el pastel tú solo", -0.5, "¿Todo? ¿En serio? Esta cita ha durado menos que un prólogo. 😤"),
            ],
        },
    },
    {
        "id": "dia_libro",
        "anuncio": "¡Llega la semana del Día del Libro! Ribby lleva días preparando rosas y marcapáginas para todos.",
        "nombre": "📚 Día del Libro",
        "inicio": (4, 20), "fin": (4, 24),
        "contexto": "Es la semana del Día del Libro (23 de abril), TU fiesta favorita del año. Estás eufórica, "
                    "recomiendas libros a todo el mundo y la biblioteca está llena de rosas y marcapáginas.",
        "regalo": {"nombre": "🌹 Una rosa y un libro (tradición de Sant Jordi)", "delta": 1.5,
                   "respuesta": "¡Una rosa Y un libro! Conoces la tradición... vale, has superado mis expectativas. Por mucho. 🌹📚"},
        "cita": {
            "titulo": "📚 La feria del libro",
            "escena": "Casetas de libros hasta donde alcanza la vista. Ribby ya lleva una lista de 40 títulos.",
            "opciones": [
                ("Cargarle todos los libros que compre", 2.0, "*te pasa una pila enorme* Eres útil. Muy útil. Y... gracias por venir conmigo. 📚"),
                ("Regalarle el libro que lleva años buscando", 1.5, "¿C-cómo sabías...? *abraza el libro* No digas nada. Solo... no digas nada. 🥹"),
                ("Decir que prefieres las películas", -1.0, "...Vete. Ahora mismo. De mi feria. 😤"),
            ],
        },
    },
    {
        "id": "halloween",
        "anuncio": "Las velas parpadean entre las estanterías y hay una ofrenda con los libros más queridos. Ribby se ha disfrazado de bruja bibliotecaria.",
        "nombre": "🎃 Halloween y Día de Muertos",
        "inicio": (10, 25), "fin": (11, 2),
        "contexto": "Es temporada de Halloween y Día de Muertos. Te has disfrazado (de bruja bibliotecaria) y "
                    "recomiendas historias de terror con mucho entusiasmo. Pusiste una ofrenda con libros de autores queridos.",
        "regalo": {"nombre": "🍬 Pan de muerto y dulces", "delta": 1.2,
                   "respuesta": "¿Pan de muerto? ...Lo pondré en la ofrenda. Después de comerme la mitad. 🕯️🍞"},
        "cita": {
            "titulo": "🎃 La biblioteca embrujada",
            "escena": "Las luces parpadean y se oyen pasos entre las estanterías. Ribby te agarra del brazo (por accidente, dice).",
            "opciones": [
                ("Contarle una historia de miedo a la luz de una vela", 2.0, "*se acerca más a ti* N-no tengo miedo. Es que hace frío. Sigue contando. 🕯️"),
                ("Hacerle una broma y asustarla", -0.5, "¡¡AAAH!! ...Eso no ha tenido gracia. Ninguna. 😤💢"),
                ("Prometer que la protegerás de los fantasmas", 1.5, "Hmph. Como si los necesitara. ...No te separes mucho, por si acaso. 👻"),
            ],
        },
    },
    {
        "id": "navidad",
        "anuncio": "Hay un árbol en la sala de lectura decorado con marcapáginas, y Ribby lleva un gorro rojo que jura odiar.",
        "nombre": "🎄 Navidad",
        "inicio": (12, 15), "fin": (1, 6),
        "contexto": "Es temporada navideña. La biblioteca tiene un árbol decorado con marcapáginas y tú llevas un "
                    "gorro rojo que finges odiar. Te pones nostálgica y cariñosa.",
        "regalo": {"nombre": "🎁 Un suéter navideño con un Sylveon bordado", "delta": 1.5,
                   "respuesta": "...Es horrible. *se lo pone inmediatamente* Es horrible y no me lo voy a quitar. 🎄"},
        "cita": {
            "titulo": "🎄 Noche de Navidad",
            "escena": "Nieva afuera. Dentro, chocolate caliente, mantas y una chimenea encendida en la sala de lectura.",
            "opciones": [
                ("Leer juntos un cuento de Navidad bajo la manta", 2.0, "*apoya la cabeza en tu hombro* ...Esto es lo mejor de todo el año. No se lo digas a nadie. 🎄💞"),
                ("Hacer una guerra de bolas de nieve", 1.0, "¡Me has dado en los listones! ...Revancha. AHORA. ❄️"),
                ("Quedarte mirando el móvil", -0.5, "Es Navidad y tú con el móvil... Hmph. 📱"),
            ],
        },
    },
]


def _dentro(evento: dict[str, Any], d: date) -> bool:
    inicio, fin, actual = evento["inicio"], evento["fin"], (d.month, d.day)
    if inicio <= fin:
        return inicio <= actual <= fin
    return actual >= inicio or actual <= fin  # Cruza de año (Navidad)


def evento_actual(d: date) -> Optional[dict[str, Any]]:
    return next((e for e in EVENTOS if _dentro(e, d)), None)


def edicion(evento: dict[str, Any], d: date) -> str:
    """Identificador único de esta edición del evento: 'navidad-2026' (la de enero cuenta como del año anterior)."""
    anio = d.year
    if evento["inicio"] > evento["fin"] and (d.month, d.day) <= evento["fin"]:
        anio -= 1
    return f"{evento['id']}-{anio}"


def es_primer_dia(evento: dict[str, Any], d: date) -> bool:
    return (d.month, d.day) == evento["inicio"]


def contexto_hoy(d: date) -> str:
    e = evento_actual(d)
    return f"TEMPORADA ESPECIAL — {e['nombre']}: {e['contexto']}" if e else ""
