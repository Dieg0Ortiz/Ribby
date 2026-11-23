"""
cogs/biblioteca.py — Biblioteca de recomendaciones de Ribby.

Fuentes de historias:
  - Listas de lectura de Wattpad (config.WATTPAD_LISTAS), sincronizadas a diario.
  - Historias de los retos literarios (participantes + sus PDFs).
  - Links de Wattpad que añaden los usuarios (comando o mencionando a Ribby).

Menciones que entiende (las enruta cogs/saludos.py):
  - "@Ribby recomiéndame una historia con Lycanroc"
  - "@Ribby esta historia es buenísima, añádela https://www.wattpad.com/story/..."
  - "@Ribby ¿de qué trata Luna de Sangre?"

Comandos /biblioteca: recomendar, agregar, ver, etiquetar, resumir,
vincular_wattpad, eliminar (admin), sincronizar (admin).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict, deque
from time import monotonic
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import calidad
import config
import database
import hugging_face
import recomendador as rec
import wattpad
from ai_providers import ProviderManager
from comun import en_prueba, es_admin, es_admin_miembro, refrescar_urls, md

log = logging.getLogger("bot-literario.biblioteca")

COLOR_MADURA = 0xB91C1C
_TAGS_OCULTOS = {"sin pokemon"}
_CACHE_SEGUNDOS = 300
_SIN_PING = discord.AllowedMentions.none()


def _num(n: Optional[int]) -> str:
    return f"{n:,}".replace(",", ".") if isinstance(n, int) else "?"


def _fuente_aporte(usuario_id: int, historia: dict[str, Any]) -> str:
    """Lo que escribe el autor de la historia tiene prioridad sobre el resto."""
    return "autor" if str(usuario_id) == str(historia.get("autor_discord") or "") else "usuario"


_VIGENCIA_MOSTRADAS = 3 * 60 * 60  # Segundos durante los que Ribby "tiene presentes" las tarjetas que mostró


def _ficha_charla(h: dict[str, Any]) -> str:
    """Una historia en pocas líneas para el prompt de la charla."""
    datos = [f"«{h.get('titulo') or 'Sin título'}» de {h.get('autor_nombre') or 'autor desconocido'}"]
    tags = [t for t in (h.get("tags") or []) if t not in _TAGS_OCULTOS][:12]
    if tags:
        datos.append("etiquetas: " + ", ".join(tags))
    if h.get("partes"):
        datos.append(f"{h['partes']} partes, {'terminada' if h.get('completada') else 'en curso'}")
    if h.get("lecturas"):
        datos.append(f"{h['lecturas']} lecturas en Wattpad")
    if h.get("nota_media") is not None:
        datos.append(f"nota de la comunidad {h['nota_media']}/5 ({h.get('num_resenas') or 0} reseñas)")
    if h.get("evento_nombre"):
        datos.append(f"participó en el reto «{h['evento_nombre']}»")
    if h.get("madura"):
        datos.append("marcada como +18")
    desc = " ".join((h.get("descripcion") or "").split())
    sinopsis = (desc[:600] + "…") if len(desc) > 600 else (desc or "(no tienes su sinopsis)")
    return "- " + " | ".join(datos) + f"\n  Sinopsis: {sinopsis}"


_MIN_PALABRAS_RESUMEN = 6


def _separar(texto: str) -> list[str]:
    return [t.strip().lstrip("#") for t in texto.replace(";", ",").replace("\n", ",").split(",") if t.strip()]


# ─────────────────────────── Vistas: completar fichas ───────────────────────────

_TEXTOS_PREGUNTA = {
    "genero": "📚 **¿Qué géneros tiene _{titulo}_?** (puedes elegir varios)",
    "pokemon": "🐾 **¿Qué Pokémon aparecen en _{titulo}_?** (puedes elegir varios)",
    "descripcion": "📝 **¿Me escribes un resumen corto de _{titulo}_?** Si eres quien la escribió, el tuyo tiene prioridad.",
}


class TextoLibreModal(discord.ui.Modal):
    """Para la opción "Otro…" y para escribir resúmenes."""

    def __init__(self, titulo: str, etiqueta: str, largo: bool, al_enviar):
        super().__init__(title=titulo[:45])
        self._al_enviar = al_enviar
        self.campo = discord.ui.TextInput(
            label=etiqueta[:45],
            style=discord.TextStyle.paragraph if largo else discord.TextStyle.short,
            max_length=1500 if largo else 200,
            placeholder=None if largo else "Separa con comas, por ejemplo: misterio, drama",
        )
        self.add_item(self.campo)

    async def on_submit(self, interaction: discord.Interaction):
        await self._al_enviar(interaction, str(self.campo.value))


class AyudaFichaView(discord.ui.View):
    """Hace preguntas una a una para completar la ficha de una historia."""

    def __init__(self, cog: "Biblioteca", historia: dict[str, Any], preguntas: list[str], intro: str):
        super().__init__(timeout=900)
        self.cog = cog
        self.historia = historia
        self.preguntas = preguntas
        self.intro = intro
        self.paso = 0
        self.ayudantes: set[int] = set()
        self.message: Optional[discord.Message] = None

    # ── Construcción ──

    def contenido(self) -> str:
        q = self.preguntas[self.paso]
        texto = _TEXTOS_PREGUNTA[q].format(titulo=self.historia["titulo"])
        return f"{self.intro}\n{texto}" if self.paso == 0 and self.intro else texto

    async def preparar(self) -> None:
        self.clear_items()
        q = self.preguntas[self.paso]
        if q in ("genero", "pokemon"):
            catalogo = await self.cog.catalogo()
            comunes = rec.opciones_comunes(catalogo, q, self.cog.pokemon, self.historia.get("tags") or [])
            opciones = [discord.SelectOption(label=c.title()[:100], value=c[:100]) for c in comunes]
            opciones.append(discord.SelectOption(label="Otro…", value="__otro__", emoji="✏️"))
            if q == "pokemon":
                opciones.append(discord.SelectOption(label="Ninguno", value="__ninguno__", emoji="🚫"))
            opciones.append(discord.SelectOption(label="No lo sé", value="__nose__", emoji="🤷"))
            select = discord.ui.Select(
                placeholder="Elige una o varias opciones...", min_values=1, max_values=len(opciones), options=opciones
            )
            select.callback = self._al_elegir  # type: ignore[method-assign]
            self.add_item(select)
        else:
            escribir = discord.ui.Button(label="Escribir resumen", emoji="✍️", style=discord.ButtonStyle.primary)
            escribir.callback = self._abrir_resumen  # type: ignore[method-assign]
            saltar = discord.ui.Button(label="Ahora no", style=discord.ButtonStyle.secondary)
            saltar.callback = self._saltar  # type: ignore[method-assign]
            self.add_item(escribir)
            self.add_item(saltar)

    async def avanzar(self, interaction: discord.Interaction, aporto: bool) -> None:
        if aporto:
            self.ayudantes.add(interaction.user.id)
        self.paso += 1
        if self.paso >= len(self.preguntas):
            self.stop()
            if self.ayudantes:
                nombres = ", ".join(f"<@{u}>" for u in self.ayudantes)
                final = f"🎀 ¡Gracias, {nombres}! Ya actualicé mi ficha de **{md(self.historia['titulo'])}**. ...No es que lo necesitara, pero se agradece."
            else:
                final = f"📚 Bueno, seguiré investigando **{md(self.historia['titulo'])}** por mi cuenta."
            return await interaction.response.edit_message(content=final, view=None, allowed_mentions=_SIN_PING)
        await self.preparar()
        await interaction.response.edit_message(content=self.contenido(), view=self)

    # ── Callbacks ──

    async def _al_elegir(self, interaction: discord.Interaction):
        q = self.preguntas[self.paso]
        valores = list(interaction.data.get("values", []))  # type: ignore[union-attr]
        elegidos = [v for v in valores if not v.startswith("__")]
        fuente = _fuente_aporte(interaction.user.id, self.historia)
        uid = str(interaction.user.id)

        if "__ninguno__" in valores:
            elegidos.append("sin pokemon")
        if elegidos:
            await database.agregar_etiquetas(self.cog.db, self.historia["id"], elegidos, fuente, uid)
            self.historia["tags"] = list(set(self.historia.get("tags") or []) | set(elegidos))
            self.cog.invalidar()

        if "__otro__" in valores:
            etiqueta = "¿Qué géneros?" if q == "genero" else "¿Qué Pokémon?"

            async def guardar_otro(inter: discord.Interaction, texto: str):
                nuevos = _separar(texto)
                if nuevos:
                    await database.agregar_etiquetas(self.cog.db, self.historia["id"], nuevos, fuente, uid)
                    self.historia["tags"] = list(set(self.historia.get("tags") or []) | set(nuevos))
                    self.cog.invalidar()
                await self.avanzar(inter, bool(nuevos) or bool(elegidos))

            return await interaction.response.send_modal(
                TextoLibreModal(self.historia["titulo"], etiqueta, False, guardar_otro)
            )

        await self.avanzar(interaction, bool(elegidos))

    async def _abrir_resumen(self, interaction: discord.Interaction):
        async def guardar(inter: discord.Interaction, texto: str):
            if await self.cog.rechazar_texto(inter, texto, _MIN_PALABRAS_RESUMEN):
                return
            ok = await database.guardar_descripcion(
                self.cog.db, self.historia["id"], texto, _fuente_aporte(inter.user.id, self.historia)
            )
            if ok:
                self.historia["descripcion"] = texto
                self.cog.invalidar()
            await self.avanzar(inter, ok)

        await interaction.response.send_modal(TextoLibreModal(self.historia["titulo"], "Resumen", True, guardar))

    async def _saltar(self, interaction: discord.Interaction):
        await self.avanzar(interaction, False)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class ResenaModal(discord.ui.Modal):
    def __init__(self, cog: "Biblioteca", historia: dict[str, Any]):
        super().__init__(title=f"Reseña: {historia['titulo']}"[:45])
        self.cog, self.historia = cog, historia
        self.nota = discord.ui.TextInput(label="Puntuación (1 a 5)", max_length=1, placeholder="5")
        self.texto = discord.ui.TextInput(
            label="¿Qué te pareció?", style=discord.TextStyle.paragraph, min_length=60, max_length=1500,
            placeholder="Cuéntale al autor lo que más te gustó, sin spoilers importantes...",
        )
        self.add_item(self.nota)
        self.add_item(self.texto)

    async def on_submit(self, interaction: discord.Interaction):
        valor = str(self.nota.value).strip()
        if not valor.isdigit() or not 1 <= int(valor) <= 5:
            return await interaction.response.send_message("La puntuación tiene que ser un número del 1 al 5 🙄", ephemeral=True)
        if await self.cog.rechazar_texto(interaction, str(self.texto.value)):
            return
        await self.cog.publicar_resena(interaction, self.historia, int(valor), str(self.texto.value))


class PedirResumenView(discord.ui.View):
    """Botón para que el autor (o quien la haya leído) escriba el resumen pedido."""

    def __init__(self, cog: "Biblioteca", historia: dict[str, Any], solicitante_id: int):
        super().__init__(timeout=86400)
        self.cog = cog
        self.historia = historia
        self.solicitante_id = solicitante_id

    @discord.ui.button(label="Escribir resumen", emoji="✍️", style=discord.ButtonStyle.primary)
    async def escribir(self, interaction: discord.Interaction, button: discord.ui.Button):
        async def guardar(inter: discord.Interaction, texto: str):
            if await self.cog.rechazar_texto(inter, texto, _MIN_PALABRAS_RESUMEN):
                return
            fuente = _fuente_aporte(inter.user.id, self.historia)
            ok = await database.guardar_descripcion(self.cog.db, self.historia["id"], texto, fuente)
            if not ok:
                return await inter.response.send_message(
                    "Alguien se te adelantó y ya tengo un resumen de esa historia. ¡Gracias igual! 🎀", ephemeral=True
                )
            self.cog.invalidar()
            self.stop()
            await inter.response.edit_message(view=None)
            await inter.followup.send(
                f"📖 <@{self.solicitante_id}>, aquí tienes de qué trata **{md(self.historia['titulo'])}** "
                f"(gracias, {inter.user.mention}~ ya lo guardé en mi biblioteca):\n>>> {texto[:1700]}",
                allowed_mentions=discord.AllowedMentions(users=[discord.Object(self.solicitante_id)]),
            )

        await interaction.response.send_modal(TextoLibreModal(self.historia["titulo"], "Resumen", True, guardar))


# ─────────────────────────── Cog ───────────────────────────

class Biblioteca(commands.Cog):
    """Recomendaciones de historias y base de conocimiento de Ribby."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]
        self.pokemon: set[str] = set()
        self._cache: dict[bool, list[dict[str, Any]]] = {}  # Una caché por modo (real / pruebas)
        self._cache_t: dict[bool, float] = {}
        self._lock_sync = asyncio.Lock()
        self._recientes: dict[int, deque[int]] = defaultdict(lambda: deque(maxlen=12))
        # Canal → (instante, IDs) de las últimas historias mostradas, para poder hablar de ellas después
        self._ultimas_canal: dict[int, tuple[float, list[int]]] = {}
        try:
            self.model: Optional[ProviderManager] = ProviderManager(config)
        except Exception as e:  # noqa: BLE001
            log.warning(f"Biblioteca sin IA: {e}")
            self.model = None

    async def cog_unload(self):
        self.sincronizacion_diaria.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.sincronizacion_diaria.is_running():
            self.sincronizacion_diaria.start()

    # ── Catálogo ──

    async def catalogo(self, forzar: bool = False) -> list[dict[str, Any]]:
        modo = en_prueba()
        if forzar or modo not in self._cache or monotonic() - self._cache_t.get(modo, 0) > _CACHE_SEGUNDOS:
            self._cache[modo] = await database.listar_catalogo(self.db)
            self._cache_t[modo] = monotonic()
        return self._cache[modo]

    def invalidar(self, todo: bool = False) -> None:
        if todo:
            self._cache.clear()
        else:
            self._cache.pop(en_prueba(), None)

    # ── Sincronización con Wattpad ──

    @tasks.loop(hours=6)
    async def sincronizacion_diaria(self):
        try:
            resumen = await self.sincronizar()
            log.info(f"📚 Biblioteca sincronizada: {resumen}")
        except Exception as e:  # noqa: BLE001
            log.exception(f"Error sincronizando la biblioteca: {e}")

    async def sincronizar(self, listas_extra: tuple[str, ...] = ()) -> dict[str, int]:
        async with self._lock_sync:
            if not self.pokemon:
                self.pokemon = await wattpad.nombres_pokemon()

            stats = {"retos": await database.sincronizar_retos_biblioteca(self.db), "nuevas": 0, "actualizadas": 0}
            vistos: set[str] = set()
            capitulos_nuevos: list[tuple[int, int]] = []  # (historia_id, partes nuevas)

            async def guardar(datos: dict[str, Any], origen: Optional[str]) -> None:
                hid, nueva, antes = await database.guardar_historia_wattpad_detalle(self.db, datos, origen)
                stats["nuevas" if nueva else "actualizadas"] += 1
                ahora = datos.get("partes") or 0
                if not nueva and antes and ahora > antes:
                    capitulos_nuevos.append((hid, ahora - antes))

            for lista in list(config.WATTPAD_LISTAS) + list(listas_extra):
                for datos in await wattpad.historias_de_lista(lista):
                    await guardar(datos, "lista")
                    vistos.add(datos["wattpad_id"])

            # Historias añadidas a mano: refrescar lecturas/votos/partes una a una, sin prisa
            for wid in await database.ids_wattpad_guardados(self.db):
                if wid in vistos:
                    continue
                datos = await wattpad.obtener_historia(wid)
                if datos:
                    await guardar(datos, None)
                await asyncio.sleep(1)

            self.invalidar()
            if capitulos_nuevos:
                await self.avisar_capitulos(capitulos_nuevos)
            stats["capitulos"] = len(capitulos_nuevos)
            return stats

    async def avisar_capitulos(self, novedades: list[tuple[int, int]], canal: Any = None) -> None:
        """Avisa a quien sigue una historia (o la tiene de misión) de que hay capítulos nuevos."""
        if canal is None:
            valor = await database.config_obtener(self.db, "canal_ribby")
            canal = self.bot.get_channel(int(valor)) if valor and valor.isdigit() else None
        catalogo = {h["id"]: h for h in await self.catalogo()}
        for hid, cuantas in novedades:
            h = catalogo.get(hid)
            interesados = await database.interesados_en_historia(self.db, hid)
            if not h or not interesados:
                continue
            texto = (
                f"🔔 **¡{'Capítulo nuevo' if cuantas == 1 else f'{cuantas} capítulos nuevos'}!** "
                f"**{md(h['titulo'])}** de {md(h.get('autor_nombre') or 'su autor')} acaba de actualizarse "
                f"(ya va por {h.get('partes')} partes). 📖\n{h.get('url') or ''}"
            )
            try:
                if isinstance(canal, discord.TextChannel):
                    menciones = " ".join(f"<@{u}>" for u in sorted(interesados))
                    await canal.send(
                        f"{texto}\n{menciones}",
                        allowed_mentions=discord.AllowedMentions(users=[discord.Object(int(u)) for u in interesados]),
                    )
                else:  # Sin canal configurado: aviso por mensaje privado
                    for uid in interesados:
                        usuario = self.bot.get_user(int(uid))
                        if usuario:
                            with contextlib.suppress(discord.HTTPException):
                                await usuario.send(f"{texto}\n*(Lo sigues en la biblioteca de Ribby. `/biblioteca dejar_de_seguir` para no recibir más avisos.)*")
            except discord.HTTPException as e:
                log.warning(f"No se pudo avisar del capítulo nuevo de {h['titulo']}: {e}")

    # ── Tarjetas ──

    async def tarjetas(self, historias: list[dict[str, Any]]) -> list[discord.Embed]:
        urls = [h.get("url_pdf") for h in historias] + [h.get("portada_reto") for h in historias]
        vigentes = await refrescar_urls(self.bot, urls)
        return [self._tarjeta(h, vigentes) for h in historias]

    def _tarjeta(self, h: dict[str, Any], vigentes: dict[str, str]) -> discord.Embed:
        pdf = vigentes.get(h.get("url_pdf") or "", h.get("url_pdf"))
        enlace = h.get("url") or pdf
        autor = md(h.get("autor_nombre") or "Autor desconocido")
        if h.get("autor_discord"):
            autor += f" (<@{h['autor_discord']}>)"

        desc = (h.get("descripcion") or "").strip()
        if len(desc) > 380:
            desc = desc[:380].rsplit(" ", 1)[0] + "…"
        cuerpo = f"✍️ Por **{autor}**\n\n{md(desc) if desc else '*Todavía no tengo el resumen de esta historia.*'}"

        embed = discord.Embed(
            title=(h.get("titulo") or "Sin título")[:256],
            url=enlace or None,
            description=cuerpo[:4096],
            color=COLOR_MADURA if h.get("madura") else config.COLOR_PRINCIPAL,
        )
        tags = [t for t in (h.get("tags") or []) if t not in _TAGS_OCULTOS]
        if tags:
            embed.add_field(name="🏷️  Etiquetas", value=md(", ".join(tags[:20]))[:1024], inline=False)

        if h.get("fuente") == "wattpad" or h.get("wattpad_id"):
            estado = "✅ Terminada" if h.get("completada") else "✍️ En curso"
            embed.add_field(
                name="📊  En Wattpad",
                value=f"👁️ {_num(h.get('lecturas'))} lecturas · ⭐ {_num(h.get('votos'))} votos · "
                      f"📑 {_num(h.get('partes'))} partes · {estado}",
                inline=False,
            )
        if h.get("num_resenas"):
            estrellas = "⭐" * int(round(h["nota_media"] or 0))
            embed.add_field(
                name="🖋️  Reseñas de la comunidad",
                value=f"{estrellas} **{h['nota_media']}** / 5 · {h['num_resenas']} reseña(s) · `/biblioteca resenas`",
                inline=False,
            )
        if h.get("evento_nombre"):
            embed.add_field(name="🏆  Reto literario", value=h["evento_nombre"][:1024], inline=False)
        if not h.get("url"):
            embed.add_field(
                name="📄  Documento",
                value=f"[Leer la historia]({pdf})" if pdf else "*El autor aún no ha subido el documento.*",
                inline=False,
            )
        if h.get("madura"):
            embed.add_field(name="⚠️  Contenido maduro (+18)", value="Marcada como madura en Wattpad. Lee con criterio.", inline=False)

        portada = h.get("portada_url") or vigentes.get(h.get("portada_reto") or "", h.get("portada_reto"))
        if portada:
            embed.set_thumbnail(url=portada)
        embed.set_footer(text=f"Biblioteca de Ribby  •  {'Wattpad' if h.get('url') else 'Reto literario'}")
        return embed

    # ── Recomendación ──

    async def recomendar(self, consulta: str, usuario_id: int) -> tuple[str, list[dict[str, Any]]]:
        catalogo = await self.catalogo()
        if not catalogo:
            return "Mis estantes están vacíos ahora mismo... vuelve en un rato, estoy acomodando libros 📚", []

        cands = rec.candidatos(catalogo, consulta)
        recientes = list(self._recientes[usuario_id])
        ids: list[int] = []
        mensaje = ""

        if self.model and self.model.providers:
            try:
                respuesta = await self.model.generate(
                    rec.SYSTEM_RECOMENDADOR,
                    [{"role": "user", "content": rec.prompt_usuario(consulta, [h for _, h in cands], recientes)}],
                )
                ids, mensaje = rec.parsear_respuesta(respuesta, {h["id"] for _, h in cands})
            except Exception as e:  # noqa: BLE001
                log.warning(f"Recomendación sin IA (falló el proveedor): {e}")

        if not ids:  # Respaldo: solo búsqueda local
            con_puntos = [h for s, h in cands if s > 0]
            frescas = [h for h in con_puntos if h["id"] not in recientes]
            elegidas = (frescas or con_puntos or [h for _, h in cands])[:3]
            ids = [h["id"] for h in elegidas]
            if not mensaje:
                mensaje = (
                    "Mira lo que encontré en mis estantes~ 📚" if con_puntos
                    else "Hmm, no tengo nada exactamente así... pero estas podrían gustarte 🙄"
                )

        self._recientes[usuario_id].extend(ids)
        por_id = {h["id"]: h for h in catalogo}
        return mensaje, [por_id[i] for i in ids if i in por_id]

    # ── Textos basura y trolls ──

    async def rechazar_texto(
        self, interaction: discord.Interaction, texto: str, minimo_palabras: int = calidad.MIN_PALABRAS,
    ) -> bool:
        """
        Reseñas y resúmenes: si el texto es basura (repetido, sin palabras, solo
        símbolos...) u ofensivo, se rechaza con un mensaje privado y se devuelve
        True. Se le devuelve su texto para que no lo pierda si era de buena fe.
        """
        motivo = calidad.problema_texto(texto, minimo_palabras)
        if motivo is None and hugging_face.activo():
            toxicidad = await hugging_face.puntuar_toxicidad(texto[:1000])
            if toxicidad is not None and toxicidad >= config.UMBRAL_TOXICIDAD:
                motivo = "ofensivo"
        if motivo is None:
            return False
        log.info(f"🚫 Texto rechazado de {interaction.user.display_name} ({motivo})")
        copia = f"\n\n*Tu texto, por si quieres corregirlo:*\n```{texto[:900].replace('`', 'ʼ')}```" if motivo in ("corto", "ofensivo") else ""
        await interaction.response.send_message(calidad.MENSAJES[motivo] + copia, ephemeral=True)
        return True

    # ── Contexto para la charla (lo usa cogs/saludos.py) ──

    def recordar_mostradas(self, canal_id: int, historias: list[dict[str, Any]]) -> None:
        if historias:
            self._ultimas_canal[canal_id] = (monotonic(), [h["id"] for h in historias])

    def ultimas_mostradas(self, canal_id: int, max_segundos: float = _VIGENCIA_MOSTRADAS) -> list[int]:
        momento, ids = self._ultimas_canal.get(canal_id, (0.0, []))
        return ids if monotonic() - momento <= max_segundos else []

    async def contexto_charla(self, canal_id: int, texto: str) -> str:
        """
        Fichas de las historias de las que se está hablando: las que Ribby mostró
        hace poco en el canal y la que se nombre en el mensaje. Así, a "¿qué me
        cuentas de cada una?" responde con datos reales en lugar de negarlo.
        """
        catalogo = await self.catalogo()
        por_id = {h["id"]: h for h in catalogo}
        elegidas = [por_id[i] for i in self.ultimas_mostradas(canal_id) if i in por_id]
        nombrada = rec.buscar_por_titulo(catalogo, texto, umbral=0.75) if texto else None
        if nombrada and nombrada["id"] not in {h["id"] for h in elegidas}:
            elegidas.insert(0, nombrada)
        if not elegidas:
            return ""
        lineas = [_ficha_charla(h) for h in elegidas[:4]]
        return (
            "FICHAS DE LAS HISTORIAS DE LAS QUE SE ESTÁ HABLANDO (datos reales de tu biblioteca; si te preguntan "
            "por ellas, usa esto y no inventes nada que no esté aquí):\n" + "\n".join(lineas)
        )

    async def _ofrecer_ayuda(self, canal: discord.abc.Messageable, historias: list[dict[str, Any]]) -> None:
        """Si alguna historia recomendada tiene la ficha incompleta, pide ayuda para completarla."""
        for h in historias:
            preguntas = rec.preguntas_pendientes(h, self.pokemon)
            if preguntas:
                view = AyudaFichaView(self, dict(h), preguntas, f"Por cierto, de **{md(h['titulo'])}** sé muy poco... ¿me ayudas? 🎀")
                await view.preparar()
                view.message = await canal.send(view.contenido(), view=view, allowed_mentions=_SIN_PING)
                return

    # ── Menciones (las enruta Saludos) ──

    async def manejar_mencion(self, message: discord.Message, texto: str) -> bool:
        """Devuelve True si la mención era para la biblioteca y ya se respondió."""
        urls = wattpad.extraer_urls(message.content)
        if urls:
            await self._agregar_desde_chat(message, urls)
            return True
        if rec.es_peticion_resumen(texto):
            await self._responder_resumen(message, texto)
            return True
        if rec.es_peticion_recomendacion(texto):
            # El indicador "escribiendo..." solo si está activado (Discord limita mucho ese endpoint)
            escribiendo = message.channel.typing() if config.ENABLE_TYPING_INDICATOR else contextlib.nullcontext()
            async with escribiendo:
                mensaje, historias = await self.recomendar(rec.extraer_consulta(texto), message.author.id)
                embeds = await self.tarjetas(historias)
            await message.reply(mensaje, embeds=embeds, mention_author=False, allowed_mentions=_SIN_PING)
            self.recordar_mostradas(message.channel.id, historias)
            await self._ofrecer_ayuda(message.channel, historias)
            return True
        return False

    async def _agregar_desde_chat(self, message: discord.Message, urls: list[str]) -> None:
        añadidas, conocidas, fallos = [], [], []
        for url in urls[:3]:
            lista = wattpad.id_lista(url)
            if lista:
                if not es_admin_miembro(message.author):
                    await message.reply(
                        "Importar listas enteras es cosa del staff 😤 Pásame los links de las historias una a una, o pide a un admin `/biblioteca sincronizar`.",
                        mention_author=False,
                    )
                    continue
                stats = await self.sincronizar((lista,))
                await message.reply(f"📚 Lista importada: {stats['nuevas']} historias nuevas, {stats['actualizadas']} actualizadas.", mention_author=False)
                continue
            datos = await wattpad.historia_desde_url(url)
            if not datos:
                fallos.append(url)
                continue
            hid, nueva = await database.guardar_historia_wattpad(self.db, datos, str(message.author.id))
            (añadidas if nueva else conocidas).append(hid)

        if not (añadidas or conocidas):
            if fallos:
                await message.reply(
                    "No pude abrir ese enlace 😶 ¿Seguro que es una historia pública de Wattpad?", mention_author=False
                )
            return

        self.invalidar()
        historias = [h for h in await self.catalogo() if h["id"] in añadidas + conocidas]
        if añadidas:
            texto = f"📚 ¡Nueva historia para mi biblioteca! Gracias, {md(message.author.display_name)}~ La guardaré con cuidado."
        else:
            texto = "Esa ya estaba en mis estantes 😌 pero actualicé sus datos."
        await message.reply(texto, embeds=await self.tarjetas(historias), mention_author=False, allowed_mentions=_SIN_PING)
        await self._ofrecer_ayuda(message.channel, historias)

    async def _responder_resumen(self, message: discord.Message, texto: str) -> None:
        catalogo = await self.catalogo()
        historia = rec.buscar_por_titulo(catalogo, texto)
        if not historia:
            ultimas = self.ultimas_mostradas(message.channel.id)
            if len(ultimas) == 1:
                historia = next((h for h in catalogo if h["id"] == ultimas[0]), None)
        if not historia:
            await message.reply("¿De cuál historia? Dime el título y te cuento 📖", mention_author=False)
            return

        desc = (historia.get("descripcion") or "").strip()
        if desc:
            await message.reply(
                f"📖 **{md(historia['titulo'])}**, de {md(historia.get('autor_nombre') or 'autor desconocido')}:\n>>> {md(desc[:1800])}",
                mention_author=False, allowed_mentions=_SIN_PING,
            )
            return

        view = PedirResumenView(self, historia, message.author.id)
        autor = historia.get("autor_discord")
        if autor:
            await message.reply(
                f"No tengo el resumen de **{md(historia['titulo'])}** 😶 <@{autor}>, {message.author.mention} quiere saber "
                f"de qué trata tu historia. ¿Le cuentas? Usa el botón y me lo quedo para la próxima 🎀",
                view=view, mention_author=False,
                allowed_mentions=discord.AllowedMentions(users=[discord.Object(int(autor)), message.author]),
            )
        else:
            await message.reply(
                f"No tengo el resumen de **{md(historia['titulo'])}** y no sé quién la escribió aquí en Discord 😶 "
                "¿Alguien que la haya leído me ayuda con un resumen?",
                view=view, mention_author=False, allowed_mentions=_SIN_PING,
            )

    # ── Comandos ──

    grupo = app_commands.Group(
        name="biblioteca",
        description="La biblioteca de historias de Ribby",
        guild_ids=config.GUILD_IDS or None,
    )

    async def _resolver(self, valor: str) -> Optional[dict[str, Any]]:
        catalogo = await self.catalogo()
        if valor.isdigit():
            h = next((x for x in catalogo if x["id"] == int(valor)), None)
            if h:
                return h
        return rec.buscar_por_titulo(catalogo, valor, umbral=0.5)

    async def autocompletar_historia(self, interaction: discord.Interaction, actual: str) -> list[app_commands.Choice[str]]:
        catalogo = await self.catalogo()
        n = rec.normalizar(actual)
        if n:
            catalogo = sorted(
                catalogo,
                key=lambda h: (n not in rec.normalizar(h["titulo"]), -rec.puntuar(h, rec.palabras_clave(actual))),
            )
        return [app_commands.Choice(name=(h["titulo"] or "Sin título")[:100], value=str(h["id"])) for h in catalogo[:25]]

    @grupo.command(name="recomendar", description="Ribby te recomienda historias de su biblioteca")
    @app_commands.describe(peticion="Qué te apetece leer (ej. 'romance escolar con Lycanroc')")
    async def cmd_recomendar(self, interaction: discord.Interaction, peticion: Optional[app_commands.Range[str, 1, 300]] = None):
        await interaction.response.defer()
        mensaje, historias = await self.recomendar(peticion or "", interaction.user.id)
        await interaction.followup.send(mensaje, embeds=await self.tarjetas(historias), allowed_mentions=_SIN_PING)
        if interaction.channel:
            self.recordar_mostradas(interaction.channel.id, historias)
            await self._ofrecer_ayuda(interaction.channel, historias)  # type: ignore[arg-type]

    @grupo.command(name="agregar", description="Añade una historia de Wattpad a la biblioteca")
    @app_commands.describe(link="Enlace de la historia (o de un capítulo) en Wattpad")
    async def cmd_agregar(self, interaction: discord.Interaction, link: str):
        await interaction.response.defer()
        datos = await wattpad.historia_desde_url(link)
        if not datos:
            return await interaction.followup.send("No pude leer ese enlace 😶 ¿Es una historia pública de Wattpad?")
        hid, nueva = await database.guardar_historia_wattpad(self.db, datos, str(interaction.user.id))
        self.invalidar()
        historia = await database.obtener_historia_biblioteca(self.db, hid)
        if not historia:
            return await interaction.followup.send("Algo salió mal guardando la historia 😣 Inténtalo de nuevo.")
        texto = "📚 ¡Añadida a mi biblioteca! Gracias~" if nueva else "Esa ya la tenía 😌 pero actualicé sus datos."
        await interaction.followup.send(texto, embeds=await self.tarjetas([historia]), allowed_mentions=_SIN_PING)
        if interaction.channel:
            await self._ofrecer_ayuda(interaction.channel, [historia])  # type: ignore[arg-type]

    @grupo.command(name="ver", description="Muestra la ficha de una historia")
    @app_commands.describe(historia="Título de la historia")
    @app_commands.autocomplete(historia=autocompletar_historia)
    async def cmd_ver(self, interaction: discord.Interaction, historia: str):
        h = await self._resolver(historia)
        if not h:
            return await interaction.response.send_message("No encuentro esa historia en mis estantes 🤔", ephemeral=True)
        await interaction.response.defer()
        await interaction.followup.send(embeds=await self.tarjetas([h]), allowed_mentions=_SIN_PING)
        if interaction.channel:
            await self._ofrecer_ayuda(interaction.channel, [h])  # type: ignore[arg-type]

    @grupo.command(name="etiquetar", description="Añade etiquetas (géneros, Pokémon, temas) a una historia")
    @app_commands.describe(historia="Título de la historia", etiquetas="Separadas por comas: romance, lycanroc, escolar")
    @app_commands.autocomplete(historia=autocompletar_historia)
    async def cmd_etiquetar(self, interaction: discord.Interaction, historia: str, etiquetas: app_commands.Range[str, 1, 300]):
        h = await self._resolver(historia)
        if not h:
            return await interaction.response.send_message("No encuentro esa historia en mis estantes 🤔", ephemeral=True)
        nuevas = await database.agregar_etiquetas(
            self.db, h["id"], _separar(etiquetas), _fuente_aporte(interaction.user.id, h), str(interaction.user.id)
        )
        self.invalidar()
        await interaction.response.send_message(
            f"🏷️ Añadí {nuevas} etiqueta(s) nueva(s) a **{md(h['titulo'])}**. Gracias~" if nuevas
            else f"**{md(h['titulo'])}** ya tenía esas etiquetas 😌",
            ephemeral=True,
        )

    @grupo.command(name="resumir", description="Escribe o corrige el resumen de una historia")
    @app_commands.describe(historia="Título de la historia")
    @app_commands.autocomplete(historia=autocompletar_historia)
    async def cmd_resumir(self, interaction: discord.Interaction, historia: str):
        h = await self._resolver(historia)
        if not h:
            return await interaction.response.send_message("No encuentro esa historia en mis estantes 🤔", ephemeral=True)

        async def guardar(inter: discord.Interaction, texto: str):
            if await self.rechazar_texto(inter, texto, _MIN_PALABRAS_RESUMEN):
                return
            ok = await database.guardar_descripcion(self.db, h["id"], texto, _fuente_aporte(inter.user.id, h))
            self.invalidar()
            await inter.response.send_message(
                "📝 ¡Resumen guardado! 🎀" if ok
                else "Esa historia ya tiene resumen; solo su autor puede cambiarlo. Si eres tú, vincula tu cuenta con `/biblioteca vincular_wattpad`.",
                ephemeral=True,
            )

        await interaction.response.send_modal(TextoLibreModal(h["titulo"], "Resumen", True, guardar))

    @grupo.command(name="resenar", description="Escribe una reseña de una historia que hayas leído")
    @app_commands.describe(historia="Título de la historia")
    @app_commands.autocomplete(historia=autocompletar_historia)
    async def cmd_resenar(self, interaction: discord.Interaction, historia: str):
        h = await self._resolver(historia)
        if not h:
            return await interaction.response.send_message("No encuentro esa historia en mis estantes 🤔", ephemeral=True)
        if str(interaction.user.id) == str(h.get("autor_discord") or ""):
            return await interaction.response.send_message(
                "¿Reseñar tu propia historia? Buen intento. 😏", ephemeral=True
            )
        romance = self.bot.get_cog("Afinidad")
        castigo = await romance.castigo_activo(interaction.user.id) if romance is not None else None  # type: ignore[attr-defined]
        if castigo:
            return await interaction.response.send_message(
                f"Después de lo que hiciste, no. Hasta el {castigo['hasta_texto']} no escribes reseñas en mi biblioteca. 😤",
                ephemeral=True,
            )
        await interaction.response.send_modal(ResenaModal(self, h))

    @grupo.command(name="resenas", description="Lee las reseñas de una historia")
    @app_commands.describe(historia="Título de la historia")
    @app_commands.autocomplete(historia=autocompletar_historia)
    async def cmd_resenas(self, interaction: discord.Interaction, historia: str):
        h = await self._resolver(historia)
        if not h:
            return await interaction.response.send_message("No encuentro esa historia en mis estantes 🤔", ephemeral=True)
        resenas = await database.resenas_de_historia(self.db, h["id"], limite=6)
        if not resenas:
            return await interaction.response.send_message(
                f"**{md(h['titulo'])}** aún no tiene reseñas. ¿Serás la primera persona? `/biblioteca resenar` 🖋️",
                ephemeral=True,
            )
        embed = discord.Embed(
            title=f"🖋️  Reseñas de {h['titulo']}"[:256], url=h.get("url") or None, color=config.COLOR_PRINCIPAL,
        )
        for r in resenas:
            embed.add_field(
                name=f"{'⭐' * r['puntuacion']}  —  {r['usuario_nombre'] or 'Anónimo'}"[:256],
                value=md(r["texto"][:400]) + ("…" if len(r["texto"]) > 400 else ""),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @grupo.command(name="borrar_resena", description="Borra tu reseña de una historia (el staff puede borrar la de cualquiera)")
    @app_commands.describe(
        historia="Título de la historia",
        usuario="(Solo staff) De quién es la reseña. Si no lo indicas, se borra la tuya",
        castigar="(Solo staff) Además, castigar a esa persona (-50 corazones y Ribby enfadada 3 días)",
    )
    @app_commands.autocomplete(historia=autocompletar_historia)
    async def cmd_borrar_resena(
        self, interaction: discord.Interaction, historia: str, usuario: Optional[discord.User] = None,
        castigar: bool = False,
    ):
        ajena = usuario is not None and usuario.id != interaction.user.id
        if (ajena or castigar) and not es_admin(interaction):
            return await interaction.response.send_message(
                "⛔ Solo el staff puede borrar reseñas de otras personas o castigar.", ephemeral=True
            )
        h = await self._resolver(historia)
        if not h:
            return await interaction.response.send_message("No encuentro esa historia en mis estantes 🤔", ephemeral=True)
        objetivo = usuario or interaction.user
        borrada = await database.borrar_resena(self.db, h["id"], objetivo.id)
        if borrada is None:
            return await interaction.response.send_message(
                f"{'Esa persona' if ajena else 'Tú'} no {'tiene' if ajena else 'tienes'} reseña en **{md(h['titulo'])}** 🤔",
                ephemeral=True,
            )
        self.invalidar()
        log.info(f"🗑️ {interaction.user.display_name} borró la reseña de {objetivo} en «{h['titulo']}»")
        texto = f"🗑️ Reseña de **{md(objetivo.display_name)}** en **{md(h['titulo'])}** borrada."
        if castigar:
            romance = self.bot.get_cog("Afinidad")
            if romance is not None:
                await interaction.response.send_message(texto, ephemeral=True)
                return await romance.aplicar_castigo(  # type: ignore[attr-defined]
                    interaction, objetivo, motivo=f"escribió una reseña troll en «{h['titulo']}»",
                )
        await interaction.response.send_message(texto, ephemeral=True)

    async def publicar_resena(
        self, interaction: discord.Interaction, h: dict[str, Any], puntuacion: int, texto: str
    ) -> None:
        """Guarda la reseña, avisa al autor y, si era la misión de lectura, la completa."""
        nueva = await database.guardar_resena(
            self.db, h["id"], interaction.user.id, interaction.user.display_name, puntuacion, texto
        )
        self.invalidar()

        extra = ""
        romance = self.bot.get_cog("Afinidad")
        if romance is not None:
            extra = await romance.al_resenar(interaction.user, h)  # type: ignore[attr-defined]

        autor = h.get("autor_discord")
        aviso_autor = f"\n\n<@{autor}>, ¡tienes una reseña nueva! 🎀" if autor and nueva else ""
        contenido = (
            f"🖋️ **{md(interaction.user.display_name)}** {'reseñó' if nueva else 'actualizó su reseña de'} "
            f"**{md(h['titulo'])}**  {'⭐' * puntuacion}{'☆' * (5 - puntuacion)}\n>>> {texto[:1500]}{aviso_autor}"
        )
        await interaction.response.send_message(
            contenido,
            allowed_mentions=discord.AllowedMentions(users=[discord.Object(int(autor))]) if autor else _SIN_PING,
        )
        if extra:
            await interaction.followup.send(extra, ephemeral=True)

    @grupo.command(name="seguir", description="Recibe un aviso cuando una historia publique capítulos nuevos")
    @app_commands.describe(historia="Título de la historia")
    @app_commands.autocomplete(historia=autocompletar_historia)
    async def cmd_seguir(self, interaction: discord.Interaction, historia: str):
        h = await self._resolver(historia)
        if not h:
            return await interaction.response.send_message("No encuentro esa historia en mis estantes 🤔", ephemeral=True)
        if not h.get("wattpad_id"):
            return await interaction.response.send_message(
                "Esa historia no está en Wattpad, así que no puedo saber cuándo tiene capítulos nuevos 😶", ephemeral=True
            )
        nueva = await database.seguir_historia(self.db, interaction.user.id, h["id"])
        await interaction.response.send_message(
            f"🔔 Te avisaré cuando **{md(h['titulo'])}** tenga capítulos nuevos." if nueva
            else f"Ya seguías **{md(h['titulo'])}** 😌",
            ephemeral=True,
        )

    @grupo.command(name="dejar_de_seguir", description="Deja de recibir avisos de una historia")
    @app_commands.describe(historia="Título de la historia")
    @app_commands.autocomplete(historia=autocompletar_historia)
    async def cmd_dejar_de_seguir(self, interaction: discord.Interaction, historia: str):
        h = await self._resolver(historia)
        ok = bool(h) and await database.dejar_de_seguir(self.db, interaction.user.id, h["id"])  # type: ignore[index]
        await interaction.response.send_message(
            f"🔕 Ya no te avisaré de **{md(h['titulo'])}**." if ok else "No seguías esa historia 🤔",  # type: ignore[index]
            ephemeral=True,
        )

    @grupo.command(name="autor", description="Perfil de autor: historias, lecturas, votos y reseñas")
    @app_commands.describe(usuario="Autor a consultar (por defecto, tú)")
    async def cmd_autor(self, interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        objetivo = usuario or interaction.user
        historias = [h for h in await self.catalogo() if str(h.get("autor_discord") or "") == str(objetivo.id)]
        if not historias:
            yo = objetivo.id == interaction.user.id
            cuentas = await database.wattpad_de_discord(self.db, objetivo.id)
            if cuentas:
                # Tiene cuenta vinculada pero aún no hay historias suyas: se intenta traerlas ahora
                await interaction.response.defer()
                for cuenta in cuentas:
                    await self.importar_autor(cuenta)
                historias = [h for h in await self.catalogo() if str(h.get("autor_discord") or "") == str(objetivo.id)]
                if not historias:
                    return await interaction.followup.send(
                        f"Tengo vinculada la cuenta de Wattpad **{md(', '.join(cuentas))}**, pero no encontré historias "
                        "públicas en ella 🤔",
                        ephemeral=True,
                    )
            else:
                texto = ("No tengo historias tuyas en mis estantes 🤔 Vincula tu cuenta con `/biblioteca vincular_wattpad` "
                         "o regístrate en un reto." if yo else f"No conozco historias de {md(objetivo.display_name)} todavía 🤔")
                if en_prueba():
                    texto += "\n🧪 *Estás en modo de pruebas: la biblioteca de pruebas empieza vacía (`/prueba sembrar`).*"
                return await interaction.response.send_message(texto, ephemeral=True)
        if not interaction.response.is_done():
            await interaction.response.defer()
        ids = [h["id"] for h in historias]
        lecturas = sum(h.get("lecturas") or 0 for h in historias)
        votos = sum(h.get("votos") or 0 for h in historias)
        n_resenas = sum(h.get("num_resenas") or 0 for h in historias)
        nota = (
            sum((h.get("nota_media") or 0) * (h.get("num_resenas") or 0) for h in historias) / n_resenas
            if n_resenas else None
        )
        seguidores = await database.contar_seguidores(self.db, ids)
        wattpads = sorted({h["autor_wattpad"] for h in historias if h.get("autor_wattpad")})

        embed = discord.Embed(
            title=f"✍️  {objetivo.display_name}",
            description=(f"🔗 Wattpad: " + ", ".join(f"[{md(w)}](https://www.wattpad.com/user/{w})" for w in wattpads)
                         if wattpads else "*Sin cuenta de Wattpad vinculada*"),
            color=config.COLOR_PRINCIPAL,
        )
        embed.set_thumbnail(url=objetivo.display_avatar.url)
        embed.add_field(name="📚 Historias", value=str(len(historias)), inline=True)
        embed.add_field(name="👁️ Lecturas", value=_num(lecturas), inline=True)
        embed.add_field(name="⭐ Votos", value=_num(votos), inline=True)
        embed.add_field(
            name="🖋️ Reseñas", value=f"{n_resenas}" + (f" · {nota:.1f}/5" if nota else ""), inline=True
        )
        embed.add_field(name="🔔 Seguidores", value=str(seguidores), inline=True)

        lineas = []
        for h in sorted(historias, key=lambda x: -(x.get("lecturas") or 0))[:10]:
            datos = f"👁️ {_num(h.get('lecturas'))} · ⭐ {_num(h.get('votos'))}" if h.get("wattpad_id") else "🏆 Reto"
            if h.get("num_resenas"):
                datos += f" · 🖋️ {h['nota_media']}"
            titulo = f"[{md(h['titulo'][:60])}]({h['url']})" if h.get("url") else md(h["titulo"][:60])
            lineas.append(f"• {titulo} — {datos}")
        embed.add_field(name="Sus historias", value="\n".join(lineas)[:1024], inline=False)

        for r in await database.resenas_de_historias(self.db, ids, limite=3):
            embed.add_field(
                name=f"{'⭐' * r['puntuacion']} sobre {r['titulo'][:40]} — {r['usuario_nombre'] or 'Anónimo'}"[:256],
                value=r["texto"][:200] + ("…" if len(r["texto"]) > 200 else ""),
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    @grupo.command(name="vincular_wattpad", description="Vincula tu cuenta de Wattpad para que Ribby sepa qué historias son tuyas")
    @app_commands.describe(usuario="Tu usuario o el enlace a tu perfil de Wattpad")
    async def cmd_vincular(self, interaction: discord.Interaction, usuario: str):
        nombre = wattpad.usuario_de_url(usuario)
        if not nombre:
            return await interaction.response.send_message("Eso no parece un usuario de Wattpad 🤨", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await database.vincular_autor_wattpad(self.db, nombre, str(interaction.user.id))
        total, nuevas = await self.importar_autor(nombre, str(interaction.user.id))
        if total:
            detalle = (f"Encontré **{total}** historia(s) tuya(s) en Wattpad" +
                       (f" y añadí **{nuevas}** nueva(s) a mi biblioteca" if nuevas else ", ya las tenía todas") +
                       ". Mira tu perfil con `/biblioteca autor`. 📚")
        else:
            detalle = ("No encontré historias públicas en esa cuenta 🤔 Si el nombre está bien, publica alguna "
                       "o añádelas con `/biblioteca agregar`.")
        await interaction.followup.send(
            f"🔗 Listo: **{md(nombre)}** en Wattpad eres tú. Te avisaré cuando alguien quiera saber de tus historias.\n{detalle}",
            ephemeral=True,
        )

    async def importar_autor(self, username: str, agregada_por: Optional[str] = None) -> tuple[int, int]:
        """Añade a la biblioteca todas las historias públicas de un autor de Wattpad. Retorna (total, nuevas)."""
        historias = await wattpad.historias_de_usuario(username)
        nuevas = 0
        for datos in historias:
            _, nueva = await database.guardar_historia_wattpad(self.db, datos, agregada_por)
            nuevas += int(nueva)
        self.invalidar()
        return len(historias), nuevas

    @grupo.command(name="eliminar", description="(Staff) Quita una historia de la biblioteca")
    @app_commands.describe(historia="Título de la historia")
    @app_commands.autocomplete(historia=autocompletar_historia)
    async def cmd_eliminar(self, interaction: discord.Interaction, historia: str):
        if not es_admin(interaction):
            return await interaction.response.send_message("⛔ Solo el staff puede quitar historias.", ephemeral=True)
        h = await self._resolver(historia)
        if not h:
            return await interaction.response.send_message("No encuentro esa historia 🤔", ephemeral=True)
        if h.get("participante_id"):
            return await interaction.response.send_message(
                "Esa historia es de un reto literario; no la quito para no perder el registro del reto.", ephemeral=True
            )
        await database.eliminar_historia_biblioteca(self.db, h["id"])
        self.invalidar()
        await interaction.response.send_message(f"🗑️ Quité **{md(h['titulo'])}** de la biblioteca.", ephemeral=True)

    @grupo.command(name="sincronizar", description="(Staff) Actualiza la biblioteca desde Wattpad ahora")
    @app_commands.describe(lista="(Opcional) Enlace de otra lista de lectura de Wattpad para importar")
    async def cmd_sincronizar(self, interaction: discord.Interaction, lista: Optional[str] = None):
        if not es_admin(interaction):
            return await interaction.response.send_message("⛔ Solo el staff puede sincronizar.", ephemeral=True)
        extra = ()
        if lista:
            lid = wattpad.id_lista(lista)
            if not lid:
                return await interaction.response.send_message("Ese enlace no es una lista de lectura de Wattpad.", ephemeral=True)
            extra = (lid,)
        await interaction.response.defer(ephemeral=True)
        stats = await self.sincronizar(extra)
        total = len(await self.catalogo())
        await interaction.followup.send(
            f"📚 Sincronización terminada: {stats['nuevas']} nuevas, {stats['actualizadas']} actualizadas, "
            f"{stats['retos']} historias de retos añadidas, {stats.get('capitulos', 0)} con capítulos nuevos. "
            f"Total en la biblioteca: **{total}**.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Biblioteca(bot))
