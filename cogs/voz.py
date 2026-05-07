"""
cogs/voz.py — Detección de asistencia en canal de voz.

Escucha on_voice_state_update para registrar entradas y salidas
del canal de voz durante la fase de narración.
"""

import logging
import discord
from discord.ext import commands
import database

log = logging.getLogger("bot-literario.voz")


class Voz(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        activo = await database.obtener_evento_activo(self.bot.db)
        if not activo or activo["estado"] != "narrando":
            return

        canal_voz_id = activo["canal_voz_id"]
        if not canal_voz_id:
            return

        # Obtener la narración activa para vincular la asistencia
        narracion = await database.obtener_narracion_activa(self.bot.db, activo["id"])
        narracion_id = narracion["id"] if narracion else None

        evento_id = activo["id"]
        user_id = str(member.id)
        canal_antes = before.channel.id if before.channel else None
        canal_despues = after.channel.id if after.channel else None

        # Entró al canal de narración
        if canal_antes != canal_voz_id and canal_despues == canal_voz_id:
            await database.registrar_entrada_voz(self.bot.db, evento_id, user_id, narracion_id)
            log.info(f"🟢 {member.display_name} entró al canal de narración (sesión {narracion_id})")

        # Salió del canal de narración
        elif canal_antes == canal_voz_id and canal_despues != canal_voz_id:
            await database.registrar_salida_voz(self.bot.db, evento_id, user_id)
            log.info(f"🔴 {member.display_name} salió del canal de narración")


async def setup(bot: commands.Bot):
    await bot.add_cog(Voz(bot))
