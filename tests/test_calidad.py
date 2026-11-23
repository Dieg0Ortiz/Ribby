"""
Tests del filtro de reseñas y resúmenes basura (calidad.py).

    python -m unittest tests.test_calidad -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calidad  # noqa: E402

BASURA = {
    "Israel" * 60: "palabra_gigante",              # La reseña troll real
    "Israel " * 40: "repetitivo",
    "." * 60: "corto",                             # "60 veces un punto"
    "jaja " * 15: "repetitivo",
    "a b c d e f g h i j k l m n o p q r": "sin_letras",
    "buena " * 12: "repetitivo",
    "!!!! ???? !!!! ???? !!!! ???? !!!! ???? !!!! ????": "corto",
}

BUENAS = [
    "Me encantó la historia, los personajes están muy bien escritos y el final me dejó llorando. Jajajaja el "
    "capítulo del faro es mi favorito.",
    "No me gustó mucho: el ritmo es lento y los diálogos se sienten forzados, aunque la idea de Lycanroc "
    "reencarnado es original.",
    "Historia buena buena buena, la recomiendo mucho a todos los que les guste el drama y la fantasía con Pokémon.",
    "https://www.wattpad.com/story/123 muy buena historia, te atrapa desde el primer capítulo y no la puedes soltar.",
    "Es muy buena y la recomiendo a todos, me gustó mucho el final y lo que le pasa a Eevee.",
]


class TestCalidad(unittest.TestCase):
    def test_rechaza_basura(self):
        for texto, motivo in BASURA.items():
            self.assertEqual(calidad.problema_texto(texto), motivo, texto[:40])

    def test_acepta_resenas_de_verdad(self):
        for texto in BUENAS:
            self.assertIsNone(calidad.problema_texto(texto), texto[:40])

    def test_resumen_con_menos_palabras(self):
        resumen = "Una Eevee perdida busca su hogar en una biblioteca."
        self.assertIsNone(calidad.problema_texto(resumen, minimo_palabras=6))

    def test_todos_los_motivos_tienen_mensaje(self):
        for motivo in set(BASURA.values()) | {"ofensivo"}:
            self.assertIn(motivo, calidad.MENSAJES)


if __name__ == "__main__":
    unittest.main()
