"""
Tests de las citas con Ribby (citas.py). Sin discord.py, red ni base de datos.

    python -m unittest tests.test_citas -v
"""

import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import citas as ct  # noqa: E402
import ribby_lore as lr  # noqa: E402


def _escena(efectos=(0.9, 0.0, 0.4)):
    return {"texto": "La lluvia golpea el faro. Ribby mira de reojo una tetera de jazmín.",
            "pregunta": "¿Qué le ofreces?",
            "opciones": [{"texto": f"Opción {i}", "efecto": e, "reaccion": f"Reacción {i}"} for i, e in enumerate(efectos)]}


class TestIngredientes(unittest.TestCase):
    def test_evita_lugares_ya_usados(self):
        usados = ct.LUGARES[:-1]
        for semilla in range(20):
            ing = ct.sortear_ingredientes(usados, random.Random(semilla))
            self.assertEqual(ing["lugar"], ct.LUGARES[-1])
            self.assertIn(ing["objeto"], ct.OBJETOS)
            self.assertIn(ing["giro"], ct.GIROS)

    def test_si_ya_uso_todos_vuelve_a_empezar(self):
        self.assertIn(ct.sortear_ingredientes(ct.LUGARES)["lugar"], ct.LUGARES)


class TestValidacion(unittest.TestCase):
    def test_inicio_valido(self):
        texto = "Aquí va: " + json.dumps({"titulo": "🌧️ El faro de las tazas", "premisa": "Un faro.", "escena": _escena()})
        titulo, premisa, escena = ct.parsear_inicio(texto, random.Random(1))
        self.assertEqual(titulo, "🌧️ El faro de las tazas")
        self.assertEqual(len(escena["opciones"]), 3)
        self.assertEqual(sorted(o["efecto"] for o in escena["opciones"]), [0.0, 0.4, 0.9])

    def test_baraja_las_opciones(self):
        ordenes = {tuple(o["texto"] for o in ct.validar_escena(_escena(), random.Random(s))["opciones"]) for s in range(30)}
        self.assertGreater(len(ordenes), 1)  # La mejor no siempre sale primera

    def test_recorta_y_acota(self):
        datos = _escena(efectos=(5, -9, "x"))
        datos["opciones"][0]["texto"] = "a" * 300
        escena = ct.validar_escena(datos)
        self.assertTrue(all(-1 <= o["efecto"] <= 1 for o in escena["opciones"]))
        self.assertTrue(all(len(o["texto"]) <= ct.LIMITES["opcion"] for o in escena["opciones"]))

    def test_invalidas(self):
        self.assertIsNone(ct.parsear_inicio("no es json"))
        self.assertIsNone(ct.parsear_inicio(json.dumps({"escena": _escena()})))  # Sin título
        sola = _escena()
        sola["opciones"] = sola["opciones"][:1]
        self.assertIsNone(ct.validar_escena(sola))  # Una sola opción no es una decisión
        self.assertIsNone(ct.parsear_final(json.dumps({"recuerdo": "x"})))

    def test_escena_siguiente_y_final(self):
        self.assertIsNotNone(ct.parsear_escena(json.dumps({"escena": _escena()})))
        self.assertEqual(ct.parsear_final(json.dumps({"final": "Fin.", "recuerdo": "Fueron al faro."})),
                         ("Fin.", "Fueron al faro."))


class TestResultado(unittest.TestCase):
    def test_desenlaces(self):
        self.assertEqual(ct.resultado([0.9, 0.8, 0.7, 1.0], 4)[0], "perfecta")
        self.assertEqual(ct.resultado([0.5, 0.3, 0.2, 0.4], 4)[0], "bonita")
        self.assertEqual(ct.resultado([0.4, -0.4, 0.1, -0.1], 4)[0], "regular")
        self.assertEqual(ct.resultado([-0.5, -0.8, 0.0, -0.6], 4)[0], "desastre")

    def test_corazones_acotados_y_ultima_pesa_mas(self):
        _, maximo = ct.resultado([1.0] * 5, 5)
        _, minimo = ct.resultado([-1.0] * 5, 5)
        self.assertLessEqual(maximo, ct.CORAZONES_MAX)
        self.assertGreaterEqual(minimo, ct.CORAZONES_MIN)
        self.assertGreater(ct.quimica([0.0, 1.0]), ct.quimica([1.0, 0.0]))

    def test_abandonada_nunca_resta(self):
        desenlace, corazones = ct.resultado([-1.0, -1.0], 5, abandonada=True)
        self.assertEqual((desenlace, corazones), ("a_medias", 0.0))
        _, parcial = ct.resultado([1.0, 1.0], 5, abandonada=True)
        _, completa = ct.resultado([1.0] * 5, 5)
        self.assertLess(parcial, completa)


