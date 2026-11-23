"""
cogs/historial.py — Consulta de eventos pasados y vista de participantes.

Comandos:
  /reto info      — Muestra el evento activo con navegación interactiva de participantes.
  /reto historial — Lista eventos cerrados. Al seleccionar uno, muestra detalles.
"""

from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

import config
import database
import personalidad as ribby
from comun import (
    en_servidores_configurados,
    es_admin,
    fecha_corta,
    refrescar_participantes,
    refrescar_urls,
)


BASE_DIR = Path(__file__).resolve().parent.parent
MANUAL_USUARIO_PATH = BASE_DIR / "MANUAL_DE_USUARIO.md"
MANUAL_ADMIN_PATH = BASE_DIR / "MANUAL_ADMINISTRADORES.md"


# ─────────────────────────── Constantes visuales ───────────────────────────

ESTADOS_VISUAL = {
    "abierto": ("🟢", "Abierto", "Recibiendo inscripciones", config.COLOR_EXITO),
    "narrando": ("🔴", "En Vivo", "Sesión de narración activa", config.COLOR_NARRACION),
    "votando": ("🗳️", "Votando", "Votación abierta", config.COLOR_VOTACION),
    "cerrado": ("🔒", "Cerrado", "Evento finalizado", config.COLOR_INFO),
}


# ─────────────────────────── Helpers para embeds ───────────────────────────

