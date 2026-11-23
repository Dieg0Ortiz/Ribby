"""
comun.py — Utilidades compartidas por los cogs.

- Verificación de permisos de administrador.
- Decorador para registrar comandos en los servidores configurados.
- Refresco de URLs firmadas del CDN de Discord (caducan ~24 h).
- Helpers de formato para fechas y campos de embeds.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from datetime import datetime
from typing import Any, Iterable, Optional

import discord
from discord import app_commands

import config

log = logging.getLogger("bot-literario.comun")


# ─────────────────────────── Modo de pruebas ───────────────────────────
#
# Con /prueba activar, el modo de pruebas es GLOBAL: todo lo que haga cualquier
# usuario (y las tareas automáticas) va al esquema "pruebas" de la base de datos
# hasta que alguien use /prueba desactivar. Además, en los servidores de pruebas
# (config.GUILDS_PRUEBAS) todo usa siempre la base de pruebas.
# Cada interacción marca en ContextVars quién la provoca y en qué servidor.

_usuario_actual: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("ribby_usuario", default=None)
_servidor_actual: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("ribby_servidor", default=None)
_forzar_real: contextvars.ContextVar[bool] = contextvars.ContextVar("ribby_forzar_real", default=False)
_modo_global = False
eventos_forzados: dict[int, str] = {}  # usuario → id de evento de temporada (solo en pruebas)


def activar_modo_global(activo: bool) -> None:
    global _modo_global
    _modo_global = activo


def modo_global() -> bool:
    return _modo_global


def marcar_usuario(usuario: Any, servidor_id: Optional[int] = None) -> None:
    """
    Indica quién provoca lo que se está ejecutando ahora y en qué servidor (y por
    tanto qué base de datos usar). Acepta un usuario de Discord o un ID.
    """
    if usuario is not None and not isinstance(usuario, int):
        es_creador(usuario)  # Recuerda el ID del creador si se le reconoce por su nombre
        if servidor_id is None and getattr(usuario, "guild", None) is not None:
            servidor_id = usuario.guild.id
        usuario = usuario.id
    _usuario_actual.set(usuario)
    _servidor_actual.set(servidor_id)


def usuario_actual() -> Optional[int]:
    return _usuario_actual.get()


def en_prueba(usuario_id: Optional[int] = None) -> bool:
    """
    ¿Lo que se ejecuta ahora va a la base de pruebas? Sí si el modo de pruebas
    global está activado o si estamos en un servidor de pruebas.
    (`usuario_id` se acepta por compatibilidad; el modo ya no es por usuario.)
    """
    if _forzar_real.get():
        return False
    return _modo_global or _servidor_actual.get() in config.GUILDS_PRUEBAS


@contextlib.contextmanager
def contexto_real():
    """Dentro de este bloque las consultas van siempre a la base de datos real."""
    token = _forzar_real.set(True)
    try:
        yield
    finally:
        _forzar_real.reset(token)


def instalar_contexto(bot: discord.Client) -> None:
    """Engancha comandos, botones, menús y formularios para marcar al usuario de cada interacción."""
    async def check_arbol(interaction: discord.Interaction) -> bool:
        marcar_usuario(interaction.user, interaction.guild_id)
        return True

    bot.tree.interaction_check = check_arbol  # type: ignore[method-assign]

    for clase in (discord.ui.Item, discord.ui.Modal):
        original = clase.interaction_check

        async def check(self, interaction: discord.Interaction, _original=original) -> bool:
            marcar_usuario(interaction.user, interaction.guild_id)
            return await _original(self, interaction)

        clase.interaction_check = check  # type: ignore[method-assign]


# ─────────────────────────── El creador de Ribby ───────────────────────────

# Tainy: Ribby le ve como su padre/creador. Se reconoce por ID (CREADOR_DISCORD_ID)
# o, si no está configurado, por su nombre de usuario de Discord.
CREADOR_USUARIOS = {"peso_pluma__."}
_creadores: set[int] = set(config.CREADOR_IDS)


def es_creador(usuario: Any) -> bool:
    if usuario is None:
        return False
    if getattr(usuario, "id", None) in _creadores:
        return True
    if str(getattr(usuario, "name", "")).lower() in CREADOR_USUARIOS:
        _creadores.add(usuario.id)  # Se recuerda el ID para tareas que solo conocen el número
        return True
    return False


def es_creador_id(usuario_id: Any) -> bool:
    try:
        return int(usuario_id) in _creadores
    except (TypeError, ValueError):
        return False


def creador_activo(usuario_id: Any) -> bool:
    """El creador cuenta como tal salvo en modo de pruebas (ahí puede probar todo como un usuario normal)."""
    return es_creador_id(usuario_id) and not en_prueba(int(usuario_id))


# ─────────────────────────── Permisos ───────────────────────────

def es_admin(interaction: discord.Interaction) -> bool:
    """True si quien usa el comando tiene el rol de administrador literario.

    Fuera de un servidor (DM) `interaction.user` es un `User` sin roles,
    así que se rechaza en lugar de lanzar AttributeError.
    """
    return es_admin_miembro(interaction.user)


def es_admin_miembro(usuario: Any) -> bool:
    """Igual que es_admin, pero para el autor de un mensaje."""
    if not isinstance(usuario, discord.Member):
        return False
    return any(role.name == config.ADMIN_ROLE_NAME for role in usuario.roles)


def en_servidores_configurados(func):
    """Registra el comando en GUILD_IDS si están definidos; si no, queda global."""
    if config.GUILD_IDS:
        return app_commands.guilds(*config.GUILD_IDS)(func)
    return func


# ─────────────────────────── CDN de Discord ───────────────────────────

_HOSTS_CDN = ("cdn.discordapp.com", "media.discordapp.net")
_LOTE_REFRESCO = 50  # Límite de URLs por petición en la API de Discord


def _es_url_cdn(url: Optional[str]) -> bool:
    return bool(url) and any(h in url for h in _HOSTS_CDN)  # type: ignore[operator]


async def refrescar_urls(bot: discord.Client, urls: Iterable[Optional[str]]) -> dict[str, str]:
    """
    Devuelve {url_original: url_vigente} para las URLs del CDN de Discord.

    Desde 2024 los enlaces de adjuntos van firmados y caducan, así que una URL
    guardada en la base de datos deja de funcionar al cabo de un día. Este
    endpoint devuelve una versión vigente del mismo archivo. Si falla, se
    devuelven las URLs originales para no romper nada.
    """
    pendientes = list(dict.fromkeys(u for u in urls if _es_url_cdn(u)))
    resultado: dict[str, str] = {u: u for u in pendientes}  # type: ignore[misc]

    for i in range(0, len(pendientes), _LOTE_REFRESCO):
        lote = pendientes[i:i + _LOTE_REFRESCO]
        try:
            data = await bot.http.request(
                discord.http.Route("POST", "/attachments/refresh-urls"),
                json={"attachment_urls": lote},
            )
            for item in data.get("refreshed_urls", []):
                original, nueva = item.get("original"), item.get("refreshed")
                if original and nueva:
                    resultado[original] = nueva
        except Exception as e:  # noqa: BLE001 — degradar con elegancia
            log.warning(f"No se pudieron refrescar {len(lote)} URL(s) del CDN: {e}")

    return resultado


async def refrescar_participantes(bot: discord.Client, participantes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Devuelve copias de los participantes con url_pdf/url_portada vigentes."""
    urls = [p.get("url_pdf") for p in participantes] + [p.get("url_portada") for p in participantes]
    mapa = await refrescar_urls(bot, urls)
    copia = []
    for p in participantes:
        q = dict(p)
        for campo in ("url_pdf", "url_portada"):
            if q.get(campo):
                q[campo] = mapa.get(q[campo], q[campo])
        copia.append(q)
    return copia


