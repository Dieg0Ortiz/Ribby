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
GUILD_ID: int = int(os.getenv("GUILD_ID", "0"))

# ─────────────────────────── Roles ───────────────────────────

# Nombre del rol requerido para usar comandos de administrador.
# Los usuarios con este rol pueden crear eventos, iniciar votaciones, etc.
ADMIN_ROLE_NAME: str = os.getenv("ADMIN_ROLE_NAME", "Admin Literario")

# ─────────────────────────── Asistencia ───────────────────────────

# Porcentaje mínimo de asistencia en el canal de voz para poder votar (0.0 – 1.0).
PORCENTAJE_ASISTENCIA_MINIMO: float = float(os.getenv("PORCENTAJE_ASISTENCIA", "0.70"))

# ─────────────────────────── Embeds ───────────────────────────

# Colores para los mensajes embebidos del bot (formato hexadecimal).
COLOR_PRINCIPAL: int = 0x9B59B6   # Púrpura
COLOR_EXITO: int     = 0x2ECC71   # Verde
COLOR_ERROR: int     = 0xE74C3C   # Rojo
COLOR_INFO: int      = 0x3498DB   # Azul
COLOR_ADVERTENCIA: int = 0xF39C12 # Naranja
