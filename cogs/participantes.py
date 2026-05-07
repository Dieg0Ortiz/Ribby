"""
cogs/participantes.py — Registro de participantes y detección automática de archivos.

Comandos:
  /participante_registrar [titulo]          — Cualquier usuario se registra a sí mismo.
  /participante_registrar [titulo] [@usuario] — Un admin registra a otro usuario.

Listeners:
  on_message — Detecta PDFs y portadas SOLO de participantes ya registrados.
"""

import logging
from typing import Optional
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
import database
import personalidad as ribby

log = logging.getLogger("bot-literario.participantes")


def _es_admin(interaction: discord.Interaction) -> bool:
    """Verifica si el usuario tiene el rol de administrador literario."""
    return any(
        role.name == config.ADMIN_ROLE_NAME for role in interaction.user.roles
    )


# Extensiones válidas para documentos (historias)
EXTENSIONES_DOCUMENTO = {".pdf", ".docx", ".doc"}

# Extensiones válidas para portadas
EXTENSIONES_IMAGEN = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# Estados en los que se aceptan archivos
ESTADOS_ACEPTAN_ARCHIVOS = {"abierto", "narrando"}


class Participantes(commands.Cog):
    """Cog para registro de participantes y detección de archivos."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /participante_registrar ──

    @app_commands.command(
        name="participante_registrar",
        description="Regístrate en el evento activo (o un admin registra a otro usuario)",
    )
    @app_commands.describe(
        titulo="Título de tu historia",
        usuario="(Solo admins) El usuario a registrar. Si no se indica, te registras tú mismo.",
    )
    @app_commands.guilds(*config.GUILD_IDS) if config.GUILD_IDS else lambda f: f
    async def registrar(
        self,
        interaction: discord.Interaction,
        titulo: str,
        usuario: Optional[discord.Member] = None,
    ):
        # Determinar quién se registra
        if usuario is not None and usuario.id != interaction.user.id:
            # Se intenta registrar a OTRO usuario → requiere admin
            if not _es_admin(interaction):
                embed = discord.Embed(
                    description=(
                        "**⛔  Sin permisos**\n\n"
                        "Solo un administrador puede registrar a otro usuario."
                    ),
                    color=config.COLOR_ERROR,
                )
                return await interaction.response.send_message(embed=embed, ephemeral=True)
            objetivo = usuario
        else:
            # El usuario se registra a sí mismo → cualquiera puede
            objetivo = interaction.user

        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo:
            embed = discord.Embed(
                description="**⚠️  Sin evento activo**\n\nNo hay ningún evento activo en este momento.",
                color=config.COLOR_ADVERTENCIA,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if activo["estado"] not in ESTADOS_ACEPTAN_ARCHIVOS:
            embed = discord.Embed(
                description=(
                    "**⚠️  Registro cerrado**\n\n"
                    "Solo se pueden registrar participantes cuando el evento está `abierto` o `narrando`."
                ),
                color=config.COLOR_ADVERTENCIA,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        pid = await database.registrar_participante(
            self.bot.db,
            activo["id"],
            str(objetivo.id),
            objetivo.display_name,
            titulo,
        )

        embed = discord.Embed(
            title="✨  ¡Registro Exitoso!",
            description=(
                f"{config.SEPARADOR}\n\n"
                f"{ribby.frase(ribby.REGISTRO, usuario=objetivo.display_name)}\n\n"
                f"{config.SEPARADOR}"
            ),
            color=config.COLOR_EXITO,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="👤  Autor", value=objetivo.mention, inline=True)
        embed.add_field(name="✍️  Título", value=f"*{titulo}*", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="📖  Evento", value=f"**{activo['nombre']}**", inline=True)
        embed.add_field(name="📊  Estado", value=f"`{activo['estado'].upper()}`", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(
            name="📌  ¿Qué sigue?",
            value="Sube tu documento (PDF/DOCX) y portada (imagen) en el canal de envío configurado.",
            inline=False,
        )
        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        embed.set_thumbnail(url=objetivo.display_avatar.url)
        embed.set_footer(text=ribby.tip_aleatorio())

        await interaction.response.send_message(embed=embed)

    # ── Listener: Detección automática de archivos ──

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Detecta PDFs y portadas subidos al canal de envío del evento activo.
        Solo acepta archivos de participantes previamente registrados."""
        # Ignorar mensajes del bot
        if message.author.bot:
            return

        # Ignorar mensajes sin adjuntos
        if not message.attachments:
            return

        log.info(
            f"📨 Mensaje con {len(message.attachments)} adjunto(s) de {message.author.display_name} "
            f"en canal {message.channel.name} (ID: {message.channel.id})"
        )

        # Verificar si hay un evento activo con canal de envío configurado
        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo:
            log.info("   ↳ Ignorado: no hay evento activo")
            return

        if activo["estado"] not in ESTADOS_ACEPTAN_ARCHIVOS:
            log.info(f"   ↳ Ignorado: evento en estado '{activo['estado']}' (se requiere abierto o narrando)")
            return

        if not activo["canal_envio_id"]:
            log.info("   ↳ Ignorado: el evento no tiene canal de envío configurado")
            return

        if message.channel.id != activo["canal_envio_id"]:
            log.info(
                f"   ↳ Ignorado: canal {message.channel.id} ≠ canal_envio {activo['canal_envio_id']}"
            )
            return

        log.info(f"   ↳ Canal correcto. Procesando archivos para evento '{activo['nombre']}'...")

        # Buscar al participante — DEBE estar registrado previamente
        participante = await database.obtener_participante_por_usuario(
            self.bot.db, activo["id"], str(message.author.id)
        )

        if not participante:
            # No está registrado → rechazar y avisar
            log.info(f"   ↳ Rechazado: {message.author.display_name} no está registrado en el evento")
            try:
                embed = discord.Embed(
                    description=(
                        "**⚠️  No estás registrado**\n\n"
                        "Debes registrarte primero con el comando:\n"
                        "```/participante_registrar titulo:<título de tu historia>```\n"
                        "Después podrás subir tu documento y portada aquí."
                    ),
                    color=config.COLOR_ADVERTENCIA,
                )
                embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
                embed.set_footer(text="Este mensaje se eliminará en 20 segundos")
                await message.reply(embed=embed, delete_after=20)
            except discord.HTTPException:
                pass
            return

        # Procesar cada adjunto
        archivos_procesados = []

        for attachment in message.attachments:
            filename = attachment.filename.lower()
            log.info(f"   ↳ Archivo: {attachment.filename} ({attachment.content_type})")

            # Detectar documentos (PDF, DOCX, DOC)
            if any(filename.endswith(ext) for ext in EXTENSIONES_DOCUMENTO):
                url_guardada = attachment.url

                # Reenviar al canal de respaldo si está configurado
                if activo["canal_respaldo_id"]:
                    canal_respaldo = self.bot.get_channel(activo["canal_respaldo_id"])
                    if canal_respaldo:
                        try:
                            file = await attachment.to_file()
                            msg_respaldo = await canal_respaldo.send(
                                content=f"📄 Documento de **{message.author.display_name}** — Evento: {activo['nombre']}",
                                file=file,
                            )
                            if msg_respaldo.attachments:
                                url_guardada = msg_respaldo.attachments[0].url
                        except Exception as e:
                            log.warning(f"   ↳ Error al respaldar documento: {e}")

                await database.actualizar_pdf(self.bot.db, participante["id"], url_guardada)
                archivos_procesados.append(("📄", "Documento", attachment.filename))
                log.info(f"   ✅ Documento guardado para {message.author.display_name}")

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
                        except Exception as e:
                            log.warning(f"   ↳ Error al respaldar portada: {e}")

                await database.actualizar_portada(self.bot.db, participante["id"], url_guardada)
                archivos_procesados.append(("🖼️", "Portada", attachment.filename))
                log.info(f"   ✅ Portada guardada para {message.author.display_name}")
            else:
                log.info(f"   ↳ Archivo ignorado (tipo no reconocido): {attachment.filename}")

        # Confirmar al usuario con un embed bonito
        if archivos_procesados:
            # Contar libros en la biblioteca
            libros = await database.contar_libros_biblioteca(self.bot.db)

            # Elegir frase según tipo de archivo
            tiene_doc = any(t == "Documento" for _, t, _ in archivos_procesados)
            tiene_portada = any(t == "Portada" for _, t, _ in archivos_procesados)

            if tiene_doc and tiene_portada:
                frase = ribby.frase(ribby.NUEVO_LIBRO, libros=libros)
            elif tiene_doc:
                frase = ribby.frase(ribby.NUEVO_LIBRO, libros=libros)
            else:
                frase = ribby.frase(ribby.NUEVA_PORTADA)

            desc_lineas = []
            for emoji, tipo, nombre in archivos_procesados:
                desc_lineas.append(f"{emoji}  **{tipo}**  →  `{nombre}`")

            embed = discord.Embed(
                title="✅  Archivos Recibidos",
                description=(
                    f"{config.SEPARADOR}\n\n"
                    f"{frase}\n\n"
                    + "\n".join(desc_lineas)
                    + f"\n\n{config.SEPARADOR}"
                ),
                color=config.COLOR_EXITO,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(
                name="Ribby 🎀",
                icon_url=config.BOT_ICON_URL or None,
            )
            embed.set_footer(text=f"Biblioteca de Ribby: {libros} libro(s)  •  Se borra en 15s")

            try:
                await message.reply(embed=embed, delete_after=15)
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Participantes(bot))
