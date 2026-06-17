"""
cogs/votacion.py — Sistema de votación anti-fraude con menú desplegable.

Comando:
  /votar — Muestra un menú desplegable para votar (solo si cumple requisitos).

Verificaciones (en orden):
  1. El evento debe estar en estado 'votando'.
  2. El usuario debe tener votos disponibles (según votos_max_por_usuario del evento).
  3. El usuario no puede votar por sí mismo.
  4. El usuario no puede votar dos veces por la misma historia.

Multi-voto:
  - Los admins pueden configurar el límite con /evento configurar_votos.
  - Default: 1 voto por usuario. Máximo configurable: 10.
  - El menú excluye historias por las que ya votó.
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

import config
import database


class VotoSelect(discord.ui.Select):
    """Menú desplegable con las historias disponibles para votar."""

    def __init__(self, evento_id: int, participantes: list, db, es_valido: bool, votos_usados: int, votos_max: int):
        self.evento_id = evento_id
        self._db = db
        self._es_valido = es_valido
        self._votos_usados = votos_usados
        self._votos_max = votos_max

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
            nuevo_conteo = self._votos_usados + 1
            votos_restantes = self._votos_max - nuevo_conteo

            if self._votos_max > 1:
                # Multi-voto: mostrar progreso
                if votos_restantes > 0:
                    descripcion = (
                        f"{config.SEPARADOR}\n\n"
                        f"Tu voto ha sido guardado de forma **anónima**.\n\n"
                        f"📊  **Voto {nuevo_conteo} de {self._votos_max}** registrado.\n"
                        f"Te {'queda' if votos_restantes == 1 else 'quedan'} **{votos_restantes}** "
                        f"voto{'s' if votos_restantes != 1 else ''} disponible{'s' if votos_restantes != 1 else ''}.\n"
                        f"Usa `/votar` de nuevo para emitir tu siguiente voto.\n\n"
                        f"{config.SEPARADOR}"
                    )
                else:
                    descripcion = (
                        f"{config.SEPARADOR}\n\n"
                        f"Tu voto ha sido guardado de forma **anónima**.\n\n"
                        f"📊  **Voto {nuevo_conteo} de {self._votos_max}** registrado.\n"
                        f"✅  ¡Has usado todos tus votos!\n"
                        f"¡Gracias por participar en el reto!\n\n"
                        f"{config.SEPARADOR}"
                    )
            else:
                # Voto único: mensaje original
                descripcion = (
                    f"{config.SEPARADOR}\n\n"
                    "Tu voto ha sido guardado de forma **anónima**.\n"
                    "¡Gracias por participar en el reto!\n\n"
                    f"{config.SEPARADOR}"
                )

            embed = discord.Embed(
                title="✅  ¡Voto Registrado!",
                description=descripcion,
                color=config.COLOR_EXITO,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
            embed.set_footer(text="COMARCALIT  •  Tu voto es privado y definitivo")
        else:
            embed = discord.Embed(
                title="⚠️  Voto No Registrado",
                description=(
                    f"{config.SEPARADOR}\n\n"
                    "No se pudo registrar tu voto.\n"
                    "Puede que ya hayas votado por esta historia\n"
                    "o hayas usado todos tus votos disponibles.\n\n"
                    f"{config.SEPARADOR}"
                ),
                color=config.COLOR_ADVERTENCIA,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)

        await interaction.response.send_message(embed=embed, ephemeral=True)


class VotoView(discord.ui.View):
    """Vista que contiene el menú de votación."""

    def __init__(self, evento_id: int, participantes: list, db, es_valido: bool, votos_usados: int, votos_max: int):
        super().__init__(timeout=300)
        self.add_item(VotoSelect(evento_id, participantes, db, es_valido, votos_usados, votos_max))


class Votacion(commands.Cog):
    """Cog para el sistema de votación."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="votar", description="Vota por tu historia favorita del evento activo")
    @app_commands.guilds(*config.GUILD_IDS) if config.GUILD_IDS else lambda f: f
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

        # Obtener límite de votos y votos usados
        votos_max = activo.get("votos_max_por_usuario", 1) or 1
        votos_usados = await database.contar_votos_usuario(self.bot.db, evento_id, user_id)

        # Verificación 2 — ¿Ya usó todos sus votos?
        if votos_usados >= votos_max:
            if votos_max == 1:
                msg_ya_voto = (
                    "**⚠️  Ya votaste**\n\n"
                    "Ya registraste tu voto para este evento.\n"
                    "No puedes votar de nuevo."
                )
            else:
                msg_ya_voto = (
                    "**⚠️  Votos agotados**\n\n"
                    f"Ya usaste tus **{votos_max} votos** disponibles para este evento.\n"
                    "No puedes votar de nuevo."
                )
            embed = discord.Embed(
                description=msg_ya_voto,
                color=config.COLOR_ADVERTENCIA,
            )
            embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # Verificación silenciosa — ¿Está habilitado?
        es_valido = await database.esta_habilitado(self.bot.db, evento_id, user_id)

        # Obtener participantes (excluyendo al votante)
        participantes = await database.obtener_participantes(self.bot.db, evento_id)
        participantes = [p for p in participantes if p["usuario_discord_id"] != user_id]

        # Si es multi-voto, excluir historias por las que ya votó
        if votos_usados > 0:
            ya_votados = await database.obtener_votos_usuario_lista(self.bot.db, evento_id, user_id)
            participantes = [p for p in participantes if p["id"] not in ya_votados]

        if not participantes:
            if votos_usados > 0:
                msg_sin = "**⚠️  Sin más historias**\n\nYa votaste por todas las historias disponibles."
            else:
                msg_sin = "**⚠️  Sin candidatos**\n\nNo hay historias disponibles para votar."
            embed = discord.Embed(
                description=msg_sin,
                color=config.COLOR_ADVERTENCIA,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # Construir lista de historias
        historias_lista = []
        for i, p in enumerate(participantes, 1):
            titulo = p["titulo_historia"] or "Sin título"
            historias_lista.append(f"`{i}.`  **{titulo}**  —  *{p['usuario_nombre']}*")

        # Información de votos
        if votos_max > 1:
            votos_restantes = votos_max - votos_usados
            info_votos = (
                f"\n\n🗳️  **Voto {votos_usados + 1} de {votos_max}**  •  "
                f"Te {'queda' if votos_restantes == 1 else 'quedan'} {votos_restantes} "
                f"voto{'s' if votos_restantes != 1 else ''}"
            )
        else:
            info_votos = ""

        embed = discord.Embed(
            title="🗳️  Votación",
            description=(
                f"{config.SEPARADOR}\n\n"
                f"📖  **{activo['nombre']}**\n\n"
                "Selecciona la historia que más te gustó\n"
                "en el menú desplegable de abajo.\n\n"
                f"{config.SEPARADOR_CORTO}\n\n"
                + "\n".join(historias_lista)
                + f"{info_votos}"
                + f"\n\n{config.SEPARADOR}"
            ),
            color=config.COLOR_VOTACION,
            timestamp=datetime.now(timezone.utc),
        )
        if votos_max > 1:
            embed.add_field(
                name="ℹ️  Multi-voto",
                value=f"Puedes votar por hasta **{votos_max} historias diferentes**. Usa `/votar` una vez por cada voto.",
                inline=False,
            )
        embed.add_field(
            name="⚠️  Importante",
            value="Tu voto es **anónimo** y **definitivo**. No podrás cambiarlo.",
            inline=False,
        )
        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="COMARCALIT  •  Retos Literarios  •  Elige sabiamente")

        view = VotoView(evento_id, participantes, self.bot.db, es_valido, votos_usados, votos_max)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Votacion(bot))
