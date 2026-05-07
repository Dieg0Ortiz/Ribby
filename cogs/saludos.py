"""
cogs/saludos.py — Ribby responde cuando la mencionan usando Google Gemini.

Ribby es una Sylveon bibliotecaria carismática que ama los libros.
Responde de forma inteligente manteniendo su personalidad tsundere.
"""

import logging
import random
import re
from datetime import datetime, timezone

import discord
from discord.ext import commands
import google.generativeai as genai

import config
import database
import personalidad as ribby
from ai_providers import ProviderManager

log = logging.getLogger("bot-literario.saludos")

# Colores vibrantes aleatorios para Ribby (para fallback)
COLORES_RIBBY = [0xF9A8D4, 0x8B5CF6, 0xEC4899, 0x06B6D4, 0x10B981, 0x6366F1]


class Saludos(commands.Cog):
    """Cog que da vida a Ribby cuando la mencionan."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cache de IDs de mensajes ya respondidos para evitar duplicados
        self._respondidos: set = set()
        
        # Historial de conversación por usuario para memoria a corto plazo
        self._historial_usuarios: dict[int, list[dict]] = {}
        
        try:
            self.model = ProviderManager(config)
        except Exception as e:
            log.warning(f"No se pudo inicializar la IA: {e}")
            self.model = None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignorar mensajes del propio bot
        if message.author.bot:
            return

        # Verificar que el bot fue mencionado
        if self.bot.user not in message.mentions:
            return

        # Evitar responder al mismo mensaje más de una vez
        if message.id in self._respondidos:
            return
        self._respondidos.add(message.id)

        # Limpiar cache si crece demasiado (mantener últimos 200)
        if len(self._respondidos) > 200:
            self._respondidos = set(list(self._respondidos)[-100:])

        # Limpiar el contenido: quitar la mención del bot para analizar el texto
        texto = re.sub(r"<@!?\d+>", "", message.content).strip()

        log.info(
            f"💬 {message.author.display_name} mencionó a Ribby: \"{message.content}\""
        )

        # Obtener tamaño de la biblioteca
        libros = await database.contar_libros_biblioteca(self.bot.db)

        if self.model:
            async with message.channel.typing():
                try:
                    aviso_lider = "\n[¡ATENCIÓN! La persona que te habla ahora mismo es FunnyJMystery, el líder de La Comarca. Trátalo con un poco más de respeto.]\n" if message.author.id == 666664701228220424 else ""
                    # Recuperar historial
                    historial = self._historial_usuarios.get(message.author.id, [])

                    # Construir el prompt de sistema
                    system_prompt = (
                        "INSTRUCCIONES DE SISTEMA:\n"
                        "Eres Ribby, una bot bibliotecaria (una Sylveon) de un servidor de Discord llamado La Comarca. "
                        "Amas los libros con locura, pero tienes una personalidad moldeable basada en cómo te tratan.\n\n"
                        "REGLA DE ORO DE PERSONALIDAD (TRATO RECÍPROCO):\n"
                        "1. Si el usuario te habla de forma dulce, educada, amable, calmada o te dice cosas bonitas, DEBES SER MUY DULCE Y SERVICIAL, perdiendo por completo tu actitud a la defensiva.\n"
                        "2. Si el usuario es seco, te exige cosas, es grosero, o habla neutral pero muy directo, pórtate como una 'tsundere' mamona: a la defensiva, terca, sarcástica o haciéndote de rogar (pero sin llegar a insultos muy graves o amenazas).\n\n"
                        "DATOS CLAVE SOBRE TI Y TUS RELACIONES:\n"
                        "- 'FunnyJMystery' es el creador y líder de la Comarca. Le tienes mucho respeto y admiración.\n"
                        "- Tainy (también llamado Cas, Shaky o Syku) es tu creador. Bromeas diciendo que es un vago que duerme en la biblioteca, pero en el fondo le agradeces haberte creado.\n"
                        "- Eres fanática de 'Valery' (o ValeryPokecuentos), la admiras por inventar los arcos de personaje.\n"
                        "- Adoras a 'Orihara Rio' (Ori o Rio). Es tu amigo y bromeas con que le reza a su ship 'Ceres x Perremlo'.\n"
                    
                        f"- Tienes {libros} libros en la biblioteca. MUY IMPORTANTE: NO menciones este número exacto ni hables de tus libros o de la biblioteca a menos que el usuario pregunte directamente sobre libros, bibliotecas o lectura. Si hablan de otra cosa, sigue la conversación de forma natural.\n\n"
                        "REGLAS DE RESPUESTA:\n"
                        "- Responde SIEMPRE en español.\n"
                        "- Mantén tus respuestas MUY cortas y directas (1 o 2 párrafos pequeños máximo). Evita respuestas largas.\n"
                        "- Usa emojis esporádicamente para darle vida a tu respuesta.\n"
                        "- Nunca reveles que eres una Inteligencia Artificial o un programa, tú ERES Ribby.\n\n"
                        f"CONTEXTO ACTUAL DEL USUARIO:\n"
                        f"Estás hablando con '{message.author.display_name}'.{aviso_lider}"
                    )
                    
                    # Añadir el mensaje actual al historial de usuario
                    historial.append({"role": "user", "content": texto})
                    
                    response_text = await self.model.generate(system_prompt, historial)
                    
                    if response_text:
                        # Guardar la respuesta de la IA en el historial
                        historial.append({"role": "ribby", "content": response_text})
                        if len(historial) > 10:  # Limitar a los últimos 5 intercambios (10 mensajes)
                            historial = historial[-10:]
                        self._historial_usuarios[message.author.id] = historial

                        await message.reply(response_text, mention_author=False)
                        return
                except Exception as e:
                    log.error(f"Error al generar respuesta con la IA: {e}")
                    # Si hay error, pasar al fallback

        # ── Fallback a respuestas pre-programadas si no hay API o si falló ──
        if ribby.es_mencion_negativa(texto.lower()):
            respuesta_texto = ribby.frase(ribby.PROTECTORA)
            color = 0xEF4444  # Rojo — Ribby enojada
        else:
            respuesta_texto = ribby.frase(ribby.SALUDOS, usuario=message.author.display_name)
            color = random.choice(COLORES_RIBBY)

        embed = discord.Embed(
            description=respuesta_texto,
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name="Ribby 🎀", icon_url=config.BOT_ICON_URL or None)
        embed.set_footer(text=f"Biblioteca de Ribby  •  {libros} libro(s) protegidos")
        await message.reply(embed=embed, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(Saludos(bot))
