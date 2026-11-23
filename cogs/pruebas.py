"""
cogs/pruebas.py — Modo de pruebas de Ribby (solo staff y su creador).

Con /prueba activar, TODO lo que hagas tú (comandos, botones, mensajes,
canal de voz) se guarda en el esquema "pruebas" de la base de datos, una copia
vacía con la misma estructura. El resto de usuarios sigue usando los datos
reales aunque estéis en el mismo canal.

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
import temporadas

log = logging.getLogger("bot-literario.pruebas")

COLOR_PRUEBAS = 0x22D3EE
_CLAVE = "modo_prueba:"

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
        """Recupera quién estaba en modo de pruebas antes de reiniciar el bot."""
        try:
            with comun.contexto_real():
                claves = await database.config_con_prefijo(self.db, _CLAVE)
            comun.usuarios_en_prueba.update(int(k[len(_CLAVE):]) for k in claves if k[len(_CLAVE):].isdigit())
        except Exception as e:  # noqa: BLE001
            log.warning(f"No se pudo cargar el modo de pruebas: {e}")

    # ── Utilidades ──

    def _limpiar_caches(self, usuario_id: int) -> None:
        """Al cambiar de modo, nada de lo que Ribby tenga en memoria debe mezclar datos de ambos mundos."""
        saludos = self.bot.get_cog("Saludos")
        if saludos is not None:
            getattr(saludos, "_estado_usuarios", {}).pop(usuario_id, None)
            getattr(saludos, "_ultimo_uso_ia", {}).pop(usuario_id, None)
        biblioteca = self.bot.get_cog("Biblioteca")
        if biblioteca is not None:
            biblioteca.invalidar(todo=True)  # type: ignore[attr-defined]

    async def _exigir_modo(self, interaction: discord.Interaction) -> bool:
        if not _puede_probar(interaction):
            await interaction.response.send_message("⛔ El modo de pruebas es solo para el staff.", ephemeral=True)
            return False
        if not comun.en_prueba(interaction.user.id):
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

    @grupo.command(name="activar", description="Entra en modo de pruebas: todo lo que hagas irá a la base de datos de pruebas")
    async def activar(self, interaction: discord.Interaction):
        if not _puede_probar(interaction):
            return await interaction.response.send_message("⛔ El modo de pruebas es solo para el staff.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await database.preparar_esquema_pruebas(self.db)
        with comun.contexto_real():
            await database.config_guardar(self.db, f"{_CLAVE}{interaction.user.id}", "1")
        comun.usuarios_en_prueba.add(interaction.user.id)
        self._limpiar_caches(interaction.user.id)
        creador = "\n• Como eres su creador, en pruebas Ribby te trata como a un usuario normal para que puedas probar el romance." \
            if comun.es_creador(interaction.user) else ""
        await interaction.followup.send(
            "🧪 **Modo de pruebas ACTIVADO.**\n"
            "• Todo lo que hagas (comandos, botones, hablar con Ribby, canal de voz) se guarda en la base de pruebas.\n"
            "• Los demás usuarios siguen usando los datos reales.\n"
            "• La biblioteca de pruebas empieza vacía: usa `/prueba sembrar` para copiar la real.\n"
            f"• Ribby marcará con 🧪 sus respuestas mientras estés en pruebas.{creador}\n\n"
            "Atajos: `/prueba nivel`, `/prueba diario`, `/prueba tiempo`, `/prueba evento`, `/prueba celebrar`, "
            "`/prueba iniciativa`, `/prueba capitulo_nuevo`, `/prueba reiniciar`.",
            ephemeral=True,
        )

    @grupo.command(name="desactivar", description="Sal del modo de pruebas y vuelve a los datos reales")
    async def desactivar(self, interaction: discord.Interaction):
        if not _puede_probar(interaction):
            return await interaction.response.send_message("⛔ El modo de pruebas es solo para el staff.", ephemeral=True)
        with comun.contexto_real():
            await database.config_borrar(self.db, f"{_CLAVE}{interaction.user.id}")
        comun.usuarios_en_prueba.discard(interaction.user.id)
        comun.eventos_forzados.pop(interaction.user.id, None)
        self._limpiar_caches(interaction.user.id)
        await interaction.response.send_message(
            "✅ **Modo de pruebas desactivado.** Vuelves a los datos reales. (Los datos de prueba se conservan "
            "hasta que uses `/prueba reiniciar`.)",
            ephemeral=True,
        )

    @grupo.command(name="estado", description="¿Estás en modo de pruebas?")
    async def estado(self, interaction: discord.Interaction):
        activo = comun.en_prueba(interaction.user.id)
        forzado = comun.eventos_forzados.get(interaction.user.id)
        quienes = ", ".join(f"<@{u}>" for u in sorted(comun.usuarios_en_prueba)) or "nadie"
        await interaction.response.send_message(
            f"🧪 Modo de pruebas: **{'ACTIVADO' if activo else 'desactivado'}**"
            + (f"\n🎉 Evento forzado: **{forzado}**" if forzado else "")
            + f"\n👥 En pruebas ahora mismo: {quienes}",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    @grupo.command(name="reiniciar", description="Borra TODOS los datos de prueba y empieza de cero")
    async def reiniciar(self, interaction: discord.Interaction):
        if not await self._exigir_modo(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await database.preparar_esquema_pruebas(self.db, reiniciar=True)
        self._limpiar_caches(interaction.user.id)
        await interaction.followup.send("🧹 Base de datos de pruebas vaciada y recreada.", ephemeral=True)

    @grupo.command(name="sembrar", description="Copia la biblioteca real (historias, etiquetas, autores) a la de pruebas")
    async def sembrar(self, interaction: discord.Interaction):
        if not await self._exigir_modo(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        total = await database.sembrar_biblioteca_pruebas(self.db)
        self._limpiar_caches(interaction.user.id)
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
                    f"En pruebas, Ribby ya tiene pareja ({pareja['nombre_display']}). Usa `/prueba reiniciar`.", ephemeral=True
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
                f"Nadie sigue **{h['titulo']}** en pruebas. Usa antes `/biblioteca seguir`.", ephemeral=True
            )
        await interaction.response.send_message(f"🧪 Simulando capítulo nuevo de **{h['titulo']}**...", ephemeral=True)
        await biblioteca.avisar_capitulos([(h["id"], 1)], canal=interaction.channel)  # type: ignore[union-attr]

    @capitulo_nuevo.autocomplete("historia")
    async def _autocompletar(self, interaction: discord.Interaction, actual: str) -> list[app_commands.Choice[str]]:
        biblioteca = self.bot.get_cog("Biblioteca")
        if biblioteca is None:
            return []
        return await biblioteca.autocompletar_historia(interaction, actual)  # type: ignore[union-attr]


async def setup(bot: commands.Bot):
    await bot.add_cog(Pruebas(bot))
