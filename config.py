"""
config.py — Variables de configuración del Bot de Retos Literarios.

Los valores sensibles se cargan desde .env.
Los IDs de canales y roles se configuran aquí o desde comandos del bot.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────── Credenciales ───────────────────────────

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")

# Guild IDs: puede ser uno o varios separados por comas
_guild_raw = os.getenv("GUILD_ID", "0")
GUILD_IDS: list[int] = [int(g.strip()) for g in _guild_raw.split(",") if g.strip()]
GUILD_ID: int = GUILD_IDS[0] if GUILD_IDS else 0  # Compatibilidad con código existente

# Gemini: Puede ser una sola llave o una lista separada por comas
_gemini_raw = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEYS: list[str] = [k.strip() for k in _gemini_raw.split(",") if k.strip()]
GEMINI_API_KEY: str = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""

# Otros proveedores (opcionales)
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

# Base de datos (Supabase)
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# ─────────────────────────── Roles ───────────────────────────

# Nombre del rol requerido para usar comandos de administrador.
# Los usuarios con este rol pueden crear eventos, iniciar votaciones, etc.
ADMIN_ROLE_NAME: str = os.getenv("ADMIN_ROLE_NAME", "Admin Literario")

# ─────────────────────────── Asistencia ───────────────────────────

# Porcentaje mínimo de asistencia en el canal de voz para poder votar (0.0 – 1.0).
PORCENTAJE_ASISTENCIA_MINIMO: float = float(os.getenv("PORCENTAJE_ASISTENCIA", "0.70"))

# ─────────────────────────── Embeds — Paleta Premium ───────────────────────────

# Colores refinados para los mensajes embebidos del bot (formato hexadecimal).
COLOR_PRINCIPAL: int   = 0x8B5CF6   # Violeta vibrante
COLOR_EXITO: int       = 0x10B981   # Esmeralda
COLOR_ERROR: int       = 0xEF4444   # Rojo coral
COLOR_INFO: int        = 0x06B6D4   # Cyan
COLOR_ADVERTENCIA: int = 0xF59E0B   # Ámbar
COLOR_ORO: int         = 0xFBBF24   # Dorado — para ganadores
COLOR_NARRACION: int   = 0xEC4899   # Rosa — para narración en vivo
COLOR_VOTACION: int    = 0x6366F1   # Índigo — para votación

# ─────────────────────────── Branding ───────────────────────────

BOT_NAME: str = "Ribby 🎀"
BOT_ICON_URL: str = ""  # URL de ícono del bot (opcional, se puede llenar)

# Separadores visuales para embeds
SEPARADOR: str = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SEPARADOR_CORTO: str = "─────────────────"
