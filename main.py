"""
main.py — Punto de entrada del Bot de Retos Literarios.

Inicializa el bot, conecta la base de datos, carga los cogs y levanta un
servidor web mínimo para que las plataformas gratuitas no apaguen el proceso.
"""

import asyncio
import logging
import os
import signal
import sys

import aiohttp
import discord
from aiohttp import web
from discord.ext import commands

import comun
import config
import database

# ─────────────────────────── Logging ───────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot-literario")

# ─────────────────────────── Intents ───────────────────────────

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.voice_states = True

# ─────────────────────────── Bot ───────────────────────────

bot = commands.Bot(
    command_prefix="!",  # No se usa realmente: todos los comandos son slash
    intents=intents,
    help_command=None,
    # Por seguridad, el bot nunca hace ping a @everyone/@here ni a roles.
    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False),
)

# Marca quién provoca cada interacción (necesario para el modo de pruebas)
comun.instalar_contexto(bot)

COGS = [
    "cogs.eventos",
    "cogs.participantes",
    "cogs.voz",
    "cogs.votacion",
    "cogs.historial",
    "cogs.biblioteca",
    "cogs.romance",
    "cogs.saludos",
    "cogs.pruebas",
]

_comandos_sincronizados = False


@bot.event
async def on_ready():
    """Se ejecuta al conectar (y en cada reconexión: por eso el sync va una sola vez)."""
    global _comandos_sincronizados
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info(f"  🤖  Bot conectado como {bot.user} (ID: {bot.user.id})")
    log.info(f"  📡  Servidores: {len(bot.guilds)}")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if _comandos_sincronizados:
        return
    _comandos_sincronizados = True

    if config.GUILD_IDS:
        for gid in config.GUILD_IDS:
            try:
                synced = await bot.tree.sync(guild=discord.Object(id=gid))
                log.info(f"  ✅  {len(synced)} comandos sincronizados (guild {gid})")
            except Exception as e:  # noqa: BLE001
                log.warning(f"  ⚠️  No se pudieron sincronizar comandos en guild {gid}: {e}")
    else:
        try:
            synced = await bot.tree.sync()
            log.info(f"  ✅  {len(synced)} comandos sincronizados (global)")
        except Exception as e:  # noqa: BLE001
            log.error(f"  ❌  Error al sincronizar comandos: {e}")


# ─────────────────────────── Servidor web (keep-alive) ───────────────────────────

async def handle_ping(request):
    return web.Response(text="Ribby is alive and listening!")


async def start_web_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info(f"  🌐  Servidor web iniciado en el puerto {port}")
    return runner


# ─────────────────────────── Arranque ───────────────────────────

# Errores de red al conectar por primera vez: se reintenta.
# (Una vez conectado, discord.py ya reconecta solo con reconnect=True.)
_ERRORES_RED = (aiohttp.ClientError, OSError, asyncio.TimeoutError, discord.GatewayNotFound, discord.ConnectionClosed)


async def main() -> int:
    if not config.DISCORD_TOKEN:
        log.error("  ❌  DISCORD_TOKEN no está configurado.")
        return 1

    runner = None
    async with bot:
        bot.db = await database.init_db()  # type: ignore[attr-defined]
        log.info("  💾  Base de datos inicializada")

        for cog in COGS:
            try:
                await bot.load_extension(cog)
                log.info(f"  📦  Cog cargado: {cog}")
            except Exception as e:  # noqa: BLE001
                log.exception(f"  ❌  Error cargando {cog}: {e}")

        runner = await start_web_server()

        # Railway/Docker apagan el contenedor con SIGTERM (p. ej. al redesplegar): se cierra Ribby
        # ordenadamente para que se desconecte de Discord enseguida y deje de figurar como conectada.
        bucle = asyncio.get_running_loop()
        for senal in (signal.SIGTERM, signal.SIGINT):
            try:
                bucle.add_signal_handler(senal, lambda s=senal: (
                    log.info(f"  🛑  Señal {s.name} recibida: cerrando Ribby..."),
                    asyncio.ensure_future(bot.close()),
                ))
            except (NotImplementedError, RuntimeError):  # Windows
                pass

        try:
            max_intentos = 10
            for intento in range(1, max_intentos + 1):
                try:
                    log.info(f"  🔌  Conectando a Discord (intento {intento}/{max_intentos})...")
                    await bot.start(config.DISCORD_TOKEN)
                    return 0  # El bot se cerró de forma ordenada
                except discord.LoginFailure:
                    log.error("  ❌  Token de Discord inválido. Revisa DISCORD_TOKEN.")
                    return 1
                except discord.PrivilegedIntentsRequired:
                    log.error("  ❌  Activa los intents privilegiados (Members y Message Content) en el portal de Discord.")
                    return 1
                except _ERRORES_RED as e:
                    espera = min(60, 5 * intento)
                    log.warning(f"  ⚠️  Conexión fallida: {e}. Reintentando en {espera}s...")
                    await asyncio.sleep(espera)
                    bot.clear()  # Reinicia el estado interno para poder volver a llamar a start()

            log.error("  ❌  No se pudo conectar a Discord después de todos los intentos.")
            return 1
        finally:
            if runner is not None:
                await runner.cleanup()
            await bot.db.close()  # type: ignore[attr-defined]


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
