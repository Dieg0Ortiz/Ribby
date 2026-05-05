"""
cogs/eventos.py — Gestión del ciclo de vida de eventos literarios.

Comandos de administrador:
  /evento crear [nombre]
  /evento configurar [canal_voz] [canal_envio]
  /evento iniciar_narracion
  /evento iniciar_votacion
  /evento cerrar
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

import config
import database


def _es_admin(interaction: discord.Interaction) -> bool:
    """Verifica si el usuario tiene el rol de administrador literario."""
    return any(
        role.name == config.ADMIN_ROLE_NAME for role in interaction.user.roles
    )


class Eventos(commands.Cog):
    """Cog para la gestión de eventos literarios."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Grupo de comandos /evento ──

    evento_group = app_commands.Group(
        name="evento",
        description="Gestión de eventos literarios (solo administradores)",
        guild_ids=[config.GUILD_ID] if config.GUILD_ID else None,
    )

    # ── /evento crear ──

    @evento_group.command(name="crear", description="Crea un nuevo evento literario")
    @app_commands.describe(nombre="Nombre del evento (ej. 'Misterios — Reto #3')")
    async def crear(self, interaction: discord.Interaction, nombre: str):
        if not _es_admin(interaction):
            return await interaction.response.send_message(
                "❌ No tienes permisos para usar este comando.", ephemeral=True
            )

        # Verificar que no haya un evento activo
        activo = await database.obtener_evento_activo(self.bot.db)
        if activo:
            return await interaction.response.send_message(
                f"⚠️ Ya existe un evento activo: **{activo['nombre']}** (ID: `{activo['id']}`). "
                f"Ciérralo primero con `/evento cerrar`.",
                ephemeral=True,
            )

        evento_id = await database.crear_evento(self.bot.db, nombre)

        embed = discord.Embed(
            title="📖 Nuevo Evento Literario",
            description=f"**{nombre}**",
            color=config.COLOR_EXITO,
        )
        embed.add_field(name="ID del Evento", value=f"`{evento_id}`", inline=True)
        embed.add_field(name="Estado", value="🟢 Abierto", inline=True)
        embed.set_footer(text="Usa /evento configurar para asociar los canales")

        await interaction.response.send_message(embed=embed)

    # ── /evento configurar ──

    @evento_group.command(
        name="configurar",
        description="Asocia canales de voz y texto al evento activo",
    )
    @app_commands.describe(
        canal_voz="Canal de voz donde se narrará",
        canal_envio="Canal de texto donde los autores suben sus historias",
        canal_respaldo="Canal privado para respaldo de archivos (opcional)",
    )
    async def configurar(
        self,
        interaction: discord.Interaction,
        canal_voz: discord.VoiceChannel,
        canal_envio: discord.TextChannel,
        canal_respaldo: discord.TextChannel = None,
    ):
        if not _es_admin(interaction):
            return await interaction.response.send_message(
                "❌ No tienes permisos para usar este comando.", ephemeral=True
            )

        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo:
            return await interaction.response.send_message(
                "⚠️ No hay ningún evento activo. Crea uno con `/evento crear`.",
                ephemeral=True,
            )

        respaldo_id = canal_respaldo.id if canal_respaldo else None
        await database.configurar_evento(
            self.bot.db, activo["id"], canal_voz.id, canal_envio.id, respaldo_id
        )

        embed = discord.Embed(
            title="⚙️ Evento Configurado",
            description=f"**{activo['nombre']}** (ID: `{activo['id']}`)",
            color=config.COLOR_INFO,
        )
        embed.add_field(name="🔊 Canal de voz", value=canal_voz.mention, inline=True)
        embed.add_field(name="📝 Canal de envío", value=canal_envio.mention, inline=True)
        if canal_respaldo:
            embed.add_field(name="🔒 Canal de respaldo", value=canal_respaldo.mention, inline=True)

        await interaction.response.send_message(embed=embed)

    # ── /evento iniciar_narracion ──

    @evento_group.command(
        name="iniciar_narracion",
        description="Inicia la fase de narración y el registro de asistencia",
    )
    async def iniciar_narracion(self, interaction: discord.Interaction):
        if not _es_admin(interaction):
            return await interaction.response.send_message(
                "❌ No tienes permisos para usar este comando.", ephemeral=True
            )

        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo:
            return await interaction.response.send_message(
                "⚠️ No hay ningún evento activo.", ephemeral=True
            )

        if activo["estado"] != "abierto":
            return await interaction.response.send_message(
                f"⚠️ El evento está en estado `{activo['estado']}`. "
                f"Solo se puede iniciar la narración desde el estado `abierto`.",
                ephemeral=True,
            )

        if not activo["canal_voz_id"]:
            return await interaction.response.send_message(
                "⚠️ Primero configura el canal de voz con `/evento configurar`.",
                ephemeral=True,
            )

        await database.cambiar_estado_evento(self.bot.db, activo["id"], "narrando")

        # Registrar automáticamente a los usuarios que ya están en el canal de voz
        canal_voz = self.bot.get_channel(activo["canal_voz_id"])
        if canal_voz:
            for member in canal_voz.members:
                if not member.bot:
                    await database.registrar_entrada_voz(
                        self.bot.db, activo["id"], str(member.id)
                    )

        embed = discord.Embed(
            title="🎙️ ¡Narración Iniciada!",
            description=(
                f"**{activo['nombre']}**\n\n"
                f"📡 El registro de asistencia está activo.\n"
                f"🕐 Se está contando el tiempo de permanencia en el canal de voz."
            ),
            color=config.COLOR_PRINCIPAL,
        )
        embed.set_footer(text="Usa /evento iniciar_votacion cuando termine la narración")

        await interaction.response.send_message(embed=embed)

    # ── /evento iniciar_votacion ──

    @evento_group.command(
        name="iniciar_votacion",
        description="Cierra la narración e inicia la fase de votación",
    )
    async def iniciar_votacion(self, interaction: discord.Interaction):
        if not _es_admin(interaction):
            return await interaction.response.send_message(
                "❌ No tienes permisos para usar este comando.", ephemeral=True
            )

        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo:
            return await interaction.response.send_message(
                "⚠️ No hay ningún evento activo.", ephemeral=True
            )

        if activo["estado"] != "narrando":
            return await interaction.response.send_message(
                f"⚠️ El evento está en estado `{activo['estado']}`. "
                f"Solo se puede iniciar la votación desde el estado `narrando`.",
                ephemeral=True,
            )

        await interaction.response.defer()

        # Cerrar sesiones de voz abiertas
        await database.cerrar_sesiones_abiertas(self.bot.db, activo["id"])

        # Calcular la duración total de la narración
        ts_inicio = activo["timestamp_inicio_narracion"]
        if ts_inicio:
            dt_inicio = datetime.fromisoformat(ts_inicio)
            dt_ahora = datetime.now(timezone.utc)
            duracion_min = (dt_ahora - dt_inicio).total_seconds() / 60.0
        else:
            duracion_min = 0

        await database.guardar_duracion_narracion(self.bot.db, activo["id"], round(duracion_min, 2))

        # Calcular asistencia y determinar habilitados
        asistencia = await database.calcular_asistencia_total(self.bot.db, activo["id"])
        umbral = duracion_min * config.PORCENTAJE_ASISTENCIA_MINIMO

        habilitados = {
            uid: mins for uid, mins in asistencia.items() if mins >= umbral
        }
        await database.guardar_habilitados(self.bot.db, activo["id"], habilitados)

        # Cambiar estado
        await database.cambiar_estado_evento(self.bot.db, activo["id"], "votando")

        # Construir embed de resultados
        embed = discord.Embed(
            title="🗳️ ¡Votación Abierta!",
            description=(
                f"**{activo['nombre']}**\n\n"
                f"⏱️ Duración de la narración: **{duracion_min:.1f} minutos**\n"
                f"📊 Umbral de asistencia (70%): **{umbral:.1f} minutos**\n"
                f"✅ Usuarios habilitados para votar: **{len(habilitados)}**\n\n"
                f"Usa `/votar` para emitir tu voto."
            ),
            color=config.COLOR_PRINCIPAL,
        )

        if habilitados:
            nombres = []
            guild = interaction.guild
            for uid in habilitados:
                member = guild.get_member(int(uid))
                nombres.append(member.display_name if member else f"ID:{uid}")
            embed.add_field(
                name="👥 Habilitados",
                value="\n".join(f"• {n}" for n in nombres),
                inline=False,
            )

        embed.set_footer(text="Los votos son privados. Usa /evento cerrar para finalizar.")

        await interaction.followup.send(embed=embed)

    # ── /evento cerrar ──

    @evento_group.command(
        name="cerrar",
        description="Cierra el evento y publica los resultados finales",
    )
    async def cerrar(self, interaction: discord.Interaction):
        if not _es_admin(interaction):
            return await interaction.response.send_message(
                "❌ No tienes permisos para usar este comando.", ephemeral=True
            )

        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo:
            return await interaction.response.send_message(
                "⚠️ No hay ningún evento activo para cerrar.", ephemeral=True
            )

        await interaction.response.defer()

        # Si estaba en narración, cerrar sesiones abiertas
        if activo["estado"] == "narrando":
            await database.cerrar_sesiones_abiertas(self.bot.db, activo["id"])

        # Obtener resultados de votación
        resultados = await database.obtener_resultados_votacion(self.bot.db, activo["id"])

        # Cambiar estado
        await database.cambiar_estado_evento(self.bot.db, activo["id"], "cerrado")

        # Construir embed de resultados
        embed = discord.Embed(
            title="🏆 Evento Finalizado",
            description=f"**{activo['nombre']}**",
            color=config.COLOR_EXITO,
        )

        if resultados:
            podio = ["🥇", "🥈", "🥉"]
            tabla = []
            for i, r in enumerate(resultados):
                medalla = podio[i] if i < len(podio) else f"#{i+1}"
                titulo = r["titulo_historia"] or "Sin título"
                tabla.append(f"{medalla} **{r['usuario_nombre']}** — _{titulo}_ ({r['total_votos']} votos)")

            embed.add_field(
                name="📊 Resultados",
                value="\n".join(tabla),
                inline=False,
            )

            # Anunciar ganador
            ganador = resultados[0]
            if ganador["total_votos"] > 0:
                embed.add_field(
                    name="🎉 ¡Ganador!",
                    value=f"**{ganador['usuario_nombre']}** con _{ganador['titulo_historia'] or 'Sin título'}_",
                    inline=False,
                )
        else:
            embed.add_field(
                name="📊 Resultados",
                value="No hubo participantes registrados.",
                inline=False,
            )

        embed.set_footer(text="Este evento ha sido archivado. Consulta /reto historial")

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Eventos(bot))
