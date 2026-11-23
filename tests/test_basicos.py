"""
Tests sin red ni base de datos.

Ejecutar desde la raíz del proyecto:
    python -m unittest discover -s tests -v
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord  # noqa: E402
from discord.ext import commands  # noqa: E402

import ai_providers  # noqa: E402
import comun  # noqa: E402
import database  # noqa: E402
import personalidad  # noqa: E402
from cogs import saludos, votacion  # noqa: E402


class TestPersonalidad(unittest.TestCase):
    def test_mencion_negativa_con_puntuacion(self):
        self.assertTrue(personalidad.es_mencion_negativa("ese libro es feo, la verdad"))

    def test_no_confunde_secreto_con_reto(self):
        self.assertFalse(personalidad.es_mencion_negativa("odio guardar un secreto"))

    def test_sin_palabra_negativa(self):
        self.assertFalse(personalidad.es_mencion_negativa("me encanta esta historia"))


class TestComun(unittest.TestCase):
    def test_limitar_bloque_respeta_limite(self):
        lineas = [f"línea {i} " + "x" * 50 for i in range(100)]
        valor = comun.limitar_bloque_embed(lineas, 1024)
        self.assertLessEqual(len(valor), 1024)
        self.assertIn("más", valor)

    def test_limitar_bloque_vacio(self):
        self.assertEqual(comun.limitar_bloque_embed([]), "​")

    def test_nombres_con_caracteres_especiales(self):
        import wattpad
        # Los guiones bajos se conservan al guardar...
        self.assertEqual(wattpad.usuario_de_url("-_CAS_-"), "-_CAS_-")
        self.assertEqual(wattpad.usuario_de_url("https://www.wattpad.com/user/-_CAS_-"), "-_CAS_-")
        # ...y al mostrarlos no se convierten en cursiva, negrita ni spoiler
        self.assertEqual(comun.md("-_CAS_-"), "\\-\\_CAS\\_-")  # El guion inicial también (Discord lo tomaría por lista)
        self.assertEqual(comun.md("||  And If I  ||"), "\\|\\|  And If I  \\|\\|")
        self.assertEqual(comun.md(None), "")

    def test_fecha_corta(self):
        self.assertEqual(comun.fecha_corta("2026-11-22T10:00:00+00:00"), "2026-11-22")
        self.assertEqual(comun.fecha_corta(datetime(2026, 1, 2, tzinfo=timezone.utc)), "2026-01-02")
        self.assertEqual(comun.fecha_corta(None), "N/A")

    def test_refrescar_urls_ignora_urls_externas_y_tolera_fallos(self):
        class HttpQueFalla:
            async def request(self, *a, **k):
                raise RuntimeError("sin red")

        class BotFalso:
            http = HttpQueFalla()

        url = "https://cdn.discordapp.com/attachments/1/2/a.pdf?ex=1"
        res = asyncio.run(comun.refrescar_urls(BotFalso(), [url, "https://ejemplo.com/x.pdf", None]))
        self.assertEqual(res, {url: url})


class TestDatabaseHelpers(unittest.TestCase):
    def test_parse_ts_texto_y_datetime(self):
        dt = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(database._parse_ts(dt.isoformat()), dt)
        self.assertEqual(database._parse_ts(dt), dt)
        self.assertEqual(database._parse_ts("2026-05-01T12:00:00").tzinfo, timezone.utc)

    def test_minutos_desde(self):
        fin = datetime.now(timezone.utc)
        self.assertAlmostEqual(database._minutos_desde((fin - timedelta(minutes=30)).isoformat(), fin), 30, places=3)
        self.assertEqual(database._minutos_desde((fin + timedelta(minutes=5)).isoformat(), fin), 0.0)


class TestTono(unittest.TestCase):
    def test_tonos(self):
        self.assertEqual(saludos._detectar_tono("eres una idiota"), "grosero")
        self.assertEqual(saludos._detectar_tono("gracias Ribby"), "amable")
        self.assertEqual(saludos._detectar_tono("qué hora es"), "neutro")


class TestRotacionGemini(unittest.TestCase):
    def test_prueba_todas_las_llaves_aunque_empiece_al_final(self):
        llamadas = []

        class Resp:
            text = "hola"

        class Modelos:
            def __init__(self, idx, falla):
                self.idx, self.falla = idx, falla

            async def generate_content(self, **kw):
                llamadas.append(self.idx)
                if self.falla:
                    raise RuntimeError("429 RESOURCE_EXHAUSTED")
                return Resp()

        class Cliente:
            def __init__(self, idx, falla):
                self.aio = type("A", (), {"models": Modelos(idx, falla)})()

        prov = ai_providers.GeminiProvider(["k0", "k1", "k2"], "modelo")
        # Solo la llave 0 funciona; empezamos en la 2 (antes nunca se probaba la 0)
        prov._clientes = [Cliente(0, False), Cliente(1, True), Cliente(2, True)]
        prov.current_key_idx = 2
        texto = asyncio.run(prov.generate("sys", [{"role": "user", "content": "hola"}]))
        self.assertEqual(texto, "hola")
        self.assertEqual(llamadas, [2, 0])
        self.assertEqual(prov.current_key_idx, 0)


class TestClaude(unittest.TestCase):
    """Sin red: se sustituye el cliente de Anthropic por uno falso."""

    def _proveedor(self, respuesta=None, error=None):
        from types import SimpleNamespace as NS
        prov = ai_providers.ClaudeProvider("sk-ant-falsa", "claude-haiku-5-5")
        capturado = {}

        async def create(**kw):
            capturado.update(kw)
            if error:
                raise error
            return respuesta

        prov._client = NS(messages=NS(create=create))
        return prov, capturado

    def test_peticion_y_texto(self):
        from types import SimpleNamespace as NS
        resp = NS(stop_reason="end_turn", content=[NS(type="text", text=" Hm. Hola. ")])
        prov, kw = self._proveedor(resp)
        historial = [{"role": "user", "content": "hola"}, {"role": "ribby", "content": "¿qué?"},
                     {"role": "user", "content": "nada"}]
        texto = asyncio.run(prov.generate("eres Ribby", historial))
        self.assertEqual(texto, "Hm. Hola.")
        self.assertEqual(kw["model"], "claude-haiku-5-5")
        self.assertEqual(kw["system"], "eres Ribby")
        self.assertEqual([m["role"] for m in kw["messages"]], ["user", "assistant", "user"])
        self.assertEqual(kw["thinking"], {"type": "disabled"})
        self.assertEqual(kw["output_config"], {"effort": "low"})

    def test_rechazo_lanza_error_para_pasar_al_respaldo(self):
        from types import SimpleNamespace as NS
        prov, _ = self._proveedor(NS(stop_reason="refusal", content=[]))
        with self.assertRaises(RuntimeError):
            asyncio.run(prov.generate("s", [{"role": "user", "content": "x"}]))

    def test_manager_usa_respaldo_si_claude_falla(self):
        class Respaldo(ai_providers.AIProvider):
            nombre = "Respaldo"

            async def generate(self, system_prompt, chat_history, max_tokens=None):
                return "respaldo ok"

        prov, _ = self._proveedor(error=RuntimeError("Claude: servicio saturado (529)"))
        manager = ai_providers.ProviderManager.__new__(ai_providers.ProviderManager)
        manager.providers = [prov, Respaldo()]
        self.assertEqual(asyncio.run(manager.generate("s", [{"role": "user", "content": "x"}])), "respaldo ok")


def _historia(i, titulo, tags, desc="", **extra):
    return {"id": i, "titulo": titulo, "tags": tags, "descripcion": desc, "autor_nombre": f"autor{i}", **extra}


CATALOGO = [
    _historia(1, "Luna de Sangre - Remake", ["amor", "lycanroc", "sylveon", "escolar", "romance", "pokemon"],
              "Alexander llegó a Crescent Valley High buscando invisibilidad."),
    _historia(2, "Reencarne en un ¿Sceptile?", ["reencarnacion", "aventura", "sceptile", "pokemon"],
              "Un humano despierta convertido en Sceptile."),
    _historia(3, "𝑷𝒐𝒌𝒆𝒎𝒐𝒏: 𝑪𝒚𝒃𝒆𝒓𝒑𝒖𝒏𝒌 𝑮𝒆𝒏𝒆𝒓𝒂𝒕𝒊𝒐𝒏", ["cyberpunk", "misterio", "pokemon"], "Alux investiga un caso."),
    _historia(4, "Historia de reto sin datos", []),
]
POKEMON = {"lycanroc", "sylveon", "sceptile", "riolu", "braixen"}


class TestRecomendador(unittest.TestCase):
    def test_normaliza_letras_decoradas_y_acentos(self):
        import recomendador as rec
        self.assertEqual(rec.normalizar("𝑷𝒐𝒌𝒆𝒎𝒐𝒏: Reencarné"), "pokemon reencarne")

    def test_busqueda_tolera_errores_de_escritura(self):
        import recomendador as rec
        for consulta in ("una historia que tenga a Lycanroc", "algo con licanroc", "LYCANROCS"):
            mejor = rec.candidatos(CATALOGO, consulta)[0][1]
            self.assertEqual(mejor["id"], 1, consulta)

    def test_busqueda_por_genero_y_descripcion(self):
        import recomendador as rec
        self.assertEqual(rec.candidatos(CATALOGO, "reencarnación")[0][1]["id"], 2)
        self.assertEqual(rec.candidatos(CATALOGO, "algo de cyberpunk")[0][1]["id"], 3)

    def test_intenciones(self):
        import recomendador as rec
        self.assertTrue(rec.es_peticion_recomendacion("Recomiéndame una historia con Lycanroc"))
        self.assertTrue(rec.es_peticion_recomendacion("¿qué puedo leer hoy?"))
        self.assertTrue(rec.es_peticion_recomendacion("busco una historia de terror"))
        self.assertFalse(rec.es_peticion_recomendacion("hola Ribby, ¿cómo estás?"))
        self.assertTrue(rec.es_peticion_resumen("¿de qué trata Luna de Sangre?"))
        self.assertEqual(rec.extraer_consulta("<@123> recomiéndame una historia con Lycanroc"), "una historia con Lycanroc")

    def test_buscar_por_titulo(self):
        import recomendador as rec
        self.assertEqual(rec.buscar_por_titulo(CATALOGO, "¿de qué trata luna de sangre?")["id"], 1)
        self.assertIsNone(rec.buscar_por_titulo(CATALOGO, "de qué trata el señor de los anillos"))

    def test_parsear_respuesta_descarta_ids_inventados(self):
        import recomendador as rec
        ids, msg = rec.parsear_respuesta('Claro: {"ids": [1, 99, "2", 1], "mensaje": "Hm. Toma."}', {1, 2, 3})
        self.assertEqual(ids, [1, 2])
        self.assertEqual(msg, "Hm. Toma.")
        self.assertEqual(rec.parsear_respuesta("no es json", {1}), ([], ""))

    def test_preguntas_pendientes(self):
        import recomendador as rec
        self.assertEqual(rec.preguntas_pendientes(CATALOGO[3], POKEMON), ["genero", "pokemon", "descripcion"])
        self.assertEqual(rec.preguntas_pendientes(CATALOGO[0], POKEMON), [])
        # Cyberpunk tiene género y es de Pokémon, pero ningún Pokémon concreto
        self.assertEqual(rec.preguntas_pendientes(CATALOGO[2], POKEMON), ["pokemon"])

    def test_opciones_comunes(self):
        import recomendador as rec
        self.assertEqual(len(rec.opciones_comunes(CATALOGO, "genero", POKEMON)), 3)
        self.assertNotIn("lycanroc", rec.opciones_comunes(CATALOGO, "pokemon", POKEMON, excluir=["lycanroc"]))


class TestAfinidad(unittest.TestCase):
    T0 = datetime(2026, 1, 1, 18, tzinfo=timezone.utc)

    def _jugar(self, dias, coquetea=True, mensajes=30):
        import afinidad as af
        e = af.nuevo_estado()
        for d in range(dias):
            for i in range(mensajes):
                af.aplicar_interaccion(e, "amable", coquetea and i % 3 == 0, False, self.T0 + timedelta(days=d, minutes=i))
        return e

    def test_tope_diario_impide_farmear(self):
        import afinidad as af
        e = self._jugar(1, mensajes=500)
        self.assertLessEqual(e["corazones"], af.TOPE_DIARIO_CHARLA)

    def test_llegar_al_maximo_lleva_cerca_de_un_mes(self):
        import afinidad as af
        self.assertLess(self._jugar(30)["corazones"], af.MAX_CORAZONES)
        self.assertEqual(self._jugar(45)["corazones"], af.MAX_CORAZONES)

    def test_sin_coqueteo_no_pasa_de_mejor_amigo(self):
        import afinidad as af
        e = self._jugar(60, coquetea=False)
        self.assertEqual(af.nivel(e, False), "mejor_amigo")

    def test_groseria_resta(self):
        import afinidad as af
        e = af.nuevo_estado()
        e["corazones"] = 20.0
        af.aplicar_interaccion(e, "grosero", False, False, self.T0)
        self.assertEqual(e["corazones"], 18.0)

    def test_declaraciones(self):
        import afinidad as af
        e = dict(af.nuevo_estado(), corazones=100.0)
        self.assertEqual(af.declarar(dict(e), True, self.T0), "ocupada")
        self.assertEqual(af.declarar(dict(af.nuevo_estado(), corazones=20.0), False, self.T0), "pronto")
        casi = dict(af.nuevo_estado(), corazones=80.0)
        self.assertEqual(af.declarar(casi, False, self.T0), "casi")
        self.assertEqual(af.declarar(casi, False, self.T0 + timedelta(hours=2)), "espera")
        self.assertEqual(af.declarar(e, False, self.T0), "acepta")
        self.assertEqual(af.nivel(e), "pareja")
        self.assertEqual(af.declarar(e, False, self.T0), "ya_pareja")

    def test_interes_se_pierde_si_no_se_declara(self):
        import afinidad as af
        e = dict(af.nuevo_estado(), corazones=100.0, fecha_maximo=self.T0.isoformat(), ultima_interaccion=self.T0.isoformat())
        self.assertEqual(af.aplicar_paso_del_tiempo(e, self.T0 + timedelta(days=6)), [])
        self.assertEqual(af.aplicar_paso_del_tiempo(e, self.T0 + timedelta(days=8)), ["interes_perdido"])
        self.assertEqual(af.nivel(e), "amigo")

    def test_pareja_ausente_termina_en_buenos_terminos(self):
        import afinidad as af
        e = dict(af.nuevo_estado(), corazones=100.0, es_pareja=True, ultima_interaccion=self.T0.isoformat())
        self.assertEqual(af.aplicar_paso_del_tiempo(e, self.T0 + timedelta(days=31)), ["fin_pareja"])
        self.assertFalse(e["es_pareja"])
        self.assertEqual(af.nivel(e), "mejor_amigo")

    def test_inactividad_se_cobra_una_sola_vez(self):
        import afinidad as af
        e = dict(af.nuevo_estado(), corazones=50.0, ultima_interaccion=self.T0.isoformat())
        af.aplicar_paso_del_tiempo(e, self.T0 + timedelta(days=20))
        af.aplicar_paso_del_tiempo(e, self.T0 + timedelta(days=20, hours=5))
        self.assertEqual(e["corazones"], 44.0)

    def test_deteccion(self):
        import afinidad as af
        self.assertTrue(af.es_declaracion("Ribby, ¿quieres ser mi novia?"))
        self.assertTrue(af.es_declaracion("seamos pareja"))
        self.assertFalse(af.es_declaracion("¿quieres ser mi amiga?"))
        self.assertTrue(af.es_coqueteo("eres muy linda hoy 😍"))
        self.assertFalse(af.es_coqueteo("recomiéndame un libro"))

    def test_contexto_incluye_reglas_de_declaracion(self):
        import afinidad as af
        e = dict(af.nuevo_estado(), corazones=100.0, es_pareja=True)
        texto = af.contexto_prompt(e, False, evento_declaracion="ya_pareja")
        self.assertIn("PAREJA", texto)
        self.assertIn("AHORA MISMO", texto)


class TestTemporadasYLogros(unittest.TestCase):
    def test_eventos_por_fecha(self):
        import temporadas as t
        from datetime import date
        self.assertEqual(t.evento_actual(date(2026, 2, 14))["id"], "san_valentin")
        self.assertEqual(t.evento_actual(date(2026, 4, 23))["id"], "dia_libro")
        self.assertEqual(t.evento_actual(date(2026, 11, 1))["id"], "halloween")
        self.assertIsNone(t.evento_actual(date(2026, 7, 15)))
        # Navidad cruza de año: el 3 de enero pertenece a la edición del año anterior
        navidad = t.evento_actual(date(2027, 1, 3))
        self.assertEqual(t.edicion(navidad, date(2027, 1, 3)), "navidad-2026")
        self.assertEqual(t.edicion(navidad, date(2026, 12, 20)), "navidad-2026")
        self.assertIn("TEMPORADA", t.contexto_hoy(date(2026, 12, 24)))

    def test_cada_evento_tiene_su_contenido(self):
        import temporadas as t
        for e in t.EVENTOS:
            self.assertTrue(e["anuncio"] and e["contexto"] and e["regalo"]["respuesta"])
            self.assertEqual(len(e["cita"]["opciones"]), 3)

    def test_logros(self):
        import logros as lg
        self.assertEqual(lg.evaluar({}), set())
        ctx = {"nivel": "algo_mas", "total_interacciones": 120, "racha_dias": 8, "citas_total": 1}
        self.assertEqual(
            lg.evaluar(ctx),
            {"amigo", "mejor_amigo", "algo_mas", "primera_charla", "charlas_100", "racha_7", "primera_cita"},
        )
        self.assertIn("pareja", lg.evaluar({"nivel": "pareja"}))
        self.assertIn("lector_10", lg.evaluar({"misiones": 10}))
        self.assertNotIn("critico", lg.evaluar({"resenas": 4}))


class TestLoreYQuiz(unittest.TestCase):
    def test_capitulos_bien_formados(self):
        import afinidad as af
        import ribby_lore as lr
        self.assertEqual([c["nivel"] for c in lr.CAPITULOS], ["amigo", "mejor_amigo", "algo_mas", "pareja"])
        for c in lr.CAPITULOS:
            self.assertIn(c["nivel"], af.NIVELES)
            self.assertTrue(all(len(p) <= 4096 for p in c["paginas"]))
            self.assertEqual(len(c["opciones"]), 3)
            for texto, delta, reaccion, recuerdo in c["opciones"]:
                self.assertLessEqual(len(texto), 80)  # Límite de etiqueta de botón
                self.assertTrue(reaccion and recuerdo)

    def test_preguntas_respetan_capitulos_leidos(self):
        import ribby_lore as lr
        for _ in range(200):
            q = lr.pregunta_sobre_ribby(set())
            self.assertNotIn(q["pregunta"], {p[0] for p in lr.PREGUNTAS_RIBBY if p[2] and p[3]})
            self.assertEqual(len(set(q["opciones"])), 4)
            self.assertIn(q["correcta"], q["opciones"])
        preguntas_con_lore = {lr.pregunta_sobre_ribby({1, 2, 3, 4})["pregunta"] for _ in range(400)}
        self.assertIn("¿Cuántos libros salvé del incendio?", preguntas_con_lore)

    def test_logros_nuevos(self):
        import logros as lg
        self.assertEqual(lg.evaluar({"capitulos": 4, "quiz_aciertos": 10}), {"primer_capitulo", "lore_completo", "te_conozco"})


class TestModoPruebas(unittest.TestCase):
    def tearDown(self):
        comun.activar_modo_global(False)
        comun.marcar_usuario(None)

    def test_reescritura_de_tablas(self):
        sql = ("INSERT INTO votos (x) SELECT 1 FROM participantes p LEFT JOIN votos v ON p.id = v.participante_id "
               "WHERE p.votos > 0 FOR UPDATE")
        r = database.sql_para_pruebas(sql)
        self.assertIn("INTO pruebas.votos", r)
        self.assertIn("FROM pruebas.participantes", r)
        self.assertIn("JOIN pruebas.votos", r)
        self.assertIn("p.votos > 0", r)          # Una columna con el mismo nombre no se toca
        self.assertTrue(r.endswith("FOR UPDATE"))  # "FOR UPDATE" no es una tabla
        self.assertIn("DO UPDATE SET", database.sql_para_pruebas("ON CONFLICT (a) DO UPDATE SET b = 1"))

    def test_modo_global_afecta_a_todos(self):
        ejecutado = []

        class Conn:
            async def fetchval(self, sql, *a):
                ejecutado.append(sql)

        class PoolFalso:
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def acquire(self):
                yield Conn()

        pool = database.PoolEnrutado(PoolFalso())

        async def consulta_como(uid, servidor=123):
            comun.marcar_usuario(uid, servidor)
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT COUNT(*) FROM eventos")

        async def varios():
            await asyncio.gather(consulta_como(111), consulta_como(222), consulta_como(None, None))

        asyncio.run(varios())  # Modo desactivado: todo a la base real
        self.assertEqual(ejecutado, ["SELECT COUNT(*) FROM eventos"] * 3)

        ejecutado.clear()
        comun.activar_modo_global(True)
        asyncio.run(varios())  # Activado: cualquier usuario (y tareas sin usuario) van a pruebas
        self.assertEqual(ejecutado, ["SELECT COUNT(*) FROM pruebas.eventos"] * 3)

        with comun.contexto_real():  # Guardar el interruptor siempre va a la base real
            self.assertFalse(comun.en_prueba())
        self.assertTrue(comun.en_prueba())

    def test_servidor_de_pruebas_siempre_usa_la_base_de_pruebas(self):
        import config
        self.assertIn(1489169806128185517, config.GUILDS_PRUEBAS)
        comun.marcar_usuario(333, 1489169806128185517)  # Cualquiera, en el servidor de pruebas
        self.assertTrue(comun.en_prueba())
        comun.marcar_usuario(333, 123)                  # La misma persona en La Comarca
        self.assertFalse(comun.en_prueba())

    def test_creador_solo_por_id(self):
        from types import SimpleNamespace as NS
        tainy = 641420040045985803
        self.assertTrue(comun.es_creador(NS(id=tainy, name="cualquier_nombre")))
        self.assertTrue(comun.es_creador_id(tainy))
        # Quien se ponga su antiguo nombre de usuario NO es el creador
        self.assertFalse(comun.es_creador(NS(id=5, name="peso_pluma__.")))
        self.assertTrue(comun.creador_activo(tainy))
        comun.activar_modo_global(True)
        self.assertTrue(comun.creador_activo(tainy))   # En pruebas sigue siendo "papá" por defecto…
        comun.fijar_creador_familia_en_pruebas(False)
        self.assertFalse(comun.creador_activo(tainy))  # …salvo que elija probar como un usuario normal
        comun.activar_modo_global(False)
        self.assertTrue(comun.creador_activo(tainy))   # Fuera de pruebas, siempre es su creador
        comun.fijar_creador_familia_en_pruebas(True)

    def test_afinidad_del_creador(self):
        import afinidad as af
        e = dict(af.nuevo_estado(), es_creador=True)
        af.aplicar_interaccion(e, "amable", True, False)
        self.assertEqual(af.nivel(e), "creador")
        self.assertEqual(e["corazones"], af.MAX_CORAZONES)
        self.assertEqual(e["coqueteos"], 0)
        self.assertEqual(af.declarar(e, False), "creador")
        self.assertFalse(e["es_pareja"])
        e["ultima_interaccion"] = (af.ahora() - timedelta(days=90)).isoformat()
        self.assertEqual(af.aplicar_paso_del_tiempo(e), [])  # Su cariño no se enfría
        self.assertIn("CREADOR", af.contexto_prompt(e, False, evento_declaracion="creador"))


class TestHuggingFace(unittest.TestCase):
    """Un servidor local imita la API de Hugging Face (sin red ni token real)."""

    def _con_servidor(self, rutas, prueba):
        from aiohttp import web
        import config
        import hugging_face as hf

        recibido = []

        async def main():
            app = web.Application()
            for ruta, respuesta in rutas.items():
                async def handler(request, respuesta=respuesta):
                    recibido.append((request.path, request.headers.get("Authorization"), await request.json()))
                    if isinstance(respuesta, int):
                        return web.Response(status=respuesta, text="caído")
                    return web.json_response(respuesta)
                app.router.add_post(ruta, handler)
            runner = web.AppRunner(app)
            await runner.setup()
            sitio = web.TCPSite(runner, "127.0.0.1", 0)
            await sitio.start()
            puerto = sitio._server.sockets[0].getsockname()[1]
            base = f"http://127.0.0.1:{puerto}"
            antes = (hf._URL_MODELO, config.HF_TOKEN)
            hf._URL_MODELO, config.HF_TOKEN = base + "/hf-inference/models/{modelo}", "hf_falso"
            try:
                return await prueba(base)
            finally:
                hf._URL_MODELO, config.HF_TOKEN = antes
                await runner.cleanup()

        return asyncio.run(main()), recibido

    def _rutas(self, tonos, toxico):
        import config
        import hugging_face as hf
        desc = list(hf.CATEGORIAS.values())
        return {
            f"/hf-inference/models/{config.HF_MODELO_TONO}": [
                {"label": desc[list(hf.CATEGORIAS).index(k)], "score": v} for k, v in tonos.items()
            ],
            f"/hf-inference/models/{config.HF_MODELO_TOXICIDAD}": [[
                {"label": "toxic", "score": toxico}, {"label": "neutral", "score": 1 - toxico},
            ]],
        }

    def test_coqueteo_detectado_aunque_las_palabras_clave_no_lo_vean(self):
        import hugging_face as hf
        rutas = self._rutas({"coqueteo": 0.8, "amable": 0.1, "grosero": 0.02, "sexual": 0.03, "neutro": 0.05}, 0.02)

        async def prueba(_):
            return await hf.analizar("no eres nada fea, la verdad", "neutro", False)

        r, recibido = self._con_servidor(rutas, prueba)
        self.assertEqual((r.tono, r.coqueteo, r.bloquear, r.fuente), ("amable", True, False, "hugging_face"))
        ruta, auth, cuerpo = next(x for x in recibido if "candidate_labels" in str(x[2]))
        self.assertEqual(auth, "Bearer hf_falso")
        self.assertEqual(cuerpo["parameters"]["hypothesis_template"], "Este mensaje es {}.")
        self.assertEqual(len(cuerpo["parameters"]["candidate_labels"]), 5)

    def test_moderacion_por_toxicidad_y_por_contenido_sexual(self):
        import hugging_face as hf
        toxico = self._rutas({"grosero": 0.9, "amable": 0.02, "coqueteo": 0.02, "sexual": 0.03, "neutro": 0.03}, 0.97)
        sexual = self._rutas({"sexual": 0.85, "coqueteo": 0.1, "amable": 0.02, "grosero": 0.02, "neutro": 0.01}, 0.3)

        async def prueba(_):
            return await hf.analizar("mensaje de prueba", "neutro", False)

        r, _ = self._con_servidor(toxico, prueba)
        self.assertEqual((r.bloquear, r.motivo, r.tono), (True, "toxicidad", "grosero"))
        r, _ = self._con_servidor(sexual, prueba)
        self.assertEqual((r.bloquear, r.motivo), (True, "sexual"))

    def test_si_hugging_face_cae_se_usan_las_reglas(self):
        import config
        import hugging_face as hf
        rutas = {f"/hf-inference/models/{config.HF_MODELO_TONO}": 503,
                 f"/hf-inference/models/{config.HF_MODELO_TOXICIDAD}": 503}

        async def prueba(_):
            return await hf.analizar("eres una idiota", "grosero", False)

        r, _ = self._con_servidor(rutas, prueba)
        self.assertEqual((r.tono, r.bloquear, r.fuente), ("grosero", False, "reglas"))
        # Y sin token ni siquiera se intenta
        self.assertEqual(asyncio.run(hf.analizar("hola Ribby", "amable", False)).fuente, "reglas")

    def test_proveedor_de_chat_y_limpieza_de_razonamiento(self):
        import config
        respuesta = {"choices": [{"message": {"role": "assistant", "content": "<think>pienso...</think>Hm. Hola. 🎀"}}]}

        async def prueba(base):
            prov = ai_providers.OpenAICompatibleProvider(
                "Hugging Face", "hf_falso", config.HF_CHAT_MODEL, base + "/v1/chat/completions"
            )
            return await prov.generate("eres Ribby", [{"role": "user", "content": "hola"}])

        texto, recibido = self._con_servidor({"/v1/chat/completions": respuesta}, prueba)
        self.assertEqual(texto, "Hm. Hola. 🎀")
        _, auth, cuerpo = recibido[0]
        self.assertEqual(auth, "Bearer hf_falso")
        self.assertEqual(cuerpo["model"], "meta-llama/Llama-3.3-70B-Instruct:cheapest")
        self.assertEqual(cuerpo["messages"][0], {"role": "system", "content": "eres Ribby"})

    def test_orden_de_proveedores(self):
        from types import SimpleNamespace as NS
        cfg = NS(ANTHROPIC_API_KEY="a", CLAUDE_MODEL="claude-haiku-5-5", HF_TOKEN="h", HF_CHAT_MODEL="m",
                 GROQ_API_KEY="g", GROQ_MODEL="x", GEMINI_API_KEYS=[], OPENROUTER_API_KEY="", OPENROUTER_MODEL="")
        nombres = [p.nombre for p in ai_providers.ProviderManager(cfg).providers]
        self.assertEqual(nombres, ["Claude", "Hugging Face", "Groq"])


class TestWattpadUrls(unittest.TestCase):
    def test_extraer_y_clasificar(self):
        import wattpad
        texto = "oye Ribby añade esta https://www.wattpad.com/story/409289758-luna-de-sangre-remake, es buenísima!"
        self.assertEqual(wattpad.extraer_urls(texto), ["https://www.wattpad.com/story/409289758-luna-de-sangre-remake"])
        self.assertEqual(wattpad.id_lista("https://www.wattpad.com/list/1584836335"), "1584836335")
        self.assertEqual(wattpad.usuario_de_url("https://www.wattpad.com/user/-_CAS_-"), "-_CAS_-")
        self.assertEqual(wattpad.usuario_de_url("@Kasper242"), "Kasper242")
        self.assertIsNone(wattpad.usuario_de_url("esto no es un usuario"))


class TestVotoView(unittest.TestCase):
    def test_reparte_mas_de_25_historias_en_varios_menus(self):
        async def crear():
            participantes = [
                {"id": i, "titulo_historia": f"Historia {i}", "usuario_nombre": f"autor{i}", "usuario_discord_id": str(i)}
                for i in range(1, 61)
            ]
            return votacion.VotoView(None, 1, 1, participantes)

        view = asyncio.run(crear())
        menus = [c for c in view.children if isinstance(c, discord.ui.Select)]
        self.assertEqual([len(m.options) for m in menus], [25, 25, 10])


class TestCargaDeCogs(unittest.TestCase):
    def test_todos_los_cogs_cargan(self):
        async def cargar():
            bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
            bot.db = None  # type: ignore[attr-defined]
            from main import COGS
            for cog in COGS:
                await bot.load_extension(cog)
            import config
            nombres = {c.qualified_name for c in bot.tree.walk_commands()}
            for gid in config.GUILD_IDS:  # Con GUILD_ID los comandos viven en cada servidor
                nombres |= {c.qualified_name for c in bot.tree.walk_commands(guild=discord.Object(id=gid))}
            await bot.close()
            return nombres

        nombres = asyncio.run(cargar())
        for esperado in ["evento crear", "evento iniciar_votacion", "votar", "reto info", "help", "admin_help",
                         "participante_registrar", "biblioteca recomendar", "biblioteca agregar",
                         "ribby corazones", "ribby cita", "ribby regalar", "ribby mision", "ribby evento",
                         "ribby logros", "ribby cumpleanos", "ribby avisos", "ribby canal", "biblioteca resenar",
                         "ribby historia", "ribby quiz", "biblioteca seguir", "biblioteca autor",
                         "prueba activar", "prueba nivel", "prueba tiempo", "prueba capitulo_nuevo",
                         "novedades", "admin_novedades"]:
            self.assertIn(esperado, nombres)


class TestPromptCaching(unittest.TestCase):
    def test_partes_del_system_prompt(self):
        bloques = ai_providers.ClaudeProvider._system(["fijo", "", "variable"])
        self.assertEqual(bloques[0], {"type": "text", "text": "fijo", "cache_control": {"type": "ephemeral"}})
        self.assertEqual(bloques[1], {"type": "text", "text": "variable"})
        self.assertEqual(ai_providers.ClaudeProvider._system("solo texto"), "solo texto")
        self.assertEqual(ai_providers.unir_system(["a", "b"]), "a\n\nb")

    def test_prompt_de_ribby_tiene_parte_fija_estable(self):
        cog = saludos.Saludos.__new__(saludos.Saludos)
        a = cog._construir_system_prompt("Emlo", "frio", 3, 10, False, contexto_extra="RETOS: nada")
        b = cog._construir_system_prompt("Pedro", "calido", 40, 99, True, resumen="x", relacion="amigo")
        self.assertEqual(a[0], b[0])  # La parte cacheable no cambia entre usuarios
        self.assertNotIn("Emlo", a[0])
        self.assertIn("Emlo", a[1])
        self.assertIn("[[RECOMENDAR", a[0])


class TestParejaEnElContexto(unittest.TestCase):
    def test_cualquiera_sabe_quien_es_su_pareja(self):
        import afinidad as af
        # Antes, a un desconocido o a un amigo Ribby le decía que no tenía pareja
        for corazones in (0.0, 20.0):
            texto = af.contexto_prompt(dict(af.nuevo_estado(), corazones=corazones), True, "Ana")
            self.assertIn("Tienes pareja: Ana", texto)
            self.assertIn("hablas BIEN de esa persona", texto)

    def test_con_su_pareja_usa_apodos_cariñosos(self):
        import afinidad as af
        texto = af.contexto_prompt(dict(af.nuevo_estado(), corazones=100.0, es_pareja=True), False)
        self.assertIn("mi amor", texto)


if __name__ == "__main__":
    unittest.main()
