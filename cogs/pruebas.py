"""
cogs/pruebas.py — Modo de pruebas de Ribby (lo activan el staff y su creador).

/prueba activar pone a Ribby ENTERA en modo de pruebas: a partir de ese momento
todo lo que haga cualquier usuario (comandos, botones, mensajes, canal de voz)
y las tareas automáticas se guardan en el esquema "pruebas" de la base de
datos, una copia con la misma estructura. Los datos reales no se tocan hasta
que alguien use /prueba desactivar. En los servidores de pruebas
(config.GUILDS_PRUEBAS) todo usa siempre la base de pruebas.

En modo de pruebas también hay atajos para probar sin esperar días:
nivel de relación, reinicio de límites diarios, viajar en el tiempo, forzar
eventos de temporada, lanzar cumpleaños/aniversarios/iniciativa al momento y
simular capítulos nuevos de una historia.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands

import afinidad as af
import comun
import config
import database
from comun import md
import temporadas

log = logging.getLogger("bot-literario.pruebas")

COLOR_PRUEBAS = 0x22D3EE
_CLAVE = "modo_prueba:global"

# Corazones con los que se deja cada nivel (y coqueteos para poder superar "mejor amigo")
_NIVELES_PRUEBA = {
    "desconocido": 0.0, "amigo": 20.0, "mejor_amigo": 50.0, "algo_mas": 80.0, "enamorada": 100.0, "pareja": 100.0,
}


def _puede_probar(interaction: discord.Interaction) -> bool:
    return comun.es_admin(interaction) or comun.es_creador(interaction.user)


class Pruebas(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    async def cog_load(self):
        """Si Ribby se reinició con el modo de pruebas activado, sigue activado."""
        try:
            with comun.contexto_real():
                activo = await database.config_obtener(self.db, _CLAVE)
            comun.activar_modo_global(bool(activo))
            if activo:
                log.warning("🧪 Ribby arranca en MODO DE PRUEBAS (los datos reales no se tocan)")
        except Exception as e:  # noqa: BLE001
            log.warning(f"No se pudo cargar el modo de pruebas: {e}")

    # ── Utilidades ──

    def _limpiar_caches(self) -> None:
        """Al cambiar de modo, nada de lo que Ribby tenga en memoria debe mezclar datos de ambos mundos."""
        saludos = self.bot.get_cog("Saludos")
        if saludos is not None:
            getattr(saludos, "_estado_usuarios", {}).clear()
            getattr(saludos, "_ultimo_uso_ia", {}).clear()
            getattr(saludos, "_cache_config", {}).clear()
        biblioteca = self.bot.get_cog("Biblioteca")
        if biblioteca is not None:
            biblioteca.invalidar(todo=True)  # type: ignore[attr-defined]
        romance = self.bot.get_cog("Afinidad")
        if romance is not None:
            romance.invalidar_caches()  # type: ignore[attr-defined]

    async def _exigir_modo(self, interaction: discord.Interaction) -> bool:
        if not _puede_probar(interaction):
            await interaction.response.send_message("⛔ El modo de pruebas es solo para el staff.", ephemeral=True)
            return False
        if not comun.en_prueba():
            await interaction.response.send_message(
                "🧪 Este atajo solo funciona en modo de pruebas (para no tocar datos reales). Usa `/prueba activar`.",
                ephemeral=True,
            )
            return False
        return True

    def _romance(self):
        return self.bot.get_cog("Afinidad")

    # ── Comandos ──

    grupo = app_commands.Group(
        name="prueba", description="🧪 Modo de pruebas de Ribby (staff)", guild_ids=config.GUILD_IDS or None,
    )

    @grupo.command(name="activar", description="Pone a Ribby en modo de pruebas para TODOS hasta que se desactive")
    async def activar(self, interaction: discord.Interaction):
        if not _puede_probar(interaction):
            return await interaction.response.send_message("⛔ El modo de pruebas es solo para el staff.", ephemeral=True)
        if comun.modo_global():
            return await interaction.response.send_message(
                "🧪 El modo de pruebas ya estaba activado. Para salir: `/prueba desactivar`.", ephemeral=True
            )
        await interaction.response.defer()
        await database.preparar_esquema_pruebas(self.db)
        with comun.contexto_real():
            await database.config_guardar(self.db, _CLAVE, str(interaction.user.id))
        comun.activar_modo_global(True)
        self._limpiar_caches()
        embed = discord.Embed(
            title="🧪  Modo de pruebas ACTIVADO",
            description=(
                f"{interaction.user.mention} ha puesto a Ribby en modo de pruebas.\n\n"
                "**Desde ahora, todo lo que hagáis con Ribby (cualquier persona) es de prueba:** corazones, retos, "
                "votos, reseñas... se guardan aparte y **no cuentan de verdad**. Ribby marca sus respuestas con 🧪.\n\n"
                "Para volver a la normalidad: **`/prueba desactivar`**."
            ),
            color=COLOR_PRUEBAS,
        )
        if interaction.guild_id in config.GUILDS_PRUEBAS:
            embed.add_field(
                name="⚠️ Ojo",
                value="Lo has activado desde el servidor de pruebas, pero el modo global afecta **también a La Comarca**. "
                      "Aquí no hacía falta: este servidor ya usa siempre la base de pruebas.",
                inline=False,
            )
        embed.add_field(
            name="Para el staff",
            value="La biblioteca de pruebas empieza vacía: `/prueba sembrar`.\n"
                  "Atajos: `/prueba nivel` · `diario` · `tiempo` · `evento` · `celebrar` · `iniciativa` · "
                  "`capitulo_nuevo` · `reiniciar` · `estado`",
            inline=False,
        )
        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @grupo.command(name="desactivar", description="Saca a Ribby del modo de pruebas: todo vuelve a los datos reales")
    async def desactivar(self, interaction: discord.Interaction):
        if not _puede_probar(interaction):
            return await interaction.response.send_message("⛔ El modo de pruebas es solo para el staff.", ephemeral=True)
        if not comun.modo_global():
            texto = "El modo de pruebas no estaba activado."
            if interaction.guild_id in config.GUILDS_PRUEBAS:
                texto += " (Este es un servidor de pruebas: aquí todo usa siempre la base de pruebas.)"
            return await interaction.response.send_message(texto, ephemeral=True)
        with comun.contexto_real():
            await database.config_borrar(self.db, _CLAVE)
        comun.activar_modo_global(False)
        comun.eventos_forzados.clear()
        self._limpiar_caches()
        descripcion = (
            "Ribby vuelve a la normalidad: todo lo que hagáis desde ahora **cuenta de verdad**.\n"
            "*(Los datos de prueba se conservan para la próxima vez, o se borran con `/prueba reiniciar`.)*"
        )
        if interaction.guild_id in config.GUILDS_PRUEBAS:
            # Si no, parece que el modo no se desactivó: aquí Ribby sigue marcando todo con 🧪
            descripcion += (
                "\n\n🧪 **Ojo:** este es el **servidor de pruebas**, así que *aquí* Ribby sigue usando siempre la "
                "base de pruebas (y marcando sus respuestas con 🧪). Lo que vuelve a la normalidad es La Comarca."
            )
        await interaction.response.send_message(embed=discord.Embed(
            title="✅  Modo de pruebas DESACTIVADO", description=descripcion, color=config.COLOR_EXITO,
        ))

    @grupo.command(name="estado", description="¿Está Ribby en modo de pruebas?")
    async def estado(self, interaction: discord.Interaction):
        en_servidor_pruebas = interaction.guild_id in config.GUILDS_PRUEBAS
        with comun.contexto_real():
            quien = await database.config_obtener(self.db, _CLAVE)
        if comun.modo_global():
            texto = "🧪 Modo de pruebas **ACTIVADO para todos**" + (f" (lo activó <@{quien}>)" if quien else "")
            texto += ".\nPara salir: `/prueba desactivar`."
        elif en_servidor_pruebas:
            texto = ("🧪 Este es un **servidor de pruebas**: aquí todo usa siempre la base de pruebas.\n"
                     "En La Comarca, Ribby funciona con los datos reales.")
        else:
            texto = "✅ Modo de pruebas **desactivado**: Ribby usa los datos reales."
        saludos = self.bot.get_cog("Saludos")
        if saludos is not None:
            otras = getattr(saludos, "otras_instancias", [])
            texto += f"\n🖥️ Esta copia de Ribby: `{getattr(saludos, 'instancia', '?')}`"
            if otras:
                texto += (
                    f"\n⚠️ **Hay {len(otras)} copia(s) más conectadas:** " + ", ".join(f"`{o}`" for o in otras)
                    + "\nApágalas: si no, pueden salir respuestas duplicadas (una de ellas con frases predeterminadas)."
                )
        forzado = comun.eventos_forzados.get(interaction.user.id)
        if forzado and comun.en_prueba():
            texto += f"\n🎉 Evento forzado para ti: **{forzado}**"
        await interaction.response.send_message(texto, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @grupo.command(name="reiniciar", description="Borra TODOS los datos de prueba y empieza de cero")
    async def reiniciar(self, interaction: discord.Interaction):
        if not await self._exigir_modo(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await database.preparar_esquema_pruebas(self.db, reiniciar=True)
        self._limpiar_caches()
        await interaction.followup.send("🧹 Base de datos de pruebas vaciada y recreada.", ephemeral=True)

    @grupo.command(name="sembrar", description="Copia la biblioteca real (historias, etiquetas, autores) a la de pruebas")
    async def sembrar(self, interaction: discord.Interaction):
        if not await self._exigir_modo(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        total = await database.sembrar_biblioteca_pruebas(self.db)
        self._limpiar_caches()
        await interaction.followup.send(
            f"🌱 Biblioteca de pruebas lista con **{total}** historias de Wattpad (las de retos no se copian).",
            ephemeral=True,
        )

    @grupo.command(name="nivel", description="Pon tu relación con Ribby en un nivel concreto")
    @app_commands.describe(nivel="Nivel al que saltar")
    @app_commands.choices(nivel=[app_commands.Choice(name=af.NIVELES[n][0] + (" (secreto)" if n == "enamorada" else ""), value=n)
                                 for n in _NIVELES_PRUEBA])
    async def nivel(self, interaction: discord.Interaction, nivel: app_commands.Choice[str]):
        if not await self._exigir_modo(interaction):
            return
        romance = self._romance()
        estado = await romance.cargar(interaction.user.id)  # type: ignore[union-attr]
        estado.update(corazones=_NIVELES_PRUEBA[nivel.value], coqueteos=10, es_pareja=False,
                      fecha_inicio_pareja=None, fecha_maximo=None)
        if nivel.value == "enamorada":
            estado["fecha_maximo"] = af.ahora().isoformat()
        if nivel.value == "pareja":
            pareja = await database.pareja_actual(self.db)
            if pareja and pareja["usuario_discord_id"] != str(interaction.user.id):
                return await interaction.response.send_message(
                    f"En pruebas, Ribby ya tiene pareja ({md(pareja['nombre_display'])}). Usa `/prueba reiniciar`.", ephemeral=True
                )
            estado.update(es_pareja=True, fecha_inicio_pareja=af.ahora().isoformat())
        await romance.guardar(interaction.user, estado)  # type: ignore[union-attr]
        await interaction.response.send_message(
            f"💗 Ahora Ribby te ve como **{af.NIVELES[af.nivel(estado)][0]}** ({estado['corazones']:.0f} corazones).",
            ephemeral=True,
        )

    @grupo.command(name="diario", description="Reinicia tus límites diarios (regalo, cita, quiz, corazones, misión...)")
    async def diario(self, interaction: discord.Interaction):
        if not await self._exigir_modo(interaction):
            return
        uid = interaction.user.id
        romance = self._romance()
        estado = await romance.cargar(uid)  # type: ignore[union-attr]
        estado.update(corazones_hoy=0.0, dia_corazones=None, ultimo_regalo=None, ultima_cita=None, ultima_declaracion=None)
        await romance.guardar(interaction.user, estado)  # type: ignore[union-attr]
        for patron in (f"quiz:{uid}", f"mision_cambio:{uid}", f"evento:%:{uid}", f"iniciativa:{uid}"):
            await database.config_borrar_patron(self.db, patron)
        await interaction.response.send_message(
            "🔄 Límites diarios reiniciados: puedes volver a regalar, tener cita, hacer el quiz, cambiar de misión, "
            "declararte y ganar corazones hablando.",
            ephemeral=True,
        )

    @grupo.command(name="tiempo", description="Viaja al futuro: hace como si hubieran pasado N días desde tu última charla")
    @app_commands.describe(dias="Días que avanzan (ej. 8 para probar que el interés se enfría)")
    async def tiempo(self, interaction: discord.Interaction, dias: app_commands.Range[int, 1, 60]):
        if not await self._exigir_modo(interaction):
            return
        romance = self._romance()
        estado = await database.obtener_afinidad(self.db, interaction.user.id) or af.nuevo_estado()
        for campo in ("ultima_interaccion", "fecha_maximo", "fecha_inicio_pareja", "ultima_declaracion"):
            if estado.get(campo):
                estado[campo] = (datetime.fromisoformat(estado[campo]) - timedelta(days=dias)).isoformat()
        await database.retroceder_misiones(self.db, interaction.user.id, dias)
        ocurrido = af.aplicar_paso_del_tiempo(estado)
        await romance.guardar(interaction.user, estado)  # type: ignore[union-attr]
        await interaction.response.send_message(
            f"⏩ Han pasado {dias} día(s). Ahora Ribby te ve como **{af.NIVELES[af.nivel(estado)][0]}** "
            f"({estado['corazones']:.0f} corazones)."
            + (f"\nEventos: {', '.join(ocurrido)}" if ocurrido else "")
            + "\nTu misión de lectura activa también \"envejeció\", así que ya puedes completarla.",
            ephemeral=True,
        )

    @grupo.command(name="evento", description="Fuerza un evento de temporada (solo para ti, en pruebas)")
    @app_commands.choices(evento=[app_commands.Choice(name=e["nombre"], value=e["id"]) for e in temporadas.EVENTOS]
                          + [app_commands.Choice(name="Ninguno (fecha real)", value="ninguno")])
    async def evento(self, interaction: discord.Interaction, evento: app_commands.Choice[str]):
        if not await self._exigir_modo(interaction):
            return
        if evento.value == "ninguno":
            comun.eventos_forzados.pop(interaction.user.id, None)
            texto = "📅 Vuelves al calendario real."
        else:
            comun.eventos_forzados[interaction.user.id] = evento.value
            texto = f"🎉 Para ti ahora es **{evento.name}**. Prueba `/ribby evento`, `/ribby cita` o habla con Ribby."
        await interaction.response.send_message(texto, ephemeral=True)

    @grupo.command(name="celebrar", description="Lanza ahora mismo una celebración de Ribby en este canal")
    @app_commands.choices(tipo=[
        app_commands.Choice(name="🎂 Mi cumpleaños", value="cumple"),
        app_commands.Choice(name="💞 Aniversario de pareja", value="aniversario"),
        app_commands.Choice(name="🎉 Anuncio del evento de temporada", value="evento"),
    ])
    async def celebrar(self, interaction: discord.Interaction, tipo: app_commands.Choice[str]):
        if not await self._exigir_modo(interaction):
            return
        romance = self._romance()
        await interaction.response.defer()
        estado = await romance.cargar(interaction.user.id)  # type: ignore[union-attr]
        estado["usuario_discord_id"] = str(interaction.user.id)
        nombre = interaction.user.display_name

        if tipo.value == "cumple":
            texto = await romance._generar(  # type: ignore[union-attr]
                estado, nombre, f"Hoy es el cumpleaños de {nombre}. Felicítale con cariño acorde a vuestra relación.",
            ) or "¡Feliz cumpleaños! 🎂 Te guardé el mejor sillón de la biblioteca."
            await interaction.followup.send(f"🧪🎂 {interaction.user.mention} {texto}")
            await romance.aplicar_actividad(interaction.user, None, 3.0, "Ribby le felicitó por su cumpleaños (prueba)")  # type: ignore[union-attr]
        elif tipo.value == "aniversario":
            if not estado.get("es_pareja"):
                return await interaction.followup.send("Primero sé su pareja: `/prueba nivel nivel:Pareja`.", ephemeral=True)
            texto = await romance._generar(  # type: ignore[union-attr]
                estado, nombre, f"Hoy se cumple 1 mes desde que tú y {nombre} sois pareja. Dedícale unas palabras de aniversario.",
            ) or "...¿Sabes qué día es hoy? Claro que lo sabes. 💞"
            await interaction.followup.send(f"🧪💞 **1 mes juntos** — {interaction.user.mention} {texto}")
        else:
            e = next((x for x in temporadas.EVENTOS if x["id"] == comun.eventos_forzados.get(interaction.user.id)), None) \
                or temporadas.evento_actual(datetime.now(af.ZONA).date()) or temporadas.EVENTOS[0]
            await interaction.followup.send(embed=discord.Embed(
                title=f"🧪 {e['nombre']} llega a la biblioteca",
                description=f"*{e['anuncio']}*\n\nUsa `/ribby evento` para un regalo y una cita especiales. 🎀",
                color=COLOR_PRUEBAS,
            ))

    @grupo.command(name="iniciativa", description="Ribby te escribe ahora mismo por su cuenta (sin esperar ni límites)")
    async def iniciativa(self, interaction: discord.Interaction):
        if not await self._exigir_modo(interaction):
            return
        romance = self._romance()
        await interaction.response.defer()
        estado = await romance.cargar(interaction.user.id)  # type: ignore[union-attr]
        estado["usuario_discord_id"] = str(interaction.user.id)
        texto = await romance._generar(  # type: ignore[union-attr]
            estado, interaction.user.display_name,
            f"Hace 3 días que no hablas con {interaction.user.display_name} y decides escribirle tú primero, por "
            "iniciativa propia. Salúdale de forma natural: menciona algo que recuerdes de esta persona, pregúntale qué "
            "tal o recomiéndale leer algo. Sin reproches.",
        ) or "Hm. Estaba ordenando estanterías y me acordé de ti. ...Solo eso. 📚"
        await interaction.followup.send(f"🧪💌 {interaction.user.mention} {texto}")

    @grupo.command(name="capitulo_nuevo", description="Simula que una historia publicó un capítulo nuevo (aviso a seguidores)")
    @app_commands.describe(historia="Historia (síguela antes con /biblioteca seguir para recibir el aviso)")
    async def capitulo_nuevo(self, interaction: discord.Interaction, historia: str):
        if not await self._exigir_modo(interaction):
            return
        biblioteca = self.bot.get_cog("Biblioteca")
        h = await biblioteca._resolver(historia)  # type: ignore[union-attr]
        if not h:
            return await interaction.response.send_message("No encuentro esa historia en la biblioteca de pruebas.", ephemeral=True)
        interesados = await database.interesados_en_historia(self.db, h["id"])
        if not interesados:
            return await interaction.response.send_message(
                f"Nadie sigue **{md(h['titulo'])}** en pruebas. Usa antes `/biblioteca seguir`.", ephemeral=True
            )
        await interaction.response.send_message(f"🧪 Simulando capítulo nuevo de **{md(h['titulo'])}**...", ephemeral=True)
        await biblioteca.avisar_capitulos([(h["id"], 1)], canal=interaction.channel)  # type: ignore[union-attr]

    @capitulo_nuevo.autocomplete("historia")
    async def _autocompletar(self, interaction: discord.Interaction, actual: str) -> list[app_commands.Choice[str]]:
        biblioteca = self.bot.get_cog("Biblioteca")
        if biblioteca is None:
            return []
        return await biblioteca.autocompletar_historia(interaction, actual)  # type: ignore[union-attr]


async def setup(bot: commands.Bot):
    await bot.add_cog(Pruebas(bot))
