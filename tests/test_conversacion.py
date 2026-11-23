"""
Tests de la memoria de conversación (conversacion.py) y de la detección de
intención de la biblioteca. No necesitan discord.py, red ni base de datos.

    python -m unittest tests.test_conversacion -v
"""

import os
import sys
import json
import unittest
from datetime import date
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import conversacion as conv  # noqa: E402
import memoria as mem  # noqa: E402
import recomendador as rec  # noqa: E402

RIBBY = 1
T0 = 1_000_000.0


def _e(mid, autor_id, autor, texto, seg=0, ribby=False, responde_a=None, nota=""):
    return conv.Entrada(mid, autor_id, autor, texto, T0 + seg, ribby, responde_a, nota)


class TestMemoriaCanales(unittest.TestCase):
    def test_registra_y_respeta_limites(self):
        m = conv.MemoriaCanales(max_entradas=3, max_canales=2)
        for i in range(5):
            m.registrar(10, _e(i, 2, "Juan", f"msg {i}", i))
        self.assertEqual([e.texto for e in m.recientes(10, ahora=T0 + 10)], ["msg 2", "msg 3", "msg 4"])
        m.registrar(20, _e(100, 2, "Juan", "otro canal"))
        m.registrar(30, _e(101, 2, "Juan", "tercer canal"))
        self.assertFalse(m.tiene(10))  # El canal menos activo se descarta

    def test_no_duplica_ni_guarda_vacios(self):
        m = conv.MemoriaCanales()
        m.registrar(10, _e(1, 2, "Juan", "hola"))
        m.registrar(10, _e(1, 2, "Juan", "hola"))
        m.registrar(10, _e(2, 2, "Juan", ""))
        self.assertEqual(len(m.recientes(10, ahora=T0)), 1)

    def test_sembrar_mezcla_en_orden(self):
        m = conv.MemoriaCanales()
        m.registrar(10, _e(3, 2, "Juan", "nuevo", 30))
        m.sembrar(10, [_e(1, 2, "Juan", "viejo", 10), _e(3, 2, "Juan", "nuevo", 30), _e(2, 3, "Pedro", "medio", 20)])
        self.assertEqual([e.texto for e in m.recientes(10, ahora=T0 + 40)], ["viejo", "medio", "nuevo"])

    def test_editar_borrar_y_ventana(self):
        m = conv.MemoriaCanales()
        m.registrar(10, _e(1, 2, "Juan", "hola"))
        m.registrar(10, _e(2, 2, "Juan", "adios", 10))
        m.editar(10, 1, "hola editado")
        m.borrar(10, 2)
        self.assertEqual([e.texto for e in m.recientes(10, ahora=T0 + 20)], ["hola editado"])
        self.assertEqual(m.recientes(10, ahora=T0 + conv.VENTANA_SEGUNDOS + 1), [])

    def test_participantes(self):
        entradas = [_e(1, 2, "Juan", "a"), _e(2, RIBBY, "Ribby", "b", ribby=True), _e(3, 3, "Pedro", "c"),
                    _e(4, 2, "Juan", "d")]
        self.assertEqual(conv.participantes(entradas, excluir={3}), [(2, "Juan")])
        self.assertEqual(conv.participantes(entradas), [(2, "Juan"), (3, "Pedro")])


class TestMensajesParaIA(unittest.TestCase):
    def test_caso_real_recuerda_las_tarjetas(self):
        """La conversación del bug: Ribby recomendó (tarjetas) y luego lo negó."""
        entradas = [
            _e(1, 2, "Emlo", "¿qué tal?", 0),
            _e(2, RIBBY, "Ribby", "Aquí tienes tres historias.\n[tarjeta: «Reencarne en un ¿Sceptile?» — Por Sr Anderson]",
               60, ribby=True),
        ]
        actual = _e(3, 2, "Emlo", "@Ribby ¡Gracias! ¿Qué podrías decirme de cada uno?", 120, responde_a=2)
        msgs = conv.mensajes_para_ia(entradas, actual, ahora=T0 + 120)
        self.assertEqual([m["role"] for m in msgs], ["user", "ribby", "user"])
        self.assertIn("Sceptile", msgs[1]["content"])
        self.assertTrue(msgs[-1]["content"].startswith("» Emlo (respondiendo a tu mensaje)"))

    def test_varias_personas_se_agrupan_y_alternan(self):
        entradas = [
            _e(1, RIBBY, "Ribby", "Bienvenidos", 0, ribby=True),
            _e(2, 2, "Juan", "Ribby, ¿te gusta el té?", 10),
            _e(3, RIBBY, "Ribby", "Solo el de jazmín.", 20, ribby=True),
            _e(4, 3, "Pedro", "jaja a Juan no le gusta el jazmín", 30, responde_a=3),
        ]
        actual = _e(5, 3, "Pedro", "¿verdad que Juan tiene mal gusto?", 40)
        msgs = conv.mensajes_para_ia(entradas, actual, ahora=T0 + 40)
        roles = [m["role"] for m in msgs]
        self.assertEqual(roles[0], "user")  # Empieza siempre por el usuario
        self.assertTrue(all(a != b for a, b in zip(roles, roles[1:])))  # Alterna
        self.assertIn("Pedro (respondiendo a tu mensaje): jaja", msgs[-1]["content"])
        self.assertIn("» Pedro: ¿verdad", msgs[-1]["content"])
        self.assertEqual(msgs[1], {"role": "ribby", "content": "Bienvenidos"})
        self.assertIn("Juan: Ribby, ¿te gusta el té?", msgs[2]["content"])

    def test_respuesta_a_otra_persona_y_tiempo(self):
        entradas = [_e(1, 2, "Juan", "me voy a dormir", 0)]
        actual = _e(2, 3, "Pedro", "Ribby, ¿oíste a Juan?", 600, responde_a=1)
        msgs = conv.mensajes_para_ia(entradas, actual, ahora=T0 + 600)
        self.assertIn("Juan (hace 10 min): me voy a dormir", msgs[0]["content"])
        self.assertIn("respondiendo a Juan: «me voy a dormir»", msgs[0]["content"])

    def test_presupuesto_descarta_lo_mas_antiguo(self):
        entradas = [_e(i, 2, "Juan", f"{i}-" + "x" * 300, i) for i in range(50)]
        actual = _e(99, 2, "Juan", "último", 60)
        msgs = conv.mensajes_para_ia(entradas, actual, ahora=T0 + 60, presupuesto=1500)
        contenido = "\n".join(m["content"] for m in msgs)
        self.assertLess(len(contenido), 1700)
        self.assertIn("49-", contenido)
        self.assertNotIn("0-xxx", contenido)
        self.assertIn("» Juan: último", contenido)

    def test_contexto_respuesta_y_nota_de_comando(self):
        entradas = [_e(1, RIBBY, "Ribby", "[tarjeta: «Cita en la biblioteca»]", 0, ribby=True,
                       nota="respuesta a un comando de Ana")]
        actual = _e(2, 2, "Juan", "¿Ana tuvo una cita contigo?", 30)
        msgs = conv.mensajes_para_ia(entradas, actual, ahora=T0 + 30, contexto_respuesta="(Está respondiendo a X)")
        self.assertEqual(msgs[0]["role"], "user")
        self.assertIn("comando de Ana", msgs[1]["content"])
        self.assertTrue(msgs[-1]["content"].endswith("(Está respondiendo a X)"))


class TestTextoDeMensaje(unittest.TestCase):
    def test_embeds_y_adjuntos(self):
        embed = NS(title="Reencarne en un ¿Sceptile?", description="✍️ Por **Sr Anderson**\n\nTras haber fallecido...",
                   author=None, fields=[])
        msg = NS(clean_content="Aquí tienes", content="", embeds=[embed], attachments=[NS(filename="historia.pdf")],
                 stickers=[])
        texto = conv.texto_de_mensaje(msg)
        self.assertIn("Aquí tienes", texto)
        self.assertIn("[tarjeta: «Reencarne en un ¿Sceptile?» — ✍️ Por Sr Anderson Tras haber fallecido...]", texto)
        self.assertIn("[adjuntó: historia.pdf]", texto)

    def test_entrada_de_mensaje_marca_a_ribby_y_comandos(self):
        msg = NS(id=5, author=NS(id=RIBBY, name="Ribby", display_name="Ribby"), clean_content="hola",
                 embeds=[], attachments=[], stickers=[], reference=None, created_at=None,
                 interaction_metadata=NS(user=NS(name="ana", display_name="Ana")))
        e = conv.entrada_de_mensaje(msg, RIBBY)
        self.assertTrue(e.es_ribby)
        self.assertEqual(e.nota, "respuesta a un comando de Ana")


