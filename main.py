"""
main.py — Punto de entrada del Bot de Retos Literarios.

Inicializa el bot, conecta la base de datos y carga todos los cogs.
"""

import asyncio
import logging

import discord
from discord.ext import commands

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
    command_prefix="!",  # No se usa realmente, todo con slash commands
    intents=intents,
    help_command=None,
)

# ─────────────────────────── Cogs a cargar ───────────────────────────

COGS = [
    "cogs.eventos",
    "cogs.participantes",
    "cogs.voz",
    "cogs.votacion",
    "cogs.historial",
    "cogs.saludos",
]


@bot.event
async def on_ready():
    """Se ejecuta cuando el bot se conecta exitosamente a Discord."""
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info(f"  🤖  Bot conectado como {bot.user} (ID: {bot.user.id})")
    log.info(f"  📡  Servidores: {len(bot.guilds)}")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Sincronizar slash commands con Discord
    try:
        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            synced = await bot.tree.sync(guild=guild)
            log.info(f"  ✅  {len(synced)} comandos sincronizados (guild {config.GUILD_ID})")
        else:
            synced = await bot.tree.sync()
            log.info(f"  ✅  {len(synced)} comandos sincronizados (global)")
    except Exception as e:
        log.error(f"  ❌  Error al sincronizar comandos: {e}")


import os
from aiohttp import web

async def handle_ping(request):
    return web.Response(text="Ribby is alive and listening!")

async def start_web_server():
    """Inicia un servidor web dummy para mantener vivo el proceso en servicios gratuitos (Render, Koyeb, etc.)."""
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    log.info(f"  🌐  Servidor web iniciado en el puerto {port}")


async def main():
    """Función principal asíncrona."""
    # Inicializar la base de datos
    bot.db = await database.init_db()
    log.info("  💾  Base de datos inicializada")

    # Cargar cogs
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            log.info(f"  📦  Cog cargado: {cog}")
        except Exception as e:
            log.error(f"  ❌  Error cargando {cog}: {e}")

    # Arrancar el servidor web (para evitar que plataformas como Render lo apaguen)
    await start_web_server()

    # Arrancar el bot
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
