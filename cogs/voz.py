"""
cogs/voz.py — Detección de asistencia en canal de voz.

Escucha on_voice_state_update para registrar entradas y salidas
del canal de voz durante la fase de narración. Al (re)conectar, concilia
el estado guardado con quién está realmente en el canal, por si hubo
movimientos mientras el bot estaba desconectado.
"""

import logging

import discord
from discord.ext import commands

import comun
import database

log = logging.getLogger("bot-literario.voz")


class Voz(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        comun.marcar_usuario(member, member.guild.id)  # Modo de pruebas: decide qué base de datos usar

        canal_antes = before.channel.id if before.channel else None
        canal_despues = after.channel.id if after.channel else None
        if canal_antes == canal_despues:
            return  # Mute/deafen/stream: no cambia la asistencia, no hace falta consultar la BD

        activo = await database.obtener_evento_activo(self.db)
        if not activo or activo["estado"] != "narrando" or not activo["canal_voz_id"]:
            return

        canal_voz_id = activo["canal_voz_id"]
        evento_id = activo["id"]

        if canal_despues == canal_voz_id:
            narracion = await database.obtener_narracion_activa(self.db, evento_id)
            narracion_id = narracion["id"] if narracion else None
            await database.registrar_entrada_voz(self.db, evento_id, member.id, narracion_id)
            log.info(f"🟢 {member.display_name} entró al canal de narración (sesión {narracion_id})")

        elif canal_antes == canal_voz_id:
            await database.registrar_salida_voz(self.db, evento_id, member.id)
            log.info(f"🔴 {member.display_name} salió del canal de narración")

    @commands.Cog.listener()
    async def on_ready(self):
        """Concilia la asistencia si el bot se reinició en plena narración."""
        try:
            activo = await database.obtener_evento_activo(self.db)
            if not activo or activo["estado"] != "narrando" or not activo["canal_voz_id"]:
                return

            canal = self.bot.get_channel(activo["canal_voz_id"])
            if not isinstance(canal, (discord.VoiceChannel, discord.StageChannel)):
                return

            evento_id = activo["id"]
            presentes = {str(m.id) for m in canal.members if not m.bot}
            abiertos = await database.obtener_usuarios_con_sesion_abierta(self.db, evento_id)
            narracion = await database.obtener_narracion_activa(self.db, evento_id)
            narracion_id = narracion["id"] if narracion else None

            # Salieron mientras el bot no estaba: se cierra ahora (no se sabe la hora exacta)
            for uid in abiertos - presentes:
                await database.registrar_salida_voz(self.db, evento_id, uid)
            # Entraron mientras el bot no estaba: se empieza a contar desde ahora
            for uid in presentes - abiertos:
                await database.registrar_entrada_voz(self.db, evento_id, uid, narracion_id)

            if abiertos ^ presentes:
                log.info(
                    f"🔄 Asistencia conciliada: {len(abiertos - presentes)} salida(s), "
                    f"{len(presentes - abiertos)} entrada(s)"
                )
        except Exception as e:  # noqa: BLE001
            log.warning(f"No se pudo conciliar la asistencia de voz: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Voz(bot))