# ─────────────────────────── Formato ───────────────────────────

def md(texto: Any) -> str:
    """
    Protege un texto para mostrarlo tal cual en Discord: sin esto, un usuario como
    "-_CAS_-" se ve en cursiva ("-CAS-") y un título con "||" se convierte en spoiler.
    """
    return discord.utils.escape_markdown(str(texto if texto is not None else ""))


def fecha_corta(valor: Any) -> str:
    """'YYYY-MM-DD' a partir de un datetime o de un string ISO; 'N/A' si no hay."""
    if not valor:
        return "N/A"
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    return str(valor)[:10]


def limitar_bloque_embed(lineas: list[str], limite: int = 1024, separador: str = "\n\n") -> str:
    """Une líneas recortando para que el resultado quepa en un campo de embed."""
    if not lineas:
        return "​"

    resultado: list[str] = []
    longitud = 0
    for linea in lineas:
        extra = len(separador) if resultado else 0
        if longitud + extra + len(linea) > limite:
            break
        resultado.append(linea)
        longitud += extra + len(linea)

    valor = separador.join(resultado)
    omitidas = len(lineas) - len(resultado)
    if omitidas > 0:
        sufijo = f"{separador}... y {omitidas} más"
        if len(valor) + len(sufijo) > limite:
            valor = valor[: max(0, limite - len(sufijo))]
        valor += sufijo

    return valor or lineas[0][:limite]
