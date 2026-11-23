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
# Sin valor por defecto: si no se define, los comandos se sincronizan de forma global.
_guild_raw = os.getenv("GUILD_ID", "")
GUILD_IDS: list[int] = [int(g.strip()) for g in _guild_raw.split(",") if g.strip() and g.strip() != "0"]
GUILD_ID: int = GUILD_IDS[0] if GUILD_IDS else 0  # Compatibilidad con código existente

# Servidores de pruebas: todo lo que ocurre en ellos usa automáticamente la base de
# datos de pruebas (nunca toca los datos reales de La Comarca).
GUILDS_PRUEBAS: list[int] = [
    int(g) for g in os.getenv("GUILD_PRUEBAS", "1489169806128185517").replace(" ", "").split(",") if g.isdigit()
]
# Los comandos también se registran en los servidores de pruebas (si se usan servidores concretos)
if GUILD_IDS:
    GUILD_IDS += [g for g in GUILDS_PRUEBAS if g not in GUILD_IDS]

# Gemini: Puede ser una sola llave o una lista separada por comas
_gemini_raw = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEYS: list[str] = [k.strip() for k in _gemini_raw.split(",") if k.strip()]
GEMINI_API_KEY: str = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""

# Claude (Anthropic): proveedor principal de IA si está configurado
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")

# Hugging Face (opcional): análisis de tono, moderación y respaldo de conversación.
# Necesita un token con el permiso "Inference Providers" (https://huggingface.co/settings/tokens).
HF_TOKEN: str = os.getenv("HF_TOKEN", "")
HF_CHAT_MODEL: str = os.getenv("HF_CHAT_MODEL", "meta-llama/Llama-3.3-70B-Instruct:cheapest")
HF_MODELO_TONO: str = os.getenv("HF_MODELO_TONO", "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7")
HF_MODELO_TOXICIDAD: str = os.getenv("HF_MODELO_TOXICIDAD", "textdetox/xlmr-large-toxicity-classifier")
# Probabilidad de toxicidad a partir de la cual Ribby corta el mensaje (0–1)
UMBRAL_TOXICIDAD: float = float(os.getenv("UMBRAL_TOXICIDAD", "0.85"))

# Otros proveedores (opcionales, de respaldo)
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

# Modelos de IA (configurables sin tocar código)
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")

# Creador de Ribby (Tainy): Ribby le trata como a su padre. IDs de Discord separados por comas.
# Solo por ID: los nombres de usuario de Discord se pueden cambiar y reutilizar.
CREADOR_IDS: list[int] = [
    int(x) for x in os.getenv("CREADOR_DISCORD_ID", "641420040045985803").replace(" ", "").split(",") if x.isdigit()
]

# Listas de lectura de Wattpad que forman la base de la biblioteca (IDs separados por comas).
# Por defecto: "Historias de nuestro servidor" de La Comarca.
WATTPAD_LISTAS: list[str] = [
    x.strip() for x in os.getenv("WATTPAD_LISTAS", "1584836335").split(",") if x.strip()
]

# Segundos mínimos entre dos respuestas con IA para un mismo usuario (anti-spam / cuota).
AI_COOLDOWN_SECONDS: int = int(os.getenv("AI_COOLDOWN_SECONDS", "8"))

# Base de datos (Supabase)
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# ─────────────────────────── Roles ───────────────────────────

# Nombre del rol requerido para usar comandos de administrador.
# Los usuarios con este rol pueden crear eventos, iniciar votaciones, etc.
ADMIN_ROLE_NAME: str = os.getenv("ADMIN_ROLE_NAME", "Admin Literario")

# ─────────────────────────── Asistencia ───────────────────────────

# Porcentaje mínimo de asistencia en el canal de voz para poder votar (0.0 – 1.0).
PORCENTAJE_ASISTENCIA_MINIMO: float = float(os.getenv("PORCENTAJE_ASISTENCIA", "0.70"))

# Porcentaje mínimo de documentos descargados para que el voto sea válido (0.0 – 1.0).
PORCENTAJE_LECTURA_MINIMO: float = float(os.getenv("PORCENTAJE_LECTURA", "0.50"))

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

# ─────────────────────────── Typing Indicator ───────────────────────────

def _as_bool(value: str, default: bool = False) -> bool:
	raw = (value or "").strip().lower()
	if not raw:
		return default
	return raw in {"1", "true", "yes", "y", "on", "si", "sí"}

# Recomendado en producción: desactivado para evitar 429 en /typing.
ENABLE_TYPING_INDICATOR: bool = _as_bool(os.getenv("ENABLE_TYPING_INDICATOR", "0"), False)

# En caso de activar typing, enfriamientos para reducir reintentos al recibir 429.
TYPING_COOLDOWN_SECONDS: int = int(os.getenv("TYPING_COOLDOWN_SECONDS", "600"))
TYPING_GLOBAL_COOLDOWN_SECONDS: int = int(os.getenv("TYPING_GLOBAL_COOLDOWN_SECONDS", "600"))

# Separadores visuales para embeds
SEPARADOR: str = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SEPARADOR_CORTO: str = "─────────────────"