def _embed_resumen_evento(activo: dict, total_participantes: int) -> discord.Embed:
    """Genera el embed de resumen general del evento."""
    emoji, label, desc, color = ESTADOS_VISUAL.get(
        activo["estado"], ("❓", activo["estado"], "", config.COLOR_PRINCIPAL)
    )
    nombre = activo["nombre"][:240]

    embed = discord.Embed(
        title=f"📖  {nombre}",
        description=(
            f"{config.SEPARADOR}\n\n"
            f"{emoji}  **{label}**  —  {desc}\n\n"
            f"{config.SEPARADOR}"
        ),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="🆔  ID", value=f"```{activo['id']}```", inline=True)
    embed.add_field(name="👥  Participantes", value=f"```{total_participantes}```", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    if total_participantes > 0:
        embed.add_field(
            name="📌  Navegación",
            value="Usa los botones de abajo para explorar las historias en mi biblioteca~",
            inline=False,
        )
    else:
        embed.add_field(
            name="📚  Historias",
            value=(
                "*Mi estante está vacío por ahora...*\n\n"
                "¡Usa `/participante_registrar` para inscribirte y traer un libro nuevo!"
            ),
            inline=False,
        )

    embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
    embed.set_footer(text=ribby.tip_aleatorio())
    return embed


def _embed_participante(p: dict, idx: int, total: int, evento_nombre: str) -> discord.Embed:
    """Genera el embed de un participante individual con portada arriba."""
    titulo = p["titulo_historia"] or "Sin título"
    color = config.COLOR_PRINCIPAL

    embed = discord.Embed(color=color, timestamp=datetime.now(timezone.utc))

    # ── Portada como imagen principal (arriba del contenido) ──
    if p["url_portada"]:
        embed.set_image(url=p["url_portada"])

    # ── Título y contenido ──
    desc_partes = [
        f"## ✍️  {titulo}",
        f"{config.SEPARADOR}",
        "",
    ]

    # Info del autor
    desc_partes.append(f"👤  **Autor:**  {p['usuario_nombre']}")

    # Fecha de registro
    if p.get("fecha_registro"):
        desc_partes.append(f"📅  **Registrado:**  {fecha_corta(p['fecha_registro'])}")

    # Evento
    desc_partes.append(f"📖  **Evento:**  {evento_nombre[:100]}")

    desc_partes.append("")

    # Link de descarga
    if p["url_pdf"]:
        desc_partes.append("📄  **Documento:**  ✅ Subido *(Usa el botón de abajo)*")
    else:
        desc_partes.append("📄  **Documento:**  *Pendiente de subir*")

    if p["url_portada"]:
        desc_partes.append(f"🖼️  **Portada:**  ✅ Subida")
    else:
        desc_partes.append("🖼️  **Portada:**  *Pendiente de subir*")

    desc_partes.append("")
    desc_partes.append(f"{config.SEPARADOR}")

    embed.description = "\n".join(desc_partes)

    embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
    embed.set_footer(text=f"📚 Libro {idx + 1} de {total} en mi estante  •  Usa ◀ ▶ para navegar")

    return embed


def _particionar_lineas_embed(lineas: list[str], limite: int = 1024) -> list[str]:
    """Agrupa líneas para que cada bloque pueda ir en un campo de embed."""
    bloques: list[str] = []
    bloque_actual: list[str] = []
    longitud_actual = 0

    for linea in lineas:
        separador = 1 if bloque_actual else 0
        longitud_linea = len(linea)

        if bloque_actual and longitud_actual + separador + longitud_linea > limite:
            bloques.append("\n".join(bloque_actual))
            bloque_actual = [linea]
            longitud_actual = longitud_linea
            continue

        bloque_actual.append(linea)
        longitud_actual += separador + longitud_linea

    if bloque_actual:
        bloques.append("\n".join(bloque_actual))

    return bloques or ["N/A"]


def _limitar_campos_embed(campos: list[tuple[str, str, bool]], limite: int) -> list[tuple[str, str, bool]]:
    """Recorta campos para que la suma de sus textos no exceda un presupuesto."""
    seleccionados: list[tuple[str, str, bool]] = []
    usado = 0

    for nombre, valor, inline in campos:
        costo = len(nombre) + len(valor)
        if usado + costo > limite:
            restantes = len(campos) - len(seleccionados)
            if restantes > 0:
                aviso = f"... y {restantes} bloque{'s' if restantes != 1 else ''} más"
                nombre_aviso = "📚  Historias"
                if usado + len(nombre_aviso) + len(aviso) <= limite:
                    seleccionados.append((nombre_aviso, aviso, False))
            break

        seleccionados.append((nombre, valor, inline))
        usado += costo

    return seleccionados


# ─────────────────────────── Vista interactiva /reto info ───────────────────────────

class _VistaConTimeout(discord.ui.View):
    """Vista que desactiva sus componentes en el mensaje cuando expira."""

    message: discord.Message | discord.InteractionMessage | None = None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class InfoPaginadaView(_VistaConTimeout):
    """
    Vista con botones para navegar entre resumen y participantes.

    El mensaje de /reto info es público: si otra persona pulsa un botón, en
    lugar de cambiarle la página a todos se le abre su propia copia privada.
    """

    def __init__(self, db, evento: dict, participantes: list, owner_id: int, pagina: int = -1, timeout: float = 180):
        super().__init__(timeout=timeout)
        self._db = db
        self.evento = evento
        self.participantes = participantes
        self.owner_id = owner_id
        self.total = len(participantes)
        self.pagina = max(-1, min(pagina, self.total - 1))  # -1 = resumen, 0..N-1 = participantes
        self._actualizar_botones()

    def _actualizar_botones(self):
        """Habilita/deshabilita botones según la página actual."""
        self.btn_primero.disabled = self.pagina <= -1
        self.btn_anterior.disabled = self.pagina <= -1
        self.btn_pagina.label = "📋 Resumen" if self.pagina == -1 else f"{self.pagina + 1} / {self.total}"
        self.btn_siguiente.disabled = self.total == 0 or self.pagina >= self.total - 1
        self.btn_ultimo.disabled = self.total == 0 or self.pagina >= self.total - 1
        self.btn_descargar.disabled = self.pagina == -1 or not self.participantes[self.pagina]["url_pdf"]

    def _get_embed(self) -> discord.Embed:
        if self.pagina == -1:
            return _embed_resumen_evento(self.evento, self.total)
        p = self.participantes[self.pagina]
        return _embed_participante(p, self.pagina, self.total, self.evento["nombre"])

    async def _ir_a(self, interaction: discord.Interaction, pagina: int):
        if interaction.user.id != self.owner_id:
            copia = InfoPaginadaView(self._db, self.evento, self.participantes, interaction.user.id, pagina)
            await interaction.response.send_message(embed=copia._get_embed(), view=copia, ephemeral=True)
            copia.message = await interaction.original_response()
            return
        self.pagina = max(-1, min(pagina, self.total - 1))
        self._actualizar_botones()
        await interaction.response.edit_message(embed=self._get_embed(), view=self)

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.secondary)
    async def btn_primero(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._ir_a(interaction, -1)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.primary)
    async def btn_anterior(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._ir_a(interaction, self.pagina - 1)

    @discord.ui.button(label="📋 Resumen", style=discord.ButtonStyle.secondary, disabled=True)
    async def btn_pagina(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()  # Solo indicador

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary)
    async def btn_siguiente(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._ir_a(interaction, self.pagina + 1)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary)
    async def btn_ultimo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._ir_a(interaction, self.total - 1)

    @discord.ui.button(label="📥 Descargar Documento", style=discord.ButtonStyle.success)
    async def btn_descargar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.pagina == -1:
            return await interaction.response.defer()

        p = self.participantes[self.pagina]
        if not p["url_pdf"]:
            return await interaction.response.send_message(
                "Este participante aún no ha subido su documento.", ephemeral=True
            )

        await database.registrar_descarga(self._db, self.evento["id"], str(interaction.user.id), p["id"])

        # Enlace vigente: las URLs del CDN de Discord caducan
        url = (await refrescar_urls(interaction.client, [p["url_pdf"]])).get(p["url_pdf"], p["url_pdf"])

        titulo = p["titulo_historia"] or "Sin título"
        embed = discord.Embed(
            title="📥  Documento Listo",
            description=(
                f"Aquí tienes la historia _{titulo}_ de **{p['usuario_nombre']}**:\n\n"
                f"[⬇️  **Haz clic aquí para descargar**]({url})"
            ),
            color=config.COLOR_EXITO,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ─────────────────────────── Historial Select ───────────────────────────

class HistorialSelect(discord.ui.Select):
    """Menú desplegable para elegir un evento del historial."""

    def __init__(self, eventos: list, db):
        self._db = db
        options = []
        for e in eventos[:25]:  # Discord limita a 25 opciones
            label = e["nombre"][:100]
            fecha = fecha_corta(e["fecha_cierre"])
            options.append(
                discord.SelectOption(
                    label=label,
                    description=f"📅 Cerrado: {fecha}",
                    value=str(e["id"]),
                    emoji="📖",
                )
            )

        super().__init__(
            placeholder="📚  Selecciona un evento para ver sus detalles...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        evento_id = int(self.values[0])
        evento = await database.obtener_evento_por_id(self._db, evento_id)
        if not evento:
            return await interaction.response.send_message("Ese evento ya no existe.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        participantes = await refrescar_participantes(
            interaction.client, await database.obtener_participantes(self._db, evento_id)
        )
        resultados = await database.obtener_resultados_votacion(self._db, evento_id)

        nombre_corto = evento['nombre'][:240]
        embed = discord.Embed(
            title=f"📖  {nombre_corto}",
            description=config.SEPARADOR,
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )

        fecha_creacion = fecha_corta(evento["fecha_creacion"])
        fecha_cierre = fecha_corta(evento["fecha_cierre"])
        duracion = evento.get("duracion_narracion_minutos", 0) or 0

        embed.add_field(
            name="📅  Periodo",
            value=f"```Inicio:  {fecha_creacion}\nCierre:  {fecha_cierre}```",
            inline=True,
        )
        embed.add_field(
            name="📊  Estadísticas",
            value=f"```Participantes:  {len(participantes)}\nDuración:       {duracion:.0f} min```",
            inline=True,
        )

        if resultados and resultados[0]["total_votos"] > 0:
            ganador = resultados[0]
            titulo_ganador = ganador["titulo_historia"] or "Sin título"
            embed.add_field(
                name="🏆  Ganador",
                value=(
                    f"**{ganador['usuario_nombre']}**\n"
                    f"╰ _{titulo_ganador}_  •  **{ganador['total_votos']}** voto(s)"
                ),
                inline=False,
            )

        # Lista de participantes con sus historias
        if participantes:
            lineas = []
            for i, p in enumerate(participantes, 1):
                titulo = p["titulo_historia"] or "Sin título"
                linea = f"`{i}.`  **{p['usuario_nombre']}**  —  _{titulo}_"
                links = []
                if p["url_pdf"]:
                    links.append(f"[📄 Doc]({p['url_pdf']})")
                if p["url_portada"]:
                    links.append(f"[🖼️ Portada]({p['url_portada']})")
                if links:
                    linea += "  " + "  •  ".join(links)
                lineas.append(linea)

            bloques = _particionar_lineas_embed(lineas)
            campos_historia = []
            if len(bloques) == 1:
                campos_historia.append(("📚  Historias", bloques[0], False))
            else:
                total_bloques = len(bloques)
                for i, bloque in enumerate(bloques, 1):
                    campos_historia.append((f"📚  Historias ({i}/{total_bloques})", bloque, False))

            presupuesto_total = 5400
            presupuesto_restante = max(0, presupuesto_total - len(embed.title or "") - len(embed.description or ""))
            campos_historia = _limitar_campos_embed(campos_historia, presupuesto_restante)
            for nombre, valor, inline in campos_historia:
                embed.add_field(name=nombre, value=valor, inline=inline)

        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        embed.set_footer(text="COMARCALIT  •  Retos Literarios  •  Archivo Histórico")

        await interaction.followup.send(embed=embed, ephemeral=True)


class HistorialView(_VistaConTimeout):
    def __init__(self, eventos: list, db):
        super().__init__(timeout=120)
        self.add_item(HistorialSelect(eventos, db))


class ManualPaginadoView(_VistaConTimeout):
    def __init__(self, embeds: list[discord.Embed]):
        super().__init__(timeout=300)
        self.embeds = embeds
        self.current_page = 0
        self._actualizar_botones()

    def _actualizar_botones(self):
        is_first = self.current_page == 0
        is_last = self.current_page == len(self.embeds) - 1
        self.btn_first.disabled = is_first
        self.btn_prev.disabled = is_first
        self.btn_next.disabled = is_last
        self.btn_last.disabled = is_last

    @discord.ui.button(label="⏮️ Principio", style=discord.ButtonStyle.secondary)
    async def btn_first(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self._actualizar_botones()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="◀ Anterior", style=discord.ButtonStyle.primary)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self._actualizar_botones()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Siguiente ▶", style=discord.ButtonStyle.primary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self._actualizar_botones()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Final ⏭️", style=discord.ButtonStyle.secondary)
    async def btn_last(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = len(self.embeds) - 1
        self._actualizar_botones()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)


# ─────────────────────────── Cog principal ───────────────────────────

class Historial(commands.Cog):
    """Cog para consulta de eventos activos y pasados."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    reto_group = app_commands.Group(
        name="reto",
        description="Información sobre los retos literarios",
        guild_ids=config.GUILD_IDS if config.GUILD_IDS else None,
    )

    # ── /reto info ──

    @reto_group.command(name="info", description="Muestra información del evento activo")
    async def info(self, interaction: discord.Interaction):
        activo = await database.obtener_evento_activo(self.db)
        if not activo:
            embed = discord.Embed(
                description="**ℹ️  Sin evento activo**\n\nNo hay ningún evento activo en este momento.",
                color=config.COLOR_INFO,
            )
            embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.defer()
        participantes = await refrescar_participantes(
            self.bot, await database.obtener_participantes(self.db, activo["id"])
        )

        view = InfoPaginadaView(self.db, activo, participantes, owner_id=interaction.user.id)
        view.message = await interaction.followup.send(
            embed=_embed_resumen_evento(activo, len(participantes)), view=view, wait=True
        )

    # ── /reto historial ──

    @reto_group.command(name="historial", description="Muestra los eventos pasados")
    async def historial(self, interaction: discord.Interaction):
        eventos = await database.obtener_ultimos_eventos(self.db)

        if not eventos:
            embed = discord.Embed(
                description="**ℹ️  Sin historial**\n\nNo hay eventos pasados registrados.",
                color=config.COLOR_INFO,
            )
            embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # Mini resumen de eventos
        resumen_lineas = []
        for i, e in enumerate(eventos[:10], 1):
            fecha = fecha_corta(e["fecha_cierre"])
            resumen_lineas.append(f"`{i}.`  **{e['nombre'][:80]}**  •  📅 {fecha}")

        embed = discord.Embed(
            title="📜  Historial de Retos Literarios",
            description=(
                f"{config.SEPARADOR}\n\n"
                f"Se encontraron **{len(eventos)}** evento(s) pasado(s).\n"
                f"Selecciona uno del menú para ver sus detalles.\n\n"
                f"{config.SEPARADOR_CORTO}\n\n"
                + "\n".join(resumen_lineas)
                + f"\n\n{config.SEPARADOR}"
            ),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        embed.set_footer(text="COMARCALIT  •  Retos Literarios  •  Archivo Histórico")

        view = HistorialView(eventos, self.db)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


    # ── /help ──

    @app_commands.command(name="help", description="Muestra el manual de usuario completo de Ribby")
    @en_servidores_configurados
    async def help_command(self, interaction: discord.Interaction):
        await self._enviar_manual(
            interaction,
            MANUAL_USUARIO_PATH,
            autor="Ribby 🎀 • Manual de Usuario",
            pie="COMARCALIT",
            color=config.COLOR_PRINCIPAL,
            privado=False,
        )

    # ── /admin_help ──

    @app_commands.command(name="admin_help", description="Muestra el manual de administradores de Ribby (solo Staff)")
    @en_servidores_configurados
    async def admin_help_command(self, interaction: discord.Interaction):
        if not es_admin(interaction):
            embed = discord.Embed(
                description="**⛔  Sin permisos**\n\nEste manual es clasificado y solo para líderes de La Comarca.",
                color=config.COLOR_ERROR,
            )
            embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # Siempre privado: el manual describe el sistema antifraude
        await self._enviar_manual(
            interaction,
            MANUAL_ADMIN_PATH,
            autor="🔒 Admin • Manual de Secretos",
            pie="COMARCALIT (Confidencial)",
            color=0x4B5563,
            privado=True,
        )

    @staticmethod
    async def _enviar_manual(
        interaction: discord.Interaction,
        ruta: Path,
        autor: str,
        pie: str,
        color: int,
        privado: bool,
    ) -> None:
        try:
            contenido = ruta.read_text(encoding="utf-8")
        except FileNotFoundError:
            return await interaction.response.send_message(f"❌ No se encontró el archivo `{ruta.name}`.", ephemeral=True)

        # Separar el manual por las líneas horizontales ---
        secciones = [sec.strip() for sec in contenido.split("\n---") if sec.strip()]
        if not secciones:
            return await interaction.response.send_message("❌ El manual está vacío.", ephemeral=True)

        embeds = []
        for i, seccion in enumerate(secciones, 1):
            embed = discord.Embed(description=seccion[:4096], color=color, timestamp=datetime.now(timezone.utc))
            embed.set_author(name=autor, icon_url=config.BOT_ICON_URL or None)
            embed.set_footer(text=f"Página {i} de {len(secciones)}  •  {pie}")
            embeds.append(embed)

        view = ManualPaginadoView(embeds)
        await interaction.response.send_message(embed=embeds[0], view=view, ephemeral=privado)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(Historial(bot))
