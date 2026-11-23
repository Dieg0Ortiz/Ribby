"""
cogs/votacion.py — Sistema de votación anti-fraude con menú desplegable.

Comando:
  /votar — Muestra un menú desplegable para votar.

Verificaciones (todas se repiten de forma atómica al registrar el voto):
  1. El evento debe estar en estado 'votando'.
  2. El usuario debe tener votos disponibles (según votos_max_por_usuario del evento).
  3. El usuario no puede votar por sí mismo.
  4. El usuario no puede votar dos veces por la misma historia.

Multi-voto:
  - Los admins configuran el límite con /evento configurar_votos (1–10, default 1).
  - El menú excluye las historias por las que ya votó.

Límites de Discord: 25 opciones por menú y 5 menús por mensaje, así que se
muestran hasta 125 historias repartidas en varios menús.
"""

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
import database
from comun import en_servidores_configurados, md

OPCIONES_POR_MENU = 25
MAX_MENUS = 5
LIMITE_DESCRIPCION = 4096


def _embed_simple(descripcion: str, color: int) -> discord.Embed:
    embed = discord.Embed(description=descripcion, color=color)
    embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
    return embed


def _mensaje_resultado(resultado: str, votos_usados: int, votos_max: int) -> discord.Embed:
    """Construye el embed de respuesta tras intentar registrar un voto."""
    if resultado != database.VOTO_OK:
        motivos = {
            database.VOTO_DUPLICADO: "Ya habías votado por esta historia.",
            database.VOTO_LIMITE: "Ya usaste todos tus votos disponibles.",
            database.VOTO_CERRADO: "La votación ya no está abierta.",
            database.VOTO_INVALIDO: "Esa historia no es válida para tu voto.",
        }
        embed = discord.Embed(
            title="⚠️  Voto No Registrado",
            description=f"{config.SEPARADOR}\n\n{motivos.get(resultado, 'No se pudo registrar tu voto.')}\n\n{config.SEPARADOR}",
            color=config.COLOR_ADVERTENCIA,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        return embed

    restantes = votos_max - votos_usados
    if votos_max > 1:
        progreso = f"📊  **Voto {votos_usados} de {votos_max}** registrado.\n"
        if restantes > 0:
            progreso += (
                f"Te {'queda' if restantes == 1 else 'quedan'} **{restantes}** "
                f"voto{'s' if restantes != 1 else ''} disponible{'s' if restantes != 1 else ''}.\n"
                "Usa `/votar` de nuevo para emitir tu siguiente voto.\n\n"
            )
        else:
            progreso += "✅  ¡Has usado todos tus votos!\n¡Gracias por participar en el reto!\n\n"
    else:
        progreso = "¡Gracias por participar en el reto!\n\n"

    embed = discord.Embed(
        title="✅  ¡Voto Registrado!",
        description=f"{config.SEPARADOR}\n\nTu voto ha sido guardado de forma **anónima**.\n{progreso}{config.SEPARADOR}",
        color=config.COLOR_EXITO,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
    embed.set_footer(text="COMARCALIT  •  Tu voto es privado y definitivo")
    return embed


class VotoSelect(discord.ui.Select):
    """Menú desplegable con un bloque de hasta 25 historias."""

    def __init__(self, participantes: list, indice_inicial: int, total_menus: int):
        options = [
            discord.SelectOption(
                label=f"{indice_inicial + i}. {p['titulo_historia'] or 'Sin título'}"[:100],
                description=f"✍️ por {md(p['usuario_nombre'])}"[:100],
                value=str(p["id"]),
                emoji="📖",
            )
            for i, p in enumerate(participantes)
        ]
        if total_menus > 1:
            fin = indice_inicial + len(participantes) - 1
            placeholder = f"📚  Historias {indice_inicial}–{fin}..."
        else:
            placeholder = "📚  Selecciona la historia que quieres votar..."
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        view: "VotoView" = self.view  # type: ignore[assignment]
        await view.procesar_voto(interaction, int(self.values[0]))


class VotoView(discord.ui.View):
    """Vista con uno o varios menús de votación. Se desactiva tras un voto."""

    def __init__(self, db, evento_id: int, votos_max: int, participantes: list):
        super().__init__(timeout=300)
        self._db = db
        self.evento_id = evento_id
        self.votos_max = votos_max
        self.message: discord.InteractionMessage | None = None

        bloques = [
            participantes[i:i + OPCIONES_POR_MENU]
            for i in range(0, len(participantes), OPCIONES_POR_MENU)
        ][:MAX_MENUS]
        for n, bloque in enumerate(bloques):
            self.add_item(VotoSelect(bloque, n * OPCIONES_POR_MENU + 1, len(bloques)))

    async def procesar_voto(self, interaction: discord.Interaction, participante_id: int):
        user_id = str(interaction.user.id)
        # La habilitación se consulta en el momento del voto, no al abrir el menú
        es_valido = await database.esta_habilitado(self._db, self.evento_id, user_id)
        resultado = await database.registrar_voto(
            self._db, self.evento_id, user_id, participante_id, es_valido=es_valido
        )
        votos_usados = await database.contar_votos_usuario(self._db, self.evento_id, user_id)

        # Un menú = un voto: se retira para que no se reutilice con datos viejos
        self.stop()
        await interaction.response.edit_message(
            embed=_mensaje_resultado(resultado, votos_usados, self.votos_max), view=None
        )

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class Votacion(commands.Cog):
    """Cog para el sistema de votación."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    @app_commands.command(name="votar", description="Vota por tu historia favorita del evento activo")
    @en_servidores_configurados
    async def votar(self, interaction: discord.Interaction):
        activo = await database.obtener_evento_activo(self.db)

        if not activo or activo["estado"] != "votando":
            return await interaction.response.send_message(
                embed=_embed_simple(
                    "**⛔  Votación no disponible**\n\nLa votación no está abierta en este momento.",
                    config.COLOR_ERROR,
                ),
                ephemeral=True,
            )

        user_id = str(interaction.user.id)
        evento_id = activo["id"]
        votos_max = activo.get("votos_max_por_usuario", 1) or 1
        votos_usados = await database.contar_votos_usuario(self.db, evento_id, user_id)

        if votos_usados >= votos_max:
            if votos_max == 1:
                msg = "**⚠️  Ya votaste**\n\nYa registraste tu voto para este evento.\nNo puedes votar de nuevo."
            else:
                msg = (
                    "**⚠️  Votos agotados**\n\n"
                    f"Ya usaste tus **{votos_max} votos** disponibles para este evento.\n"
                    "No puedes votar de nuevo."
                )
            return await interaction.response.send_message(
                embed=_embed_simple(msg, config.COLOR_ADVERTENCIA), ephemeral=True
            )

        # Participantes elegibles: ni el propio votante ni historias ya votadas
        participantes = await database.obtener_participantes(self.db, evento_id)
        ya_votados = set(await database.obtener_votos_usuario_lista(self.db, evento_id, user_id))
        participantes = [
            p for p in participantes
            if p["usuario_discord_id"] != user_id and p["id"] not in ya_votados
        ]

        if not participantes:
            msg = (
                "**⚠️  Sin más historias**\n\nYa votaste por todas las historias disponibles."
                if votos_usados > 0 else
                "**⚠️  Sin candidatos**\n\nNo hay historias disponibles para votar."
            )
            return await interaction.response.send_message(
                embed=_embed_simple(msg, config.COLOR_ADVERTENCIA), ephemeral=True
            )

        limite_menus = OPCIONES_POR_MENU * MAX_MENUS
        omitidas = max(0, len(participantes) - limite_menus)
        participantes = participantes[:limite_menus]

        if votos_max > 1:
            restantes = votos_max - votos_usados
            info_votos = (
                f"\n\n🗳️  **Voto {votos_usados + 1} de {votos_max}**  •  "
                f"Te {'queda' if restantes == 1 else 'quedan'} {restantes} voto{'s' if restantes != 1 else ''}"
            )
        else:
            info_votos = ""

        cabecera = (
            f"{config.SEPARADOR}\n\n"
            f"📖  **{md(activo['nombre'])}**\n\n"
            "Selecciona la historia que más te gustó\n"
            "en el menú desplegable de abajo.\n\n"
            f"{config.SEPARADOR_CORTO}\n\n"
        )
        pie = f"{info_votos}\n\n{config.SEPARADOR}"

        # La lista se recorta para no pasar el límite de 4096 caracteres del embed
        lineas: list[str] = []
        presupuesto = LIMITE_DESCRIPCION - len(cabecera) - len(pie) - 40
        for i, p in enumerate(participantes, 1):
            linea = f"`{i}.`  **{p['titulo_historia'] or 'Sin título'}**  —  *{md(p['usuario_nombre'])}*"
            if sum(len(x) + 1 for x in lineas) + len(linea) > presupuesto:
                lineas.append(f"*... y {len(participantes) - i + 1} más (ver menús)*")
                break
            lineas.append(linea)

        embed = discord.Embed(
            title="🗳️  Votación",
            description=cabecera + "\n".join(lineas) + pie,
            color=config.COLOR_VOTACION,
            timestamp=datetime.now(timezone.utc),
        )
        if votos_max > 1:
            embed.add_field(
                name="ℹ️  Multi-voto",
                value=f"Puedes votar por hasta **{votos_max} historias diferentes**. Usa `/votar` una vez por cada voto.",
                inline=False,
            )
        if omitidas:
            embed.add_field(
                name="ℹ️  Demasiadas historias",
                value=f"Discord solo permite mostrar {limite_menus} opciones; {omitidas} no aparecen en el menú.",
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

        view = VotoView(self.db, evento_id, votos_max, participantes)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(Votacion(bot))
