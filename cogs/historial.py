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
        fecha = p["fecha_registro"][:10]
        desc_partes.append(f"📅  **Registrado:**  {fecha}")

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

class InfoPaginadaView(discord.ui.View):
    """Vista con botones para navegar entre resumen y participantes."""

    def __init__(self, db, evento: dict, participantes: list, timeout: float = 180):
        super().__init__(timeout=timeout)
        self._db = db
        self.evento = evento
        self.participantes = participantes
        self.pagina = -1  # -1 = resumen, 0..N = participantes
        self.total = len(participantes)
        self._actualizar_botones()

    def _actualizar_botones(self):
        """Habilita/deshabilita botones según la página actual."""
        # Primera (retroceder al inicio)
        self.btn_primero.disabled = (self.pagina <= -1)
        # Anterior
        self.btn_anterior.disabled = (self.pagina <= -1)
        # Indicador de página (no interactivo)
        if self.pagina == -1:
            self.btn_pagina.label = "📋 Resumen"
        else:
            self.btn_pagina.label = f"{self.pagina + 1} / {self.total}"
        # Siguiente
        self.btn_siguiente.disabled = (self.pagina >= self.total - 1) or (self.total == 0)
        # Último
        self.btn_ultimo.disabled = (self.pagina >= self.total - 1) or (self.total == 0)
        # Descargar Documento
        if self.pagina == -1:
            self.btn_descargar.disabled = True
        else:
            self.btn_descargar.disabled = not bool(self.participantes[self.pagina]["url_pdf"])

    def _get_embed(self) -> discord.Embed:
        """Retorna el embed correcto para la página actual."""
        if self.pagina == -1:
            return _embed_resumen_evento(self.evento, self.total)
        else:
            p = self.participantes[self.pagina]
            return _embed_participante(p, self.pagina, self.total, self.evento["nombre"])

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.secondary, custom_id="info_primero")
    async def btn_primero(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.pagina = -1
        self._actualizar_botones()
        await interaction.response.edit_message(embed=self._get_embed(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.primary, custom_id="info_anterior")
    async def btn_anterior(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.pagina = max(-1, self.pagina - 1)
        self._actualizar_botones()
        await interaction.response.edit_message(embed=self._get_embed(), view=self)

    @discord.ui.button(label="📋 Resumen", style=discord.ButtonStyle.secondary, disabled=True, custom_id="info_pagina")
    async def btn_pagina(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Botón no interactivo, solo indicador
        await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary, custom_id="info_siguiente")
    async def btn_siguiente(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.pagina = min(self.total - 1, self.pagina + 1)
        self._actualizar_botones()
        await interaction.response.edit_message(embed=self._get_embed(), view=self)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary, custom_id="info_ultimo")
    async def btn_ultimo(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.pagina = self.total - 1
        self._actualizar_botones()
        await interaction.response.edit_message(embed=self._get_embed(), view=self)

    @discord.ui.button(label="📥 Descargar Documento", style=discord.ButtonStyle.success, custom_id="info_descargar")
    async def btn_descargar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.pagina == -1:
            return await interaction.response.defer()

        p = self.participantes[self.pagina]
        if not p["url_pdf"]:
            return await interaction.response.send_message(
                "Este participante aún no ha subido su documento.", ephemeral=True
            )

        # Registrar descarga en la base de datos
        await database.registrar_descarga(
            self._db, self.evento["id"], str(interaction.user.id), p["id"]
        )

        titulo = p["titulo_historia"] or "Sin título"
        embed = discord.Embed(
            title="📥  Documento Listo",
            description=f"Aquí tienes la historia _{titulo}_ de **{p['usuario_nombre']}**:\n\n[⬇️  **Haz clic aquí para descargar**]({p['url_pdf']})",
            color=config.COLOR_EXITO
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_timeout(self):
        """Deshabilita todos los botones cuando expira el tiempo."""
        for child in self.children:
            child.disabled = True


# ─────────────────────────── Historial Select ───────────────────────────

class HistorialSelect(discord.ui.Select):
    """Menú desplegable para elegir un evento del historial."""

    def __init__(self, eventos: list, db):
        self._db = db
        options = []
        for e in eventos[:25]:  # Discord limita a 25 opciones
            label = e["nombre"][:100]
            fecha = e["fecha_cierre"][:10] if e["fecha_cierre"] else "N/A"
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
        participantes = await database.obtener_participantes(self._db, evento_id)
        resultados = await database.obtener_resultados_votacion(self._db, evento_id)

        nombre_corto = evento['nombre'][:240]
        embed = discord.Embed(
            title=f"📖  {nombre_corto}",
            description=config.SEPARADOR,
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc),
        )

        fecha_creacion = evento["fecha_creacion"][:10] if evento["fecha_creacion"] else "N/A"
        fecha_cierre = evento["fecha_cierre"][:10] if evento["fecha_cierre"] else "N/A"
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

        await interaction.response.send_message(embed=embed, ephemeral=True)


class HistorialView(discord.ui.View):
    def __init__(self, eventos: list, db):
        super().__init__(timeout=120)
        self.add_item(HistorialSelect(eventos, db))


class ManualPaginadoView(discord.ui.View):
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

    @discord.ui.button(label="⏮️ Principio", style=discord.ButtonStyle.secondary, custom_id="manual_first")
    async def btn_first(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self._actualizar_botones()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="◀ Anterior", style=discord.ButtonStyle.primary, custom_id="manual_prev")
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self._actualizar_botones()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Siguiente ▶", style=discord.ButtonStyle.primary, custom_id="manual_next")
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self._actualizar_botones()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Final ⏭️", style=discord.ButtonStyle.secondary, custom_id="manual_last")
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

        participantes = await database.obtener_participantes(self.db, activo["id"])

        # Crear vista paginada
        view = InfoPaginadaView(self.db, activo, participantes)
        embed = _embed_resumen_evento(activo, len(participantes))

        await interaction.response.send_message(embed=embed, view=view)

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
            fecha = e["fecha_cierre"][:10] if e["fecha_cierre"] else "N/A"
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


    # ── /help ──

    @app_commands.command(name="help", description="Muestra el manual de usuario completo de Ribby")
    @app_commands.guilds(*config.GUILD_IDS)
    async def help_command(self, interaction: discord.Interaction):
        try:
            with MANUAL_USUARIO_PATH.open("r", encoding="utf-8") as f:
                contenido = f.read()
        except FileNotFoundError:
            return await interaction.response.send_message(
                "❌ No se encontró el archivo `MANUAL_DE_USUARIO.md`.", ephemeral=True
            )

        # Separar el manual por las etiquetas horizontales ---
        secciones = [s.strip() for s in contenido.split("\n---")]
        
        embeds = []
        for i, seccion in enumerate(secciones):
            if not seccion:
                continue
            
            embed = discord.Embed(
                description=seccion[:4096],  # Límite de discord
                color=config.COLOR_PRINCIPAL,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_author(name="Ribby 🎀 • Manual de Usuario", icon_url=config.BOT_ICON_URL or None)
            embed.set_footer(text=f"Página {i + 1} de {len(secciones)}  •  COMARCALIT")
            embeds.append(embed)

        if not embeds:
            return await interaction.response.send_message("❌ El manual está vacío.", ephemeral=True)

        view = ManualPaginadoView(embeds)
        await interaction.response.send_message(embed=embeds[0], view=view)


    # ── /admin_help ──

    @app_commands.command(name="admin_help", description="Muestra el manual de administradores de Ribby (solo Staff)")
    @app_commands.guilds(*config.GUILD_IDS)
    async def admin_help_command(self, interaction: discord.Interaction):
        # Verificar rol de admin
        es_admin = any(role.name == config.ADMIN_ROLE_NAME for role in interaction.user.roles)
        if not es_admin:
            embed = discord.Embed(
                description="**⛔  Sin permisos**\n\nEste manual es clasificado y solo para líderes de La Comarca.",
                color=config.COLOR_ERROR,
            )
            embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        try:
            with MANUAL_ADMIN_PATH.open("r", encoding="utf-8") as f:
                contenido = f.read()
        except FileNotFoundError:
            return await interaction.response.send_message(
                "❌ No se encontró el archivo `MANUAL_ADMINISTRADORES.md`.", ephemeral=True
            )

        secciones = [s.strip() for s in contenido.split("\n---")]
        
        embeds = []
        for i, seccion in enumerate(secciones):
            if not seccion:
                continue
            
            embed = discord.Embed(
                description=seccion[:4096],
                color=0x4B5563,  # Color más oscuro para admin
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_author(name="🔒 Admin • Manual de Secretos", icon_url=config.BOT_ICON_URL or None)
            embed.set_footer(text=f"Página {i + 1} de {len(secciones)}  •  COMARCALIT (Confidencial)")
            embeds.append(embed)

        if not embeds:
            return await interaction.response.send_message("❌ El manual está vacío.", ephemeral=True)

        view = ManualPaginadoView(embeds)
        # Mostrarlo públicamente en el canal temporalmente, como solicitó el usuario
        await interaction.response.send_message(embed=embeds[0], view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Historial(bot))
