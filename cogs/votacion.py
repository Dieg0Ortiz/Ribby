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

import config
import database


class VotoSelect(discord.ui.Select):
    """Menú desplegable con las historias disponibles para votar."""

    def __init__(self, evento_id: int, participantes: list, db):
        self.evento_id = evento_id
        self._db = db

        options = []
        for p in participantes:
            titulo = p["titulo_historia"] or "Sin título"
            label = titulo[:100]
            desc = f"por {p['usuario_nombre']}"[:100]
            options.append(
                discord.SelectOption(
                    label=label,
                    description=desc,
                    value=str(p["id"]),
                )
            )

        super().__init__(
            placeholder="Selecciona la historia que quieres votar...",
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
        )

        if exito:
            embed = discord.Embed(
                title="✅ ¡Voto Registrado!",
                description="Tu voto ha sido guardado de forma anónima. ¡Gracias por participar!",
                color=config.COLOR_EXITO,
            )
        else:
            embed = discord.Embed(
                title="⚠️ Voto Duplicado",
                description="Ya habías registrado tu voto para este evento.",
                color=config.COLOR_ADVERTENCIA,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


class VotoView(discord.ui.View):
    """Vista que contiene el menú de votación."""

    def __init__(self, evento_id: int, participantes: list, db):
        super().__init__(timeout=300)
        self.add_item(VotoSelect(evento_id, participantes, db))


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
            return await interaction.response.send_message(
                "❌ La votación no está abierta en este momento.", ephemeral=True
            )

        user_id = str(interaction.user.id)
        evento_id = activo["id"]

        # Verificación 2 — Asistencia
        habilitado = await database.esta_habilitado(self.bot.db, evento_id, user_id)
        if not habilitado:
            return await interaction.response.send_message(
                "❌ No cumpliste el requisito mínimo de asistencia en el canal de voz (70%). "
                "No puedes votar en este evento.",
                ephemeral=True,
            )

        # Verificación 3 — Voto duplicado
        ya = await database.ya_voto(self.bot.db, evento_id, user_id)
        if ya:
            return await interaction.response.send_message(
                "⚠️ Ya registraste tu voto para este evento. No puedes votar de nuevo.",
                ephemeral=True,
            )

        # Obtener participantes (excluyendo al votante)
        participantes = await database.obtener_participantes(self.bot.db, evento_id)
        participantes = [p for p in participantes if p["usuario_discord_id"] != user_id]

        if not participantes:
            return await interaction.response.send_message(
                "⚠️ No hay historias disponibles para votar.", ephemeral=True
            )

        embed = discord.Embed(
            title="🗳️ Votación",
            description=(
                f"**{activo['nombre']}**\n\n"
                "Selecciona la historia que quieres votar en el menú de abajo.\n"
                "Tu voto es **anónimo** y **definitivo**."
            ),
            color=config.COLOR_PRINCIPAL,
        )

        view = VotoView(evento_id, participantes, self.bot.db)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Votacion(bot))
