"""
cogs/eventos.py — Gestión del ciclo de vida de eventos literarios.

Comandos de administrador:
  /evento crear [nombre]
  /evento configurar [canal_voz] [canal_envio]
  /evento iniciar_narracion
  /evento cerrar_narracion
  /evento iniciar_votacion
  /evento cerrar
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
import math

import config
import database
import personalidad as ribby


def _es_admin(interaction: discord.Interaction) -> bool:
    """Verifica si el usuario tiene el rol de administrador literario."""
    return any(
        role.name == config.ADMIN_ROLE_NAME for role in interaction.user.roles
    )


def _embed_error(titulo: str, descripcion: str) -> discord.Embed:
    """Crea un embed de error estilizado."""
    embed = discord.Embed(
        description=f"**{titulo}**\n\n{descripcion}",
        color=config.COLOR_ERROR,
    )
    embed.set_author(name="⛔  Error", icon_url=config.BOT_ICON_URL or None)
    return embed


def _embed_advertencia(titulo: str, descripcion: str) -> discord.Embed:
    """Crea un embed de advertencia estilizado."""
    embed = discord.Embed(
        description=f"**{titulo}**\n\n{descripcion}",
        color=config.COLOR_ADVERTENCIA,
    )
    embed.set_author(name="⚠️  Advertencia", icon_url=config.BOT_ICON_URL or None)
    return embed


class Eventos(commands.Cog):
    """Cog para la gestión de eventos literarios."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Grupo de comandos /evento ──

    evento_group = app_commands.Group(
        name="evento",
        description="Gestión de eventos literarios (solo administradores)",
        guild_ids=config.GUILD_IDS if config.GUILD_IDS else None,
    )

    # ── /evento crear ──

    @evento_group.command(name="crear", description="Crea un nuevo evento literario")
    @app_commands.describe(nombre="Nombre del evento (ej. 'Misterios — Reto #3')")
    async def crear(self, interaction: discord.Interaction, nombre: str):
        if not _es_admin(interaction):
            return await interaction.response.send_message(
                embed=_embed_error("Sin permisos", "No tienes permisos para usar este comando."),
                ephemeral=True,
            )

        # Verificar que no haya un evento activo
        activo = await database.obtener_evento_activo(self.bot.db)
        if activo:
            return await interaction.response.send_message(
                embed=_embed_advertencia(
                    "Evento activo existente",
                    f"Ya existe un evento activo: **{activo['nombre']}** (ID: `{activo['id']}`).\n"
                    f"Ciérralo primero con `/evento cerrar`."
                ),
                ephemeral=True,
            )

        evento_id = await database.crear_evento(self.bot.db, nombre)

        embed = discord.Embed(
            title="✨  Nuevo Evento Literario",
            description=(
                f"{config.SEPARADOR}\n\n"
                f"📖  **{nombre}**\n\n"
                f"{ribby.frase(ribby.EVENTO_CREADO)}\n\n"
                f"{config.SEPARADOR}"
            ),
            color=config.COLOR_EXITO,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="🆔  Identificador",
            value=f"```{evento_id}```",
            inline=True,
        )
        embed.add_field(
            name="📊  Estado",
            value="```🟢 Abierto```",
            inline=True,
        )
        embed.add_field(
            name="\u200b",
            value="\u200b",
            inline=True,
        )
        embed.add_field(
            name="📌  Siguiente paso",
            value="Usa `/evento configurar` para asociar los canales de voz y texto.",
            inline=False,
        )
        embed.set_author(
            name="Ribby 🎀",
            icon_url=config.BOT_ICON_URL or None,
        )
        embed.set_footer(text=ribby.tip_aleatorio())

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
                embed=_embed_error("Sin permisos", "No tienes permisos para usar este comando."),
                ephemeral=True,
            )

        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo:
            return await interaction.response.send_message(
                embed=_embed_advertencia(
                    "Sin evento activo",
                    "No hay ningún evento activo. Crea uno con `/evento crear`."
                ),
                ephemeral=True,
            )

        respaldo_id = canal_respaldo.id if canal_respaldo else None
        await database.configurar_canales_evento(
            self.bot.db, activo["id"], canal_voz.id, canal_envio.id, respaldo_id
        )

        canales_texto = (
            f"🔊  **Canal de voz:**  {canal_voz.mention}\n"
            f"📝  **Canal de envío:**  {canal_envio.mention}"
        )
        if canal_respaldo:
            canales_texto += f"\n🔒  **Canal de respaldo:**  {canal_respaldo.mention}"

        embed = discord.Embed(
            title="⚙️  Evento Configurado",
            description=(
                f"{config.SEPARADOR}\n\n"
                f"📖  **{activo['nombre']}**  •  ID: `{activo['id']}`\n\n"
                f"{canales_texto}\n\n"
                f"{config.SEPARADOR}"
            ),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="📌  Siguiente paso",
            value="Usa `/evento iniciar_narracion` cuando estén listos para comenzar.",
            inline=False,
        )
        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        embed.set_footer(text="COMARCALIT  •  Retos Literarios")

        await interaction.response.send_message(embed=embed)

    # ── /evento iniciar_narracion ──

    @evento_group.command(
        name="iniciar_narracion",
        description="Inicia una sesión de narración (puede haber varias por evento)",
    )
    async def iniciar_narracion(self, interaction: discord.Interaction):
        if not _es_admin(interaction):
            return await interaction.response.send_message(
                embed=_embed_error("Sin permisos", "No tienes permisos para usar este comando."),
                ephemeral=True,
            )

        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo:
            return await interaction.response.send_message(
                embed=_embed_advertencia("Sin evento activo", "No hay ningún evento activo."),
                ephemeral=True,
            )

        if activo["estado"] != "abierto":
            return await interaction.response.send_message(
                embed=_embed_advertencia(
                    "Estado incorrecto",
                    f"El evento está en estado `{activo['estado']}`.\n"
                    f"Solo se puede iniciar la narración desde el estado `abierto`.\n"
                    f"Si hay una narración activa, ciérrala primero con `/evento cerrar_narracion`."
                ),
                ephemeral=True,
            )

        if not activo["canal_voz_id"]:
            return await interaction.response.send_message(
                embed=_embed_advertencia(
                    "Canal no configurado",
                    "Primero configura el canal de voz con `/evento configurar`."
                ),
                ephemeral=True,
            )

        await interaction.response.defer()

        # Crear nueva sesión de narración
        narracion_id, numero_sesion = await database.crear_narracion(self.bot.db, activo["id"])

        # Cambiar estado a narrando
        await database.cambiar_estado_evento(self.bot.db, activo["id"], "narrando")

        # Registrar automáticamente a los usuarios que ya están en el canal de voz
        registrados_previos = 0
        canal_voz_id = activo["canal_voz_id"]
        for member in interaction.guild.members:
            if member.bot:
                continue
            if (
                member.voice
                and member.voice.channel
                and member.voice.channel.id == canal_voz_id
            ):
                await database.registrar_entrada_voz(
                    self.bot.db, activo["id"], str(member.id), narracion_id
                )
                registrados_previos += 1

        embed = discord.Embed(
            title=f"🎙️  Narración #{numero_sesion}  —  ¡En Vivo!",
            description=(
                f"{config.SEPARADOR}\n\n"
                f"📖  **{activo['nombre']}**\n\n"
                f"{ribby.frase(ribby.NARRACION)}\n\n"
                f"{config.SEPARADOR}"
            ),
            color=config.COLOR_NARRACION,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="🔢  Sesión",
            value=f"```#{numero_sesion}```",
            inline=True,
        )
        embed.add_field(
            name="👥  Oyentes",
            value=f"```{registrados_previos} usuario(s)```",
            inline=True,
        )
        embed.add_field(
            name="⏱️  Asistencia mín.",
            value=f"```{int(config.PORCENTAJE_ASISTENCIA_MINIMO * 100)}% del total```",
            inline=True,
        )
        embed.add_field(
            name="📌  Info",
            value=(
                "• Se registra automáticamente tu entrada y salida del canal de voz.\n"
                "• Al terminar, usa `/evento cerrar_narracion` para cerrar esta sesión.\n"
                "• Puedes abrir más sesiones luego. La asistencia se acumula."
            ),
            inline=False,
        )
        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        embed.set_footer(text=ribby.tip_aleatorio())

        await interaction.followup.send(embed=embed)

    # ── /evento cerrar_narracion ──

    @evento_group.command(
        name="cerrar_narracion",
        description="Cierra la sesión de narración actual (el evento sigue abierto)",
    )
    async def cerrar_narracion(self, interaction: discord.Interaction):
        if not _es_admin(interaction):
            return await interaction.response.send_message(
                embed=_embed_error("Sin permisos", "No tienes permisos para usar este comando."),
                ephemeral=True,
            )

        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo:
            return await interaction.response.send_message(
                embed=_embed_advertencia("Sin evento activo", "No hay ningún evento activo."),
                ephemeral=True,
            )

        if activo["estado"] != "narrando":
            return await interaction.response.send_message(
                embed=_embed_advertencia(
                    "No hay narración activa",
                    "No hay una sesión de narración en curso para cerrar."
                ),
                ephemeral=True,
            )

        await interaction.response.defer()

        # Cerrar sesiones de voz abiertas
        await database.cerrar_sesiones_abiertas(self.bot.db, activo["id"])

        # Cerrar la narración activa
        resultado = await database.cerrar_narracion_activa(self.bot.db, activo["id"])
        if not resultado:
            return await interaction.followup.send(
                embed=_embed_advertencia("Error", "No se encontró una narración activa."),
            )

        narr_id, duracion_min, numero_sesion = resultado

        # Calcular asistencia de esta sesión
        asistencia = await database.calcular_asistencia_total(self.bot.db, activo["id"])

        # Obtener historial de todas las narraciones
        narraciones = await database.obtener_narraciones(self.bot.db, activo["id"])
        duracion_total = sum(n["duracion_minutos"] for n in narraciones)
        total_sesiones = len(narraciones)

        # Cambiar estado de vuelta a abierto
        await database.cambiar_estado_evento(self.bot.db, activo["id"], "abierto")

        embed = discord.Embed(
            title=f"⏹️  Narración #{numero_sesion} Cerrada",
            description=(
                f"{config.SEPARADOR}\n\n"
                f"📖  **{activo['nombre']}**\n\n"
                f"La sesión de narración ha terminado.\n"
                f"El evento sigue **abierto** — puedes iniciar otra narración cuando quieras.\n\n"
                f"{config.SEPARADOR}"
            ),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="⏱️  Esta sesión",
            value=f"```{duracion_min:.1f} min```",
            inline=True,
        )
        embed.add_field(
            name="📊  Total acumulado",
            value=f"```{duracion_total:.1f} min ({total_sesiones} sesión{'es' if total_sesiones > 1 else ''})```",
            inline=True,
        )
        embed.add_field(
            name="👥  Asistentes registrados",
            value=f"```{len(asistencia)} usuario(s)```",
            inline=True,
        )
        embed.add_field(
            name="📌  ¿Qué sigue?",
            value=(
                "• `/evento iniciar_narracion` — Abrir otra sesión\n"
                "• `/evento iniciar_votacion` — Iniciar votación"
            ),
            inline=False,
        )
        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        embed.set_footer(text=ribby.tip_aleatorio())

        await interaction.followup.send(embed=embed)

    # ── /evento iniciar_votacion ──

    @evento_group.command(
        name="iniciar_votacion",
        description="Cierra las narraciones e inicia la fase de votación",
    )
    async def iniciar_votacion(self, interaction: discord.Interaction):
        if not _es_admin(interaction):
            return await interaction.response.send_message(
                embed=_embed_error("Sin permisos", "No tienes permisos para usar este comando."),
                ephemeral=True,
            )

        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo:
            return await interaction.response.send_message(
                embed=_embed_advertencia("Sin evento activo", "No hay ningún evento activo."),
                ephemeral=True,
            )

        if activo["estado"] not in ("abierto", "narrando"):
            return await interaction.response.send_message(
                embed=_embed_advertencia(
                    "Estado incorrecto",
                    f"El evento está en estado `{activo['estado']}`.\n"
                    f"Solo se puede iniciar la votación desde `abierto` o `narrando`."
                ),
                ephemeral=True,
            )

        # Verificar que haya al menos una narración cerrada
        narraciones = await database.obtener_narraciones(self.bot.db, activo["id"])
        narracion_activa = await database.obtener_narracion_activa(self.bot.db, activo["id"])

        if not narraciones and not narracion_activa:
            return await interaction.response.send_message(
                embed=_embed_advertencia(
                    "Sin narraciones",
                    "No se ha realizado ninguna sesión de narración.\n"
                    "Usa `/evento iniciar_narracion` primero."
                ),
                ephemeral=True,
            )

        await interaction.response.defer()

        # Si hay una narración activa, cerrarla automáticamente
        if activo["estado"] == "narrando" and narracion_activa:
            await database.cerrar_sesiones_abiertas(self.bot.db, activo["id"])
            await database.cerrar_narracion_activa(self.bot.db, activo["id"])

        # Calcular duración total de TODAS las narraciones
        narraciones = await database.obtener_narraciones(self.bot.db, activo["id"])
        duracion_total = sum(n["duracion_minutos"] for n in narraciones)
        total_sesiones = len(narraciones)

        # Guardar duración total en el evento
        await database.guardar_duracion_total_narraciones(self.bot.db, activo["id"])

        # ── Condición 1: Asistencia de Voz ──
        asistencia = await database.calcular_asistencia_total(self.bot.db, activo["id"])
        umbral_voz = duracion_total * config.PORCENTAJE_ASISTENCIA_MINIMO

        # ── Condición 2: Descargas de Documentos ──
        total_documentos = await database.contar_documentos_subidos(self.bot.db, activo["id"])
        umbral_lectura = math.ceil(total_documentos * 0.5)
        descargas_usuarios = await database.calcular_descargas_por_usuario(self.bot.db, activo["id"])

        # ── Combinar habilitados ──
        habilitados_dict = {}

        # 1. Procesar asistencia de voz
        for uid, mins in asistencia.items():
            if mins >= umbral_voz:
                if uid not in habilitados_dict:
                    habilitados_dict[uid] = {"minutos": mins, "descargas": descargas_usuarios.get(uid, 0)}

        # 2. Procesar descargas de documentos
        if total_documentos > 0:
            for uid, descargas in descargas_usuarios.items():
                if descargas >= umbral_lectura:
                    if uid not in habilitados_dict:
                        habilitados_dict[uid] = {"minutos": asistencia.get(uid, 0), "descargas": descargas}

        await database.guardar_habilitados(self.bot.db, activo["id"], habilitados_dict)

        # Cambiar estado
        await database.cambiar_estado_evento(self.bot.db, activo["id"], "votando")

        # Construir embed PÚBLICO (sin detalles de antifraude)
        embed = discord.Embed(
            title="🗳️  ¡Votación Abierta!",
            description=(
                f"{config.SEPARADOR}\n\n"
                f"📖  **{activo['nombre']}**\n\n"
                f"{ribby.frase(ribby.VOTACION)}\n\n"
                f"La votación para este reto ya está disponible.\n"
                f"Usa `/votar` para emitir tu voto de forma anónima.\n\n"
                f"{config.SEPARADOR}"
            ),
            color=config.COLOR_VOTACION,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="📊  Sesiones de narración",
            value=f"```{total_sesiones} sesión(es)  •  {duracion_total:.1f} min totales```",
            inline=False,
        )
        embed.add_field(
            name="📌  ¿Cómo votar?",
            value="Usa el comando `/votar` para emitir tu voto de forma anónima.",
            inline=False,
        )
        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        embed.set_footer(text=ribby.tip_aleatorio())

        await interaction.followup.send(embed=embed)

        # ── Reporte privado para el admin ──
        admin_embed = discord.Embed(
            title="🔒  Reporte de Habilitados (Solo Admin)",
            description=(
                f"{config.SEPARADOR}\n\n"
                f"📖  **{activo['nombre']}**\n\n"
                f"Aquí tienes el desglose del sistema antifraude.\n"
                f"Los usuarios que **no** aparezcan en la lista de habilitados\n"
                f"podrán votar, pero su voto será **anulado silenciosamente**.\n\n"
                f"{config.SEPARADOR}"
            ),
            color=0x4B5563,
            timestamp=datetime.now(timezone.utc),
        )
        admin_embed.add_field(
            name="🎙️  Umbral de Voz",
            value=f"```{umbral_voz:.1f} min (70%)```",
            inline=True,
        )
        admin_embed.add_field(
            name="📥  Umbral de Lectura",
            value=f"```{umbral_lectura} doc{'s' if umbral_lectura != 1 else ''} (50%)```",
            inline=True,
        )
        admin_embed.add_field(
            name="✅  Habilitados",
            value=f"```{len(habilitados_dict)} usuario(s)```",
            inline=True,
        )

        if habilitados_dict:
            nombres = []
            guild = interaction.guild
            for uid, stats in habilitados_dict.items():
                member = guild.get_member(int(uid))
                motivos = []
                if stats["minutos"] >= umbral_voz: motivos.append("🎙️")
                if total_documentos > 0 and stats["descargas"] >= umbral_lectura: motivos.append("📥")

                motivo_icon = " ".join(motivos)
                nombres.append(f"✦  {member.display_name if member else f'ID:{uid}'}  {motivo_icon}")

            admin_embed.add_field(
                name="👥  Votos válidos de",
                value="\n".join(nombres),
                inline=False,
            )

        admin_embed.set_author(name="🔒 Admin", icon_url=config.BOT_ICON_URL or None)
        admin_embed.set_footer(text="Este mensaje solo es visible para ti")

        await interaction.followup.send(embed=admin_embed, ephemeral=True)

    # ── /evento cerrar ──

    @evento_group.command(
        name="cerrar",
        description="Cierra el evento y publica los resultados finales",
    )
    async def cerrar(self, interaction: discord.Interaction):
        if not _es_admin(interaction):
            return await interaction.response.send_message(
                embed=_embed_error("Sin permisos", "No tienes permisos para usar este comando."),
                ephemeral=True,
            )

        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo:
            return await interaction.response.send_message(
                embed=_embed_advertencia("Sin evento activo", "No hay ningún evento activo para cerrar."),
                ephemeral=True,
            )

        await interaction.response.defer()

        # Si estaba en narración, cerrar sesiones abiertas
        if activo["estado"] == "narrando":
            await database.cerrar_sesiones_abiertas(self.bot.db, activo["id"])

        # Obtener resultados de votación
        resultados = await database.obtener_resultados_votacion(self.bot.db, activo["id"])

        # Cambiar estado
        await database.cambiar_estado_evento(self.bot.db, activo["id"], "cerrado")

        # Contar libros en la biblioteca
        libros = await database.contar_libros_biblioteca(self.bot.db)

        # Construir embed de resultados
        embed = discord.Embed(
            title="🏆  Evento Finalizado",
            description=(
                f"{config.SEPARADOR}\n\n"
                f"📖  **{activo['nombre']}**\n\n"
                f"{ribby.frase(ribby.EVENTO_CERRADO)}\n\n"
                f"{ribby.descripcion_biblioteca(libros)}\n\n"
                f"{config.SEPARADOR}"
            ),
            color=config.COLOR_ORO,
            timestamp=datetime.now(timezone.utc),
        )

        if resultados:
            podio_emojis = ["🥇", "🥈", "🥉"]
            tabla_lineas = []
            for i, r in enumerate(resultados):
                medalla = podio_emojis[i] if i < len(podio_emojis) else f"`#{i+1}`"
                titulo = r["titulo_historia"] or "Sin título"
                votos_txt = f"**{r['total_votos']}** voto{'s' if r['total_votos'] != 1 else ''}"
                tabla_lineas.append(f"{medalla}  **{r['usuario_nombre']}**\n╰ _{titulo}_  •  {votos_txt}")

            embed.add_field(
                name="📊  Resultados",
                value="\n\n".join(tabla_lineas),
                inline=False,
            )

            # Anunciar ganador con énfasis
            ganador = resultados[0]
            if ganador["total_votos"] > 0:
                embed.add_field(
                    name=f"{config.SEPARADOR_CORTO}",
                    value=(
                        f"🎉  **¡Felicidades, {ganador['usuario_nombre']}!**\n"
                        f"Tu historia _{ganador['titulo_historia'] or 'Sin título'}_ "
                        f"tendrá un lugar especial en la biblioteca de Ribby~ 🎀"
                    ),
                    inline=False,
                )
        else:
            embed.add_field(
                name="📊  Resultados",
                value="No hubo participantes registrados en este evento.",
                inline=False,
            )

        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        embed.set_footer(text=ribby.tip_aleatorio())

        await interaction.followup.send(embed=embed)

        # ── Reporte privado de votos nulos para admin ──
        conteo = await database.contar_votos_totales(self.bot.db, activo["id"])
        votos_nulos = await database.obtener_votos_nulos(self.bot.db, activo["id"])

        admin_embed = discord.Embed(
            title="🔒  Reporte de Votos (Solo Admin)",
            description=(
                f"{config.SEPARADOR}\n\n"
                f"📖  **{activo['nombre']}**\n\n"
                f"Desglose final de la votación:\n\n"
                f"{config.SEPARADOR}"
            ),
            color=0x4B5563,
            timestamp=datetime.now(timezone.utc),
        )
        admin_embed.add_field(
            name="✅  Votos Válidos",
            value=f"```{conteo['validos']}```",
            inline=True,
        )
        admin_embed.add_field(
            name="❌  Votos Nulos",
            value=f"```{conteo['nulos']}```",
            inline=True,
        )
        admin_embed.add_field(
            name="📊  Total Emitidos",
            value=f"```{conteo['validos'] + conteo['nulos']}```",
            inline=True,
        )

        if votos_nulos:
            guild = interaction.guild
            nulos_lineas = []
            for vn in votos_nulos:
                member = guild.get_member(int(vn["votante_discord_id"]))
                nombre = member.display_name if member else f"ID:{vn['votante_discord_id']}"
                nulos_lineas.append(
                    f"❌  **{nombre}** → votó por _{vn['titulo_historia'] or 'Sin título'}_\n"
                    f"╰ Razón: No cumplió el 70% de voz ni el 50% de lectura"
                )
            admin_embed.add_field(
                name="🚫  Votos Anulados",
                value="\n\n".join(nulos_lineas[:10]),  # Limitar a 10 para no exceder
                inline=False,
            )
        else:
            admin_embed.add_field(
                name="🚫  Votos Anulados",
                value="No hubo votos nulos en este evento.",
                inline=False,
            )

        admin_embed.set_author(name="🔒 Admin", icon_url=config.BOT_ICON_URL or None)
        admin_embed.set_footer(text="Este mensaje solo es visible para ti")

        await interaction.followup.send(embed=admin_embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Eventos(bot))