class TestLimpiarRespuesta(unittest.TestCase):
    def test_quita_acotaciones_y_prefijos(self):
        crudo = "*Ribby parpadea, confundida.*\n\nRibby: ¿Gracias? Claro que te los recomendé yo 😌"
        self.assertEqual(conv.limpiar_respuesta(crudo), "¿Gracias? Claro que te los recomendé yo 😌")

    def test_conserva_cursivas_dentro_del_texto(self):
        texto = "Eso es *muy* interesante, la verdad."
        self.assertEqual(conv.limpiar_respuesta(texto), texto)

    def test_nunca_devuelve_vacio(self):
        self.assertEqual(conv.limpiar_respuesta("*suspira*"), "*suspira*")


class TestIntencionRecomendacion(unittest.TestCase):
    def test_peticiones_reales(self):
        for t in ["Recomiéndame una historia con Lycanroc", "¿me recomiendas algo de misterio?", "dame una recomendación",
                  "¿tienes alguna buena recomendación?", "¿me puedes recomendar algo?", "sugiéreme algo triste",
                  "¿qué puedo leer hoy?", "busco una historia de terror"]:
            self.assertTrue(rec.es_peticion_recomendacion(t), t)

    def test_no_son_peticiones(self):
        for t in ["Nunca está de más conocer a una bibliotecaria para obtener recomendaciones de lectura",
                  "te recomiendo esta historia, es buenísima", "tu recomendación fue buenísima",
                  "¡Gracias! Se ven como buenos libros para leer. ¿Qué podrías decirme de cada uno?"]:
            self.assertFalse(rec.es_peticion_recomendacion(t), t)


class TestMarcas(unittest.TestCase):
    def test_extrae_y_quita_marcas(self):
        texto, m = conv.extraer_marcas("Mira estas, te van a gustar 😏 [[RECOMENDAR: misterio con Umbreon]] [[REACCION: 📚]]")
        self.assertEqual(texto, "Mira estas, te van a gustar 😏")
        self.assertEqual(m.recomendar, "misterio con Umbreon")
        self.assertEqual(m.reaccion, "📚")
        self.assertFalse(m.silencio)

    def test_silencio_y_variantes(self):
        texto, m = conv.extraer_marcas("[[silencio]]")
        self.assertEqual(texto, "")
        self.assertTrue(m.silencio)
        _, m = conv.extraer_marcas("[[REACCIÓN: 💜]]")
        self.assertEqual(m.reaccion, "💜")

    def test_sin_marcas(self):
        texto, m = conv.extraer_marcas("Hola. [esto no es marca]")
        self.assertEqual(texto, "Hola. [esto no es marca]")
        self.assertIsNone(m.recomendar)


class TestRelaciones(unittest.TestCase):
    def test_par_ordenado(self):
        self.assertEqual(conv.par(20, 3), conv.par(3, 20))

    def test_interlocutores(self):
        canal = [_e(1, 2, "Juan", "hola"), _e(2, RIBBY, "Ribby", "hm", ribby=True)]
        resp_juan = _e(3, 3, "Pedro", "jaja", responde_a=1)
        self.assertEqual(conv.interlocutores(resp_juan, [4], canal, RIBBY), {2, 4})
        resp_ribby = _e(4, 3, "Pedro", "ok", responde_a=2)
        self.assertEqual(conv.interlocutores(resp_ribby, [3, RIBBY], canal, RIBBY), set())

    def test_olvidar_autor(self):
        m = conv.MemoriaCanales()
        m.registrar(10, _e(1, 2, "Juan", "secreto"))
        m.registrar(10, _e(2, 3, "Pedro", "hola"))
        m.olvidar_autor(2)
        self.assertEqual([e.autor for e in m.recientes(10, ahora=T0)], ["Pedro"])


