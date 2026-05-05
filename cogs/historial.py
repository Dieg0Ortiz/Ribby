"""
cogs/historial.py — Consulta de eventos pasados y vista de participantes.

Comandos:
  /reto info      — Muestra el evento activo con sus participantes.
  /reto historial — Lista eventos cerrados. Al seleccionar uno, muestra detalles.
"""

import discord
from discord import app_commands
from discord.ext import commands

import config
import database


class HistorialSelect(discord.ui.Select):
    """Menú desplegable para elegir un evento del historial."""

    def __init__(self, eventos: list, db):
        self._db = db
        options = []
        for e in eventos[:25]:  # Discord limita a 25 opciones
            label = e["nombre"][:100]
            desc = f"Cerrado: {e['fecha_cierre'][:10] if e['fecha_cierre'] else 'N/A'}"
            options.append(
                discord.SelectOption(label=label, description=desc, value=str(e["id"]))
            )

        super().__init__(
            placeholder="Selecciona un evento para ver sus detalles...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        evento_id = int(self.values[0])
        evento = await database.obtener_evento_por_id(self._db, evento_id)
        participantes = await database.obtener_participantes(self._db, evento_id)
        resultados = await database.obtener_resultados_votacion(self._db, evento_id)

        embed = discord.Embed(
            title=f"📖 {evento['nombre']}",
            color=config.COLOR_INFO,
        )
        embed.add_field(
            name="📅 Fechas",
            value=(
                f"Creado: {evento['fecha_creacion'][:10]}\n"
                f"Cerrado: {evento['fecha_cierre'][:10] if evento['fecha_cierre'] else 'N/A'}"
            ),
            inline=True,
        )
        embed.add_field(
            name="👥 Participantes",
            value=str(len(participantes)),
            inline=True,
        )

        if resultados and resultados[0]["total_votos"] > 0:
            ganador = resultados[0]
            embed.add_field(
                name="🏆 Ganador",
                value=f"**{ganador['usuario_nombre']}** — _{ganador['titulo_historia'] or 'Sin título'}_ ({ganador['total_votos']} votos)",
                inline=False,
            )

        # Lista de participantes con sus historias
        if participantes:
            lineas = []
            for p in participantes:
                titulo = p["titulo_historia"] or "Sin título"
                linea = f"• **{p['usuario_nombre']}** — _{titulo}_"
                if p["url_pdf"]:
                    linea += f" [📄 PDF]({p['url_pdf']})"
                lineas.append(linea)

            # Dividir en campos si es muy largo
            texto = "\n".join(lineas)
            if len(texto) <= 1024:
                embed.add_field(name="📚 Historias", value=texto, inline=False)
            else:
                mitad = len(lineas) // 2
                embed.add_field(name="📚 Historias (1/2)", value="\n".join(lineas[:mitad]), inline=False)
                embed.add_field(name="📚 Historias (2/2)", value="\n".join(lineas[mitad:]), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


class HistorialView(discord.ui.View):
    def __init__(self, eventos: list, db):
        super().__init__(timeout=120)
        self.add_item(HistorialSelect(eventos, db))


class Historial(commands.Cog):
    """Cog para consulta de eventos activos y pasados."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    reto_group = app_commands.Group(
        name="reto",
        description="Información sobre los retos literarios",
        guild_ids=[config.GUILD_ID] if config.GUILD_ID else None,
    )

    # ── /reto info ──

    @reto_group.command(name="info", description="Muestra información del evento activo")
    async def info(self, interaction: discord.Interaction):
        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo:
            return await interaction.response.send_message(
                "ℹ️ No hay ningún evento activo en este momento.", ephemeral=True
            )

        participantes = await database.obtener_participantes(self.bot.db, activo["id"])

        estados = {
            "abierto": "🟢 Abierto — Recibiendo inscripciones",
            "narrando": "🎙️ Narrando — Sesión en vivo",
            "votando": "🗳️ Votando — Votación abierta",
            "cerrado": "🔒 Cerrado",
        }

        embed = discord.Embed(
            title=f"📖 {activo['nombre']}",
            description=estados.get(activo["estado"], activo["estado"]),
            color=config.COLOR_PRINCIPAL,
        )
        embed.add_field(name="🆔 ID", value=f"`{activo['id']}`", inline=True)
        embed.add_field(name="👥 Participantes", value=str(len(participantes)), inline=True)

        if participantes:
            embeds = [embed]
            for p in participantes[:10]:  # Limitar a 10 para no saturar
                p_embed = discord.Embed(
                    title=p["titulo_historia"] or "Sin título",
                    description=f"por **{p['usuario_nombre']}**",
                    color=config.COLOR_INFO,
                )
                if p["url_portada"]:
                    p_embed.set_image(url=p["url_portada"])
                if p["url_pdf"]:
                    p_embed.add_field(name="📄 Descargar PDF", value=f"[Clic aquí]({p['url_pdf']})")
                embeds.append(p_embed)

            await interaction.response.send_message(embeds=embeds[:10])
        else:
            embed.add_field(name="📚 Historias", value="Aún no hay participantes registrados.", inline=False)
            await interaction.response.send_message(embed=embed)

    # ── /reto historial ──

    @reto_group.command(name="historial", description="Muestra los eventos pasados")
    async def historial(self, interaction: discord.Interaction):
        eventos = await database.obtener_eventos_cerrados(self.bot.db)

        if not eventos:
            return await interaction.response.send_message(
                "ℹ️ No hay eventos pasados registrados.", ephemeral=True
            )

        embed = discord.Embed(
            title="📜 Historial de Retos Literarios",
            description=f"Se encontraron **{len(eventos)}** eventos pasados.\nSelecciona uno para ver sus detalles.",
            color=config.COLOR_INFO,
        )

        view = HistorialView(eventos, self.bot.db)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Historial(bot))
