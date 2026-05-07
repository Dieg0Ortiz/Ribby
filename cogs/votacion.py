"""
cogs/votacion.py — Sistema de votación anti-fraude con menú desplegable.

Comando:
  /votar — Muestra un menú desplegable para votar (solo si cumple requisitos).

Verificaciones (en orden):
  1. El evento debe estar en estado 'votando'.
  2. El usuario debe haber cumplido el 70% de asistencia.
  3. El usuario no debe haber votado ya.
  4. No se puede votar por uno mismo.
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

import config
import database


class VotoSelect(discord.ui.Select):
    """Menú desplegable con las historias disponibles para votar."""

    def __init__(self, evento_id: int, participantes: list, db, es_valido: bool):
        self.evento_id = evento_id
        self._db = db
        self._es_valido = es_valido

        options = []
        for p in participantes:
            titulo = p["titulo_historia"] or "Sin título"
            label = titulo[:100]
            desc = f"✍️ por {p['usuario_nombre']}"[:100]
            options.append(
                discord.SelectOption(
                    label=label,
                    description=desc,
                    value=str(p["id"]),
                    emoji="📖",
                )
            )

        super().__init__(
            placeholder="📚  Selecciona la historia que quieres votar...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        participante_id = int(self.values[0])
        exito = await database.registrar_voto(
            self._db,
            self.evento_id,
            str(interaction.user.id),
            participante_id,
            es_valido=self._es_valido,
        )

        if exito:
            embed = discord.Embed(
                title="✅  ¡Voto Registrado!",
                description=(
                    f"{config.SEPARADOR}\n\n"
                    "Tu voto ha sido guardado de forma **anónima**.\n"
                    "¡Gracias por participar en el reto!\n\n"
                    f"{config.SEPARADOR}"
                ),
                color=config.COLOR_EXITO,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
            embed.set_footer(text="COMARCALIT  •  Tu voto es privado y definitivo")
        else:
            embed = discord.Embed(
                title="⚠️  Voto Duplicado",
                description=(
                    f"{config.SEPARADOR}\n\n"
                    "Ya habías registrado tu voto para este evento.\n"
                    "Solo se permite **un voto por persona**.\n\n"
                    f"{config.SEPARADOR}"
                ),
                color=config.COLOR_ADVERTENCIA,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)

        await interaction.response.send_message(embed=embed, ephemeral=True)


class VotoView(discord.ui.View):
    """Vista que contiene el menú de votación."""

    def __init__(self, evento_id: int, participantes: list, db, es_valido: bool):
        super().__init__(timeout=300)
        self.add_item(VotoSelect(evento_id, participantes, db, es_valido))


class Votacion(commands.Cog):
    """Cog para el sistema de votación."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="votar", description="Vota por tu historia favorita del evento activo")
    @app_commands.guilds(config.GUILD_ID) if config.GUILD_ID else lambda f: f
    async def votar(self, interaction: discord.Interaction):
        activo = await database.obtener_evento_activo(self.bot.db)

        # Verificación 1 — Estado del evento
        if not activo or activo["estado"] != "votando":
            embed = discord.Embed(
                description="**⛔  Votación no disponible**\n\nLa votación no está abierta en este momento.",
                color=config.COLOR_ERROR,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        user_id = str(interaction.user.id)
        evento_id = activo["id"]

        # Verificación 2 — Voto duplicado
        ya = await database.ya_voto(self.bot.db, evento_id, user_id)
        if ya:
            embed = discord.Embed(
                description=(
                    "**⚠️  Ya votaste**\n\n"
                    "Ya registraste tu voto para este evento.\n"
                    "No puedes votar de nuevo."
                ),
                color=config.COLOR_ADVERTENCIA,
            )
            embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # Verificación silenciosa — ¿Está habilitado?
        es_valido = await database.esta_habilitado(self.bot.db, evento_id, user_id)

        # Obtener participantes (excluyendo al votante)
        participantes = await database.obtener_participantes(self.bot.db, evento_id)
        participantes = [p for p in participantes if p["usuario_discord_id"] != user_id]

        if not participantes:
            embed = discord.Embed(
                description="**⚠️  Sin candidatos**\n\nNo hay historias disponibles para votar.",
                color=config.COLOR_ADVERTENCIA,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # Construir lista de historias
        historias_lista = []
        for i, p in enumerate(participantes, 1):
            titulo = p["titulo_historia"] or "Sin título"
            historias_lista.append(f"`{i}.`  **{titulo}**  —  *{p['usuario_nombre']}*")

        embed = discord.Embed(
            title="🗳️  Votación",
            description=(
                f"{config.SEPARADOR}\n\n"
                f"📖  **{activo['nombre']}**\n\n"
                "Selecciona la historia que más te gustó\n"
                "en el menú desplegable de abajo.\n\n"
                f"{config.SEPARADOR_CORTO}\n\n"
                + "\n".join(historias_lista)
                + f"\n\n{config.SEPARADOR}"
            ),
            color=config.COLOR_VOTACION,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="⚠️  Importante",
            value="Tu voto es **anónimo** y **definitivo**. No podrás cambiarlo.",
            inline=False,
        )
        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="COMARCALIT  •  Retos Literarios  •  Elige sabiamente")

        view = VotoView(evento_id, participantes, self.bot.db, es_valido)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Votacion(bot))
