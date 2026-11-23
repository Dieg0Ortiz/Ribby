"""
Tests de los secretos escondidos y las confidencias (secretos.py). Sin discord.py ni red.

    python -m unittest tests.test_secretos -v
"""

import os
import random
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logros  # noqa: E402
import secretos as sec  # noqa: E402

DIA_NORMAL = date(2026, 11, 23)


def ctx(**kw):
    base = dict(hora=18, fecha=DIA_NORMAL, nivel="pareja", capitulos={1, 2, 3, 4}, es_pareja=True)
    base.update(kw)
    return sec.Contexto(**base)


# Una frase de ejemplo (y su contexto) para cada secreto de frase: si alguno no se puede encontrar, falla
EJEMPLOS = {
    "eevee": ("Oye Eevee, ¿qué lees?", {}),
    "cuarenta_y_dos": ("¿Siguen ahí los 42 libros?", {}),
    "hora_bruja": ("hola", {"hora": 3}),
    "ceres_perremlo": ("¿Qué opinas de Ceres x Perremlo?", {}),
    "konami": ("↑↑↓↓←→←→BA", {}),
    "tainy_despierto": ("¡Ribby! ¡Tainy está despierto!", {}),
    "cuento": ("¿Me lees un cuento?", {}),
    "listones": ("¿Puedo tocar tus listones?", {}),
    "estante_fantasia": ("¿Qué hay detrás del estante de fantasía?", {}),
    "palabras_magicas": ("Alohomora", {}),
    "dia_del_libro": ("¡Feliz Día del Libro, Ribby!", {"fecha": date(2027, 4, 23)}),
    "te_lluvia": ("¿Un té de jazmín mientras llueve?", {}),
    "carta": ("¿Al final enviaste la carta?", {}),
    "papa_tainy": ("¿Tainy es como tu padre?", {}),
}


class TestFrases(unittest.TestCase):
    def test_todos_los_secretos_de_frase_se_pueden_encontrar(self):
        de_frase = {s.id for s in sec.SECRETOS if s.accion is None}
        self.assertEqual(de_frase, set(EJEMPLOS))
        for sid, (frase, extra) in EJEMPLOS.items():
            encontrado = sec.detectar_frase(frase, ctx(**extra))
            self.assertIsNotNone(encontrado, sid)
            self.assertEqual(encontrado[0].id, sid, frase)
            self.assertTrue(encontrado[1], sid)

    def test_mensajes_normales_no_disparan_nada(self):
        for frase in ["hola Ribby, ¿cómo estás?", "recomiéndame un libro", "me gusta la lluvia", "tengo 42 años",
                      "te mando una carta", "¿qué hay en el estante?"]:
            self.assertIsNone(sec.detectar_frase(frase, ctx()), frase)

    def test_hora_y_fecha(self):
        self.assertIsNone(sec.detectar_frase("hola", ctx(hora=4)))
        self.assertIsNone(sec.detectar_frase("feliz día del libro", ctx()))  # No es 23 de abril
        # A las 3, un secreto de frase tiene prioridad sobre la hora bruja
        self.assertEqual(sec.detectar_frase("Alohomora", ctx(hora=3))[0].id, "palabras_magicas")

    def test_si_no_te_toca_ribby_lo_esquiva(self):
        s, permitido = sec.detectar_frase("¿Qué hay detrás del estante de fantasía?", ctx(capitulos={1}))
        self.assertEqual(s.id, "estante_fantasia")
        self.assertFalse(permitido)
        self.assertTrue(s.esquiva)
        s, permitido = sec.detectar_frase("¿Puedo tocar tus listones?", ctx(nivel="amigo"))
        self.assertFalse(permitido)
        # El creador siempre tiene confianza suficiente
        self.assertTrue(sec.detectar_frase("¿Puedo tocar tus listones?", ctx(nivel="creador"))[1])

    def test_todos_los_que_se_esquivan_tienen_texto(self):
        for s in sec.SECRETOS:
            if s.requisito is not None:
                self.assertTrue(s.esquiva, s.id)


class TestAcciones(unittest.TestCase):
    def test_regalos_y_cita(self):
        self.assertEqual(sec.detectar_accion("regalo:libro", ctx(fecha=date(2027, 4, 21))).id, "libro_dia_del_libro")
        self.assertIsNone(sec.detectar_accion("regalo:libro", ctx()))
        self.assertEqual(sec.detectar_accion("regalo:bicho", ctx()).id, "bicho_pareja")
        self.assertIsNone(sec.detectar_accion("regalo:bicho", ctx(es_pareja=False)))
        self.assertEqual(sec.detectar_accion("cita", ctx(hora=0)).id, "cita_medianoche")
        self.assertIsNone(sec.detectar_accion("cita", ctx(hora=1)))


class TestReacciones(unittest.TestCase):
    def test_palabras_magicas_dan_la_pista_de_otro_secreto(self):
        magia = sec.POR_ID["palabras_magicas"]
        texto = sec.reaccion(magia, [sec.POR_ID["carta"], magia], random.Random(1))
        self.assertIn(sec.POR_ID["carta"].pista, texto)
        self.assertNotIn("{pista}", sec.reaccion(magia, [], random.Random(1)))

    def test_logros_ocultos_registrados(self):
        for s in sec.SECRETOS:
            emoji, nombre, _, secreto = logros.LOGROS[s.logro]
            self.assertTrue(secreto)
            self.assertEqual(nombre, s.nombre)
        self.assertEqual(len({s.id for s in sec.SECRETOS}), len(sec.SECRETOS))


class TestConfidencias(unittest.TestCase):
    def test_se_abre_segun_el_nivel(self):
        self.assertEqual(sec.confidencias_disponibles("desconocido"), [])
        amigo = sec.confidencias_disponibles("amigo")
        pareja = sec.confidencias_disponibles("pareja")
        self.assertEqual(len(amigo), 5)
        self.assertEqual(len(pareja), 20)
        self.assertEqual(pareja[:5], amigo)  # Primero lo más ligero
        self.assertEqual(sec.confidencias_disponibles("enamorada"), sec.confidencias_disponibles("algo_mas"))
        self.assertEqual({c[0] for c in sec.confidencias_disponibles("creador")},
                         {c[0] for c in sec.CONFIDENCIAS["creador"]})

    def test_siguiente_sin_repetir(self):
        contadas = []
        for _ in range(5):
            cid, _ = sec.siguiente_confidencia("amigo", contadas)
            self.assertNotIn(cid, contadas)
            contadas.append(cid)
        self.assertIsNone(sec.siguiente_confidencia("amigo", contadas))
        self.assertIsNotNone(sec.siguiente_confidencia("mejor_amigo", contadas))  # Al subir de nivel hay más
        self.assertEqual(len(sec.texto_confidencias(contadas + ["no_existe"])), 5)

    def test_hay_confidencias_que_son_pistas(self):
        textos = " ".join(t for lista in sec.CONFIDENCIAS.values() for _, t in lista)
        self.assertIn("tres de la madrugada", textos)  # → La hora bruja


if __name__ == "__main__":
    unittest.main()