class TestPrompts(unittest.TestCase):
    def test_pedido_inicio_personalizado(self):
        ing = {"lugar": "un faro", "objeto": "una llave", "giro": "se va la luz"}
        pedido = ct.pedido_inicio(
            "Emlo", "pareja", "Es tu pareja.", "Le encanta escribir.", "- Pokémon: Leafeon",
            [{"titulo": "🎡 La feria", "resumen": "Ganaron un peluche"}], ["🌙 Otra cita: premisa"], ing, 5, 3,
            ct.gustos_ribby(lr.PREGUNTAS_RIBBY, set()),
        )
        for esperado in ("Emlo", "ROMÁNTICA", "Leafeon", "La feria", "Otra cita", "un faro", "La escena 3 será un RETO",
                         "Jazmín"):
            self.assertIn(esperado, pedido)
        # Sin haber leído los capítulos, no se destripan sus secretos
        self.assertNotIn("Detrás del estante de fantasía", pedido)

    def test_creador_familiar(self):
        self.assertIn("NADA romántico", ct.TONO_POR_NIVEL["creador"])

    def test_pedido_siguiente_lleva_consecuencias(self):
        plan = {"titulo": "T", "premisa": "P", "tono": "x", "ingredientes": "y", "nombre": "Emlo", "datos": ""}
        historial = [{"escena": "Escena uno", "eleccion": "Ofrecerle té", "reaccion": "¡Jazmín!", "efecto": 0.9}]
        pedido = ct.pedido_siguiente(plan, historial, 5, 5, 3)
        self.assertIn("Ofrecerle té", pedido)
        self.assertIn("le encantó", pedido)
        self.assertIn("ÚLTIMA escena", pedido)


class TestTardePadreHija(unittest.TestCase):
    ING = {"lugar": "arreglar el sofá", "objeto": "una llave", "giro": "Tainy se duerme"}

    def test_ingredientes_de_familia(self):
        ing = ct.sortear_ingredientes(familiar=True, rng=random.Random(2))
        self.assertIn(ing["lugar"], ct.LUGARES_FAMILIA)
        self.assertIn(ing["giro"], ct.GIROS_FAMILIA)

    def test_pedido_con_noticias_solo_para_el_creador(self):
        args = ("Tainy", "creador", "Es tu creador.", "", "", [], [], self.ING, 4, 2, "- té → jazmín")
        pedido = ct.pedido_inicio(*args, noticias="- SU PAREJA es Ana (llevan 50 días juntos).")
        self.assertIn("ESTA NO ES UNA CITA ROMÁNTICA", pedido)
        self.assertIn("SU PAREJA es Ana", pedido)
        normal = ct.pedido_inicio("Emlo", "pareja", *args[2:], noticias="- SU PAREJA es Ana")
        self.assertNotIn("ESTA NO ES UNA CITA ROMÁNTICA", normal)
        self.assertNotIn("SU PAREJA es Ana", normal)

    def test_escenas_y_final_familiares(self):
        plan = {"titulo": "T", "premisa": "P", "tono": "x", "ingredientes": "y", "nombre": "Tainy", "datos": "",
                "familiar": True, "noticias": "- Amigo/a: Pedro."}
        historial = [{"escena": "e", "eleccion": "Escucharla", "reaccion": "Gracias, papá", "efecto": 0.9}]
        self.assertIn("Amigo/a: Pedro", ct.pedido_siguiente(plan, historial, 2, 4, 3))
        self.assertIn("TARDE PERFECTA", ct.pedido_final(plan, historial, "perfecta"))
        self.assertTrue(ct.barra_quimica(1.0, familiar=True).startswith("💛"))


if __name__ == "__main__":
    unittest.main()
