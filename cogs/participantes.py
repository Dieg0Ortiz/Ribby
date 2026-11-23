"""
cogs/participantes.py — Registro de participantes y detección automática de archivos.

Comandos:
  /participante_registrar [titulo]          — Cualquier usuario se registra a sí mismo.
  /participante_registrar [titulo] [@usuario] — Un admin registra a otro usuario.

Listeners:
  on_message — Detecta PDFs y portadas SOLO de participantes ya registrados.
"""

import logging
import re
from typing import Optional
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
import database
import personalidad as ribby
import comun
import wattpad as wattpad_api
from comun import en_servidores_configurados, es_admin as _es_admin, md

log = logging.getLogger("bot-literario.participantes")


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
        self.db = bot.db  # type: ignore[attr-defined]

    # ── /participante_registrar ──

    @app_commands.command(
        name="participante_registrar",
        description="Regístrate en el evento activo (o un admin registra a otro usuario)",
    )
    @app_commands.describe(
        titulo="Título de tu historia",
        etiquetas="(Opcional) Géneros, Pokémon y temas separados por comas: romance, lycanroc, escolar",
        descripcion="(Opcional) Resumen corto de tu historia",
        wattpad="(Opcional) Enlace a tu historia o a tu perfil de Wattpad",
        usuario="(Solo admins) El usuario a registrar. Si no se indica, te registras tú mismo.",
    )
    @en_servidores_configurados
    async def registrar(
        self,
        interaction: discord.Interaction,
        titulo: app_commands.Range[str, 1, 200],
        etiquetas: Optional[app_commands.Range[str, 1, 300]] = None,
        descripcion: Optional[app_commands.Range[str, 1, 1500]] = None,
        wattpad: Optional[app_commands.Range[str, 1, 300]] = None,
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

        activo = await database.obtener_evento_activo(self.db)
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

        # Consultar Wattpad puede tardar más de los 3 s que da Discord
        await interaction.response.defer()

        ya_registrado = await database.obtener_participante_por_usuario(self.db, activo["id"], objetivo.id)
        pid = await database.registrar_participante(
            self.db,
            activo["id"],
            objetivo.id,
            objetivo.display_name,
            titulo,
        )
        notas_biblioteca = await self._actualizar_biblioteca(pid, objetivo, etiquetas, descripcion, wattpad)

        embed = discord.Embed(
            title="✏️  Registro Actualizado" if ya_registrado else "✨  ¡Registro Exitoso!",
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
            value=(
                "Tus archivos ya subidos se conservan. Si quieres reemplazarlos, vuelve a subirlos en el canal de envío."
                if ya_registrado else
                "Sube tu documento (PDF/DOCX) y portada (imagen) en el canal de envío configurado."
            ),
            inline=False,
        )
        if notas_biblioteca:
            embed.add_field(name="📚  Biblioteca de Ribby", value="\n".join(notas_biblioteca)[:1024], inline=False)
        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        embed.set_thumbnail(url=objetivo.display_avatar.url)
        embed.set_footer(text=ribby.tip_aleatorio())

        await interaction.followup.send(embed=embed)

    async def _actualizar_biblioteca(
        self,
        participante_id: int,
        autor: discord.abc.User,
        etiquetas: Optional[str],
        descripcion: Optional[str],
        enlace_wattpad: Optional[str],
    ) -> list[str]:
        """Crea/actualiza la ficha de la historia en la biblioteca. Retorna notas para el usuario."""
        notas: list[str] = []
        autor_id = str(autor.id)
        try:
            historia_id = await database.historia_de_participante(self.db, participante_id)

            if enlace_wattpad:
                if "/story/" in enlace_wattpad or re.search(r"wattpad\.com/\d+", enlace_wattpad):
                    datos = await wattpad_api.historia_desde_url(enlace_wattpad)
                    if datos:
                        wid, _ = await database.guardar_historia_wattpad(self.db, datos, autor_id)
                        await database.asociar_participante(self.db, wid, participante_id, autor_id)
                        if datos.get("autor_wattpad"):
                            await database.vincular_autor_wattpad(self.db, datos["autor_wattpad"], autor_id)
                        historia_id = wid
                        notas.append(f"🔗 Vinculada con tu historia de Wattpad: **{md(datos['titulo'])}**")
                    else:
                        notas.append("⚠️ No pude leer ese enlace de Wattpad (¿es público?).")
                else:
                    nombre = wattpad_api.usuario_de_url(enlace_wattpad)
                    if nombre:
                        await database.vincular_autor_wattpad(self.db, nombre, autor_id)
                        notas.append(f"🔗 Perfil de Wattpad vinculado: **{md(nombre)}**")
                        biblioteca = self.bot.get_cog("Biblioteca")
                        if biblioteca is not None:
                            total, nuevas = await biblioteca.importar_autor(nombre, autor_id)  # type: ignore[attr-defined]
                            if total:
                                notas.append(f"📚 {total} historia(s) tuya(s) de Wattpad en la biblioteca ({nuevas} nueva(s))")
                    else:
                        notas.append("⚠️ Ese enlace de Wattpad no lo reconozco.")

            if etiquetas:
                tags = [t.strip().lstrip("#") for t in re.split(r"[,;\n]", etiquetas) if t.strip()]
                await database.agregar_etiquetas(self.db, historia_id, tags, "autor", autor_id)
                notas.append(f"🏷️ Etiquetas: {', '.join(tags)}")

            if descripcion:
                await database.guardar_descripcion(self.db, historia_id, descripcion, "autor")
                notas.append("📝 Resumen guardado")

            biblioteca = self.bot.get_cog("Biblioteca")
            if biblioteca is not None:
                biblioteca.invalidar()  # type: ignore[attr-defined]
            if not (etiquetas and descripcion):
                notas.append("💡 Puedes añadir etiquetas o un resumen cuando quieras con `/biblioteca etiquetar` y `/biblioteca resumir`.")
        except Exception as e:  # noqa: BLE001 — la inscripción al reto no debe fallar por esto
            log.warning(f"No se pudo actualizar la biblioteca para el participante {participante_id}: {e}")
        return notas

    # ── Listener: Detección automática de archivos ──

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Detecta PDFs y portadas subidos al canal de envío del evento activo.
        Solo acepta archivos de participantes previamente registrados."""
        # Ignorar mensajes del bot
        if message.author.bot:
            return
        comun.marcar_usuario(message.author, message.guild.id if message.guild else None)  # Modo de pruebas: decide qué base de datos usar

        # Ignorar mensajes sin adjuntos
        if not message.attachments:
            return

        channel_name = getattr(message.channel, 'name', 'DM')
        log.info(
            f"📨 Mensaje con {len(message.attachments)} adjunto(s) de {message.author.display_name} "
            f"en canal {channel_name} (ID: {message.channel.id})"
        )

        # Verificar si hay un evento activo con canal de envío configurado
        activo = await database.obtener_evento_activo(self.db)
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
            self.db, activo["id"], str(message.author.id)
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

            es_documento = any(filename.endswith(ext) for ext in EXTENSIONES_DOCUMENTO)
            es_imagen    = any(filename.endswith(ext) for ext in EXTENSIONES_IMAGEN)

            if not es_documento and not es_imagen:
                log.info(f"   ↳ Archivo ignorado (tipo no reconocido): {attachment.filename}")
                continue

            tipo       = "pdf"      if es_documento else "portada"
            etiqueta   = "Documento" if es_documento else "Portada"
            emoji_tipo = "📄"        if es_documento else "🖼️"

            # --- URL primaria: la que llega directamente de Discord ---
            url_discord = attachment.url

            # --- URL de respaldo: reenvío al canal privado (más estable) ---
            url_respaldo = None
            if activo["canal_respaldo_id"]:
                canal_respaldo = self.bot.get_channel(activo["canal_respaldo_id"])
                if canal_respaldo and isinstance(canal_respaldo, discord.TextChannel):
                    try:
                        file = await attachment.to_file()
                        prefijo = "📄 Documento" if es_documento else "🖼️ Portada"
                        msg_respaldo = await canal_respaldo.send(
                            content=(
                                f"{prefijo} de **{md(message.author.display_name)}** "
                                f"— Evento: {md(activo['nombre'])}"
                            ),
                            file=file,
                        )
                        if msg_respaldo.attachments:
                            url_respaldo = msg_respaldo.attachments[0].url
                    except Exception as e:
                        log.warning(f"   ↳ Error al respaldar {etiqueta.lower()}: {e}")

            # --- Persistir en documentos_participantes y sincronizar con participantes ---
            try:
                url_activa = await database.guardar_documento(
                    pool               = self.db,
                    participante_id    = participante["id"],
                    evento_id          = activo["id"],
                    usuario_discord_id = str(message.author.id),
                    tipo               = tipo,
                    url_discord        = url_discord,
                    url_respaldo       = url_respaldo,
                    nombre_archivo     = attachment.filename,
                    content_type       = attachment.content_type,
                    tamanio_bytes      = attachment.size,
                )
                log.info(
                    f"   ✅ {etiqueta} persistido para {message.author.display_name} "
                    f"(url={'respaldo' if url_respaldo else 'discord'})"
                )
            except Exception as e:
                # Fallback: si falla la tabla nueva, al menos actualizar participantes directamente
                log.error(f"   ❌ Error persistiendo en documentos_participantes: {e}")
                url_activa = url_respaldo or url_discord
                if tipo == "pdf":
                    await database.actualizar_pdf(self.db, participante["id"], url_activa)
                else:
                    await database.actualizar_portada(self.db, participante["id"], url_activa)

            archivos_procesados.append((emoji_tipo, etiqueta, attachment.filename))

        # Confirmar al usuario con un embed bonito
        if archivos_procesados:
            biblioteca = self.bot.get_cog("Biblioteca")
            if biblioteca is not None:
                biblioteca.invalidar()  # type: ignore[attr-defined]
            # Contar libros en la biblioteca
            libros = await database.contar_libros_biblioteca(self.db)

            # Elegir frase según tipo de archivo
            tiene_doc     = any(t == "Documento" for _, t, _ in archivos_procesados)
            tiene_portada = any(t == "Portada"   for _, t, _ in archivos_procesados)

            if tiene_doc:
                frase = ribby.frase(ribby.NUEVO_LIBRO, libros=libros)
            else:
                frase = ribby.frase(ribby.NUEVA_PORTADA)

            desc_lineas = []
            for emoji, tipo_label, nombre in archivos_procesados:
                desc_lineas.append(f"{emoji}  **{tipo_label}**  →  `{nombre}`")

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