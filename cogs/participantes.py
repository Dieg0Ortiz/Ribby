"""
cogs/participantes.py — Registro de participantes y detección automática de archivos.

Comandos:
  /participante registrar [@usuario] [titulo]

Listeners:
  on_message — Detecta PDFs y portadas en el canal de envío configurado.
"""

import discord
from discord import app_commands
from discord.ext import commands

import config
import database


def _es_admin(interaction: discord.Interaction) -> bool:
    """Verifica si el usuario tiene el rol de administrador literario."""
    return any(
        role.name == config.ADMIN_ROLE_NAME for role in interaction.user.roles
    )


# Extensiones válidas para portadas
EXTENSIONES_IMAGEN = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class Participantes(commands.Cog):
    """Cog para registro de participantes y detección de archivos."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /participante registrar ──

    @app_commands.command(
        name="participante_registrar",
        description="Registra un participante en el evento activo",
    )
    @app_commands.describe(
        usuario="El usuario de Discord a registrar",
        titulo="Título de la historia",
    )
    @app_commands.guilds(config.GUILD_ID) if config.GUILD_ID else lambda f: f
    async def registrar(
        self,
        interaction: discord.Interaction,
        usuario: discord.Member,
        titulo: str,
    ):
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
                "⚠️ Solo se pueden registrar participantes cuando el evento está `abierto`.",
                ephemeral=True,
            )

        pid = await database.registrar_participante(
            self.bot.db,
            activo["id"],
            str(usuario.id),
            usuario.display_name,
            titulo,
        )

        embed = discord.Embed(
            title="✅ Participante Registrado",
            color=config.COLOR_EXITO,
        )
        embed.add_field(name="👤 Autor", value=usuario.mention, inline=True)
        embed.add_field(name="📝 Título", value=titulo, inline=True)
        embed.add_field(name="📖 Evento", value=activo["nombre"], inline=False)
        embed.set_footer(
            text="El autor puede subir su PDF y portada en el canal configurado"
        )

        await interaction.response.send_message(embed=embed)

    # ── Listener: Detección automática de archivos ──

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Detecta PDFs y portadas subidos al canal de envío del evento activo."""
        # Ignorar mensajes del bot
        if message.author.bot:
            return

        # Ignorar mensajes sin adjuntos
        if not message.attachments:
            return

        # Verificar si hay un evento activo con canal de envío configurado
        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo or activo["estado"] != "abierto":
            return

        if not activo["canal_envio_id"] or message.channel.id != activo["canal_envio_id"]:
            return

        # Buscar al participante
        participante = await database.obtener_participante_por_usuario(
            self.bot.db, activo["id"], str(message.author.id)
        )

        if not participante:
            # Auto-registrar al usuario si sube archivos en el canal correcto
            pid = await database.registrar_participante(
                self.bot.db,
                activo["id"],
                str(message.author.id),
                message.author.display_name,
            )
            participante = await database.obtener_participante_por_usuario(
                self.bot.db, activo["id"], str(message.author.id)
            )

        # Procesar cada adjunto
        archivos_procesados = []

        for attachment in message.attachments:
            filename = attachment.filename.lower()

            # Detectar PDF
            if filename.endswith(".pdf"):
                url_guardada = attachment.url

                # Reenviar al canal de respaldo si está configurado
                if activo["canal_respaldo_id"]:
                    canal_respaldo = self.bot.get_channel(activo["canal_respaldo_id"])
                    if canal_respaldo:
                        try:
                            file = await attachment.to_file()
                            msg_respaldo = await canal_respaldo.send(
                                content=f"📄 PDF de **{message.author.display_name}** — Evento: {activo['nombre']}",
                                file=file,
                            )
                            # Usar la URL del respaldo que es más duradera
                            if msg_respaldo.attachments:
                                url_guardada = msg_respaldo.attachments[0].url
                        except Exception:
                            pass  # Si falla el respaldo, usar la URL original

                await database.actualizar_pdf(self.bot.db, participante["id"], url_guardada)
                archivos_procesados.append(f"📄 PDF: `{attachment.filename}`")

            # Detectar imágenes de portada
            elif any(filename.endswith(ext) for ext in EXTENSIONES_IMAGEN):
                url_guardada = attachment.url

                # Reenviar al canal de respaldo
                if activo["canal_respaldo_id"]:
                    canal_respaldo = self.bot.get_channel(activo["canal_respaldo_id"])
                    if canal_respaldo:
                        try:
                            file = await attachment.to_file()
                            msg_respaldo = await canal_respaldo.send(
                                content=f"🖼️ Portada de **{message.author.display_name}** — Evento: {activo['nombre']}",
                                file=file,
                            )
                            if msg_respaldo.attachments:
                                url_guardada = msg_respaldo.attachments[0].url
                        except Exception:
                            pass

                await database.actualizar_portada(self.bot.db, participante["id"], url_guardada)
                archivos_procesados.append(f"🖼️ Portada: `{attachment.filename}`")

        # Confirmar al usuario
        if archivos_procesados:
            embed = discord.Embed(
                title="✅ Archivos Recibidos",
                description="\n".join(archivos_procesados),
                color=config.COLOR_EXITO,
            )
            embed.set_footer(text="Si subes nuevos archivos, se reemplazarán los anteriores")

            try:
                await message.reply(embed=embed, delete_after=15)
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Participantes(bot))