class TestMemoriaEstructurada(unittest.TestCase):
    HOY = date(2026, 11, 23)

    def test_extraccion_valida_y_conserva_datos_del_usuario(self):
        previos = [{"tipo": "apodo", "texto": "Llámame Emlo", "fuente": "usuario", "fecha": "2026-11-01"}]
        respuesta = json.dumps({
            "resumen": "Emlo es curioso y amable.",
            "hechos": [{"tipo": "pokemon", "texto": "Su Pokémon favorito es Leafeon"},
                       {"tipo": "inventado", "texto": "Le gusta el té"}],
            "pendientes": [{"texto": "Examen de matemáticas", "fecha": "2026-11-24"},
                           {"texto": "sin fecha"}],
        })
        resumen, hechos, pendientes = mem.parsear_extraccion("bla " + respuesta, previos, [], self.HOY)
        self.assertEqual(resumen, "Emlo es curioso y amable.")
        textos = [h["texto"] for h in hechos]
        self.assertIn("Llámame Emlo", textos)  # La IA lo omitió, pero lo pidió el usuario
        self.assertEqual(next(h for h in hechos if h["texto"] == "Le gusta el té")["tipo"], "otro")
        self.assertEqual(pendientes, [{"texto": "Examen de matemáticas", "fecha": "2026-11-24", "preguntado": False}])

    def test_respuesta_invalida(self):
        self.assertIsNone(mem.parsear_extraccion("no es json", [], [], self.HOY))

    def test_pendientes_para_hoy_y_preguntados(self):
        pendientes = [
            {"texto": "examen", "fecha": "2026-11-22"},    # ayer → toca preguntar
            {"texto": "viaje", "fecha": "2026-11-30"},     # futuro → todavía no
            {"texto": "partido", "fecha": "2026-11-10"},   # hace mucho → ya no
        ]
        hoy = mem.pendientes_para_hoy(pendientes, self.HOY)
        self.assertEqual([p["texto"] for p in hoy], ["examen"])
        marcados = mem.marcar_preguntados(pendientes, hoy)
        self.assertEqual(mem.pendientes_para_hoy(marcados, self.HOY), [])
        self.assertEqual([p["texto"] for p in mem.pendientes_vigentes(pendientes, self.HOY)], ["examen", "viaje"])
        self.assertEqual(mem.cuando("2026-11-22", self.HOY), "ayer")

    def test_preguntados_se_mantienen_tras_extraer(self):
        previos = [{"texto": "Examen", "fecha": "2026-11-22", "preguntado": True}]
        r = mem.parsear_extraccion(json.dumps({"resumen": "x", "hechos": [], "pendientes": [
            {"texto": "Examen", "fecha": "2026-11-22"}]}), [], previos, self.HOY)
        self.assertTrue(r[2][0]["preguntado"])

    def test_agregar_y_quitar_datos(self):
        hechos = []
        for i in range(mem.MAX_HECHOS + 3):
            hechos = mem.agregar_hecho(hechos, f"dato {i}", self.HOY, fuente="ribby")
        hechos = mem.agregar_hecho(hechos, "Llámame Emlo", self.HOY)
        hechos = mem.agregar_hecho(hechos, "llámame emlo", self.HOY)  # Duplicado
        self.assertEqual(len(hechos), mem.MAX_HECHOS)
        self.assertEqual(sum(1 for h in hechos if "emlo" in h["texto"].lower()), 1)
        self.assertNotIn("dato 0", [h["texto"] for h in hechos])
        self.assertEqual(len(mem.quitar_hecho(hechos, 0)), mem.MAX_HECHOS - 1)

    def test_carga_tolerante(self):
        self.assertEqual(mem.cargar_lista(None), [])
        self.assertEqual(mem.cargar_lista("no json"), [])
        self.assertEqual(mem.cargar_lista('[{"texto": "a"}, 3, {"texto": ""}]'), [{"texto": "a"}])

    def test_contexto_persona(self):
        bloque = mem.contexto_persona(
            [{"tipo": "pokemon", "texto": "Le encanta Leafeon", "fuente": "usuario"}],
            [{"texto": "examen", "fecha": "2026-11-22"}], self.HOY,
        )
        self.assertIn("Pokémon: Le encanta Leafeon (te pidió que lo recordaras)", bloque)
        self.assertIn("examen (era ayer)", bloque)


class TestAccionInicial(unittest.TestCase):
    def test_quita_la_acotacion_pegada_al_principio(self):
        self.assertEqual(conv.limpiar_respuesta("*Ribby se pone roja hasta las orejas y cierra el libro* ¡Tainy! 😳"), "¡Tainy! 😳")
        self.assertEqual(conv.limpiar_respuesta("_Ribby suspira, resignada_ Vale."), "Vale.")

    def test_no_toca_cursivas_normales(self):
        for texto in ["Eso es *muy* interesante.", "*suspira* Vale.", "Hola *Ribby* dijo."]:
            self.assertEqual(conv.limpiar_respuesta(texto), texto)

    def test_historial_sin_acotaciones_de_ribby(self):
        entradas = [_e(1, RIBBY, "Ribby", "*Ribby se sonroja* Hola, Tainy", 0, ribby=True)]
        msgs = conv.mensajes_para_ia(entradas, _e(2, 2, "Tainy", "hola", 10), ahora=T0 + 10)
        self.assertEqual(msgs[1]["content"], "Hola, Tainy")


if __name__ == "__main__":
    unittest.main()
