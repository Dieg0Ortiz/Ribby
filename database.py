"""
database.py — Lógica de base de datos PostgreSQL (Supabase) para Ribby.

Usa asyncpg para operaciones asíncronas. El esquema de referencia está en
schema.sql; al arrancar, `init_db` aplica los ajustes mínimos que el código
necesita (columnas y constraints añadidas en versiones posteriores).
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import asyncpg

import config

log = logging.getLogger("bot-literario.database")


# ─────────────────────────── Modo de pruebas: enrutado de consultas ───────────────────────────
#
# Las tablas del bot existen dos veces: en el esquema "public" (datos reales) y
# en "pruebas" (copia vacía con la misma estructura). Cuando quien provoca una
# consulta está en modo de pruebas (comun.en_prueba), se reescribe el SQL para
# apuntar a "pruebas.<tabla>". Se reescribe el texto en vez de usar search_path
# porque el pooler de transacciones de Supabase no conserva el search_path.

ESQUEMA_PRUEBAS = "pruebas"
TABLAS_BOT = [
    "eventos", "narraciones", "participantes", "asistencia_voz", "votos", "habilitados_voto",
    "descargas_documentos", "documentos_participantes", "ribby_memoria", "biblioteca_historias",
    "biblioteca_etiquetas", "autores_wattpad", "afinidad_usuarios", "ribby_config", "cumpleanos", "resenas",
    "misiones_lectura", "logros_usuarios", "ribby_capitulos", "seguimientos", "relaciones_usuarios",
    "citas_ribby",
]
_RE_TABLAS = re.compile(
    r"\b(FROM|JOIN|INTO|UPDATE)(\s+)(" + "|".join(sorted(TABLAS_BOT, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def sql_para_pruebas(sql: str) -> str:
    """Redirige las tablas del bot al esquema de pruebas."""
    return _RE_TABLAS.sub(lambda m: f"{m.group(1)}{m.group(2)}{ESQUEMA_PRUEBAS}.{m.group(3)}", sql)


class _ConexionEnrutada:
    def __init__(self, conn):
        self._conn = conn

    def _sql(self, sql: str) -> str:
        from comun import en_prueba
        return sql_para_pruebas(sql) if en_prueba() else sql

    async def execute(self, sql: str, *args, **kw):
        return await self._conn.execute(self._sql(sql), *args, **kw)

    async def fetch(self, sql: str, *args, **kw):
        return await self._conn.fetch(self._sql(sql), *args, **kw)

    async def fetchrow(self, sql: str, *args, **kw):
        return await self._conn.fetchrow(self._sql(sql), *args, **kw)

    async def fetchval(self, sql: str, *args, **kw):
        return await self._conn.fetchval(self._sql(sql), *args, **kw)

    def transaction(self, *args, **kw):
        return self._conn.transaction(*args, **kw)


class PoolEnrutado:
    """Envuelve el pool real; mismo uso (`async with pool.acquire() as conn`)."""

    def __init__(self, pool: asyncpg.Pool):
        self.real = pool

    @contextlib.asynccontextmanager
    async def acquire(self):
        async with self.real.acquire() as conn:
            yield _ConexionEnrutada(conn)

    async def close(self) -> None:
        await self.real.close()


async def preparar_esquema_pruebas(pool: Any, reiniciar: bool = False) -> None:
    """Crea (o recrea vacío) el esquema de pruebas copiando la estructura de las tablas reales."""
    real = getattr(pool, "real", pool)
    async with real.acquire() as conn:
        if reiniciar:
            await conn.execute(f"DROP SCHEMA IF EXISTS {ESQUEMA_PRUEBAS} CASCADE")
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {ESQUEMA_PRUEBAS}")
        for tabla in TABLAS_BOT:
            if not await conn.fetchval("SELECT to_regclass($1)", f"public.{tabla}"):
                continue
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {ESQUEMA_PRUEBAS}.{tabla} (LIKE public.{tabla} INCLUDING ALL)"
            )
            # Columnas añadidas a la tabla real después de crear la copia de pruebas
            faltan = await conn.fetch(
                """
                SELECT a.attname AS columna, format_type(a.atttypid, a.atttypmod) AS tipo
                FROM pg_attribute a
                WHERE a.attrelid = to_regclass($1) AND a.attnum > 0 AND NOT a.attisdropped
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_attribute b
                      WHERE b.attrelid = to_regclass($2) AND b.attname = a.attname AND NOT b.attisdropped
                  )
                ORDER BY a.attnum
                """,
                f"public.{tabla}", f"{ESQUEMA_PRUEBAS}.{tabla}",
            )
            for col in faltan:
                await conn.execute(
                    f'ALTER TABLE {ESQUEMA_PRUEBAS}.{tabla} ADD COLUMN IF NOT EXISTS "{col["columna"]}" {col["tipo"]}'
                )


async def sembrar_biblioteca_pruebas(pool: Any) -> int:
    """Copia la biblioteca real (historias, etiquetas, autores) al esquema de pruebas."""
    real = getattr(pool, "real", pool)
    async with real.acquire() as conn:

        async def columnas(tabla: str, alias: str = "") -> str:
            filas = await conn.fetch(
                "SELECT attname FROM pg_attribute WHERE attrelid = to_regclass($1) AND attnum > 0 "
                "AND NOT attisdropped ORDER BY attnum",
                f"public.{tabla}",
            )
            return ", ".join(f'{alias}"{f["attname"]}"' for f in filas)

        async with conn.transaction():
            for tabla in ("biblioteca_etiquetas", "biblioteca_historias"):
                await conn.execute(f"DELETE FROM {ESQUEMA_PRUEBAS}.{tabla}")
            cols = await columnas("biblioteca_historias")
            # Las historias de retos apuntan a participantes reales que no existen en pruebas
            await conn.execute(
                f"INSERT INTO {ESQUEMA_PRUEBAS}.biblioteca_historias ({cols}) "
                f"SELECT {cols} FROM public.biblioteca_historias WHERE participante_id IS NULL"
            )
            cols = await columnas("biblioteca_etiquetas")
            await conn.execute(
                f"INSERT INTO {ESQUEMA_PRUEBAS}.biblioteca_etiquetas ({cols}) "
                f"SELECT {await columnas('biblioteca_etiquetas', 'e.')} FROM public.biblioteca_etiquetas e "
                f"JOIN {ESQUEMA_PRUEBAS}.biblioteca_historias h ON h.id = e.historia_id"
            )
            cols = await columnas("autores_wattpad")
            await conn.execute(
                f"INSERT INTO {ESQUEMA_PRUEBAS}.autores_wattpad ({cols}) SELECT {cols} FROM public.autores_wattpad "
                f"ON CONFLICT DO NOTHING"
            )
            return await conn.fetchval(f"SELECT COUNT(*) FROM {ESQUEMA_PRUEBAS}.biblioteca_historias") or 0


# ─────────────────────────── Inicialización ───────────────────────────

async def init_db() -> PoolEnrutado:
    """Crea el pool de conexiones a PostgreSQL (envuelto para el modo de pruebas)."""
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL no está configurada; Ribby no puede arrancar sin base de datos.")

    log.info("Conectando a PostgreSQL (Supabase)...")
    # statement_cache_size=0 es necesario para el "Transaction Pooler" de Supabase
    pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=10, statement_cache_size=0)
    await _asegurar_esquema(pool)
    try:
        await preparar_esquema_pruebas(pool)
    except Exception as e:  # noqa: BLE001 — el bot funciona aunque no haya esquema de pruebas
        log.warning(f"No se pudo preparar el esquema de pruebas: {e}")
    return PoolEnrutado(pool)


# Cada paso es independiente: si uno falla (p. ej. hay datos duplicados que
# impiden crear un UNIQUE) se registra y el bot sigue arrancando.
_PASOS_ESQUEMA: list[tuple[str, str]] = [
    (
        "columna eventos.votos_max_por_usuario",
        "ALTER TABLE eventos ADD COLUMN IF NOT EXISTS votos_max_por_usuario INTEGER NOT NULL DEFAULT 1",
    ),
    (
        "quitar UNIQUE de 1 voto por usuario",
        "ALTER TABLE votos DROP CONSTRAINT IF EXISTS votos_evento_votante_key",
    ),
    (
        "quitar UNIQUE de 1 voto por usuario (nombre alternativo)",
        "ALTER TABLE votos DROP CONSTRAINT IF EXISTS votos_evento_id_votante_discord_id_key",
    ),
    (
        "UNIQUE (evento, votante, participante) en votos",
        "ALTER TABLE votos ADD CONSTRAINT votos_evento_votante_participante_key "
        "UNIQUE (evento_id, votante_discord_id, participante_id)",
    ),
    # ── Biblioteca de recomendaciones ──
    (
        "tabla biblioteca_historias",
        """
        CREATE TABLE IF NOT EXISTS biblioteca_historias (
            id                SERIAL PRIMARY KEY,
            fuente            TEXT NOT NULL,              -- 'wattpad' | 'reto'
            wattpad_id        TEXT UNIQUE,
            participante_id   INTEGER UNIQUE REFERENCES participantes(id) ON DELETE SET NULL,
            titulo            TEXT NOT NULL,
            autor_nombre      TEXT,
            autor_wattpad     TEXT,
            autor_discord_id  TEXT,
            descripcion       TEXT,
            descripcion_fuente TEXT,                      -- 'wattpad' | 'autor' | 'usuario'
            url               TEXT,
            portada_url       TEXT,
            lecturas          INTEGER,
            votos             INTEGER,
            partes            INTEGER,
            completada        BOOLEAN,
            madura            BOOLEAN NOT NULL DEFAULT FALSE,
            agregada_por      TEXT,
            fecha_alta        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            fecha_sync        TIMESTAMPTZ
        )
        """,
    ),
    (
        "tabla biblioteca_etiquetas",
        """
        CREATE TABLE IF NOT EXISTS biblioteca_etiquetas (
            historia_id   INTEGER NOT NULL REFERENCES biblioteca_historias(id) ON DELETE CASCADE,
            valor         TEXT NOT NULL,                  -- en minúsculas
            fuente        TEXT NOT NULL,                  -- 'wattpad' | 'autor' | 'usuario'
            aportado_por  TEXT,
            fecha         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (historia_id, valor)
        )
        """,
    ),
    (
        "tabla autores_wattpad",
        """
        CREATE TABLE IF NOT EXISTS autores_wattpad (
            wattpad_username  TEXT PRIMARY KEY,           -- en minúsculas
            discord_id        TEXT NOT NULL,
            fecha             TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    # RLS activado: la API pública de Supabase (anon key) no puede leerlas ni
    # escribirlas. El bot se conecta como dueño de las tablas y no se ve afectado.
    ("RLS biblioteca_historias", "ALTER TABLE biblioteca_historias ENABLE ROW LEVEL SECURITY"),
    ("RLS biblioteca_etiquetas", "ALTER TABLE biblioteca_etiquetas ENABLE ROW LEVEL SECURITY"),
    ("RLS autores_wattpad", "ALTER TABLE autores_wattpad ENABLE ROW LEVEL SECURITY"),
    # ── Medidor de corazones (reutiliza afinidad_usuarios, que ya existía) ──
    (
        "tabla afinidad_usuarios",
        """
        CREATE TABLE IF NOT EXISTS afinidad_usuarios (
            usuario_discord_id   TEXT PRIMARY KEY,
            nombre_display       TEXT NOT NULL,
            corazones            REAL DEFAULT 0.0,
            nivel_relacion       TEXT DEFAULT 'desconocido',
            es_pareja            BOOLEAN DEFAULT FALSE,
            fecha_inicio_pareja  TEXT,
            racha_dias           INTEGER DEFAULT 0,
            ultima_interaccion   TEXT,
            total_interacciones  INTEGER DEFAULT 0,
            historial_eventos    TEXT DEFAULT '[]'
        )
        """,
    ),
    (
        "columnas nuevas de afinidad_usuarios",
        """
        ALTER TABLE afinidad_usuarios
            ADD COLUMN IF NOT EXISTS corazones_hoy      REAL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS dia_corazones      TEXT,
            ADD COLUMN IF NOT EXISTS coqueteos          INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS fecha_maximo       TEXT,
            ADD COLUMN IF NOT EXISTS ultimo_regalo      TEXT,
            ADD COLUMN IF NOT EXISTS ultima_cita        TEXT,
            ADD COLUMN IF NOT EXISTS ultima_declaracion TEXT,
            ADD COLUMN IF NOT EXISTS dias_descontados   INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS citas_total        INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS regalos_total      INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS quiz_aciertos      INTEGER DEFAULT 0
        """,
    ),
    (
        "tabla ribby_capitulos",
        """
        CREATE TABLE IF NOT EXISTS ribby_capitulos (
            usuario_discord_id  TEXT NOT NULL,
            capitulo            INTEGER NOT NULL,
            eleccion            INTEGER NOT NULL,
            fecha               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (usuario_discord_id, capitulo)
        )
        """,
    ),
    ("RLS ribby_capitulos", "ALTER TABLE ribby_capitulos ENABLE ROW LEVEL SECURITY"),
    # ── Vida social de Ribby: configuración, cumpleaños, reseñas, misiones y logros ──
    (
        "tabla ribby_config",
        """
        CREATE TABLE IF NOT EXISTS ribby_config (
            clave  TEXT PRIMARY KEY,
            valor  TEXT,
            fecha  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "tabla cumpleanos",
        """
        CREATE TABLE IF NOT EXISTS cumpleanos (
            usuario_discord_id  TEXT PRIMARY KEY,
            dia                 INTEGER NOT NULL CHECK (dia BETWEEN 1 AND 31),
            mes                 INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12)
        )
        """,
    ),
    (
        "tabla resenas",
        """
        CREATE TABLE IF NOT EXISTS resenas (
            id                  SERIAL PRIMARY KEY,
            historia_id         INTEGER NOT NULL REFERENCES biblioteca_historias(id) ON DELETE CASCADE,
            usuario_discord_id  TEXT NOT NULL,
            usuario_nombre      TEXT,
            puntuacion          INTEGER NOT NULL CHECK (puntuacion BETWEEN 1 AND 5),
            texto               TEXT NOT NULL,
            fecha               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (historia_id, usuario_discord_id)
        )
        """,
    ),
    (
        "tabla misiones_lectura",
        """
        CREATE TABLE IF NOT EXISTS misiones_lectura (
            id                  SERIAL PRIMARY KEY,
            usuario_discord_id  TEXT NOT NULL,
            historia_id         INTEGER NOT NULL REFERENCES biblioteca_historias(id) ON DELETE CASCADE,
            estado              TEXT NOT NULL DEFAULT 'activa',   -- activa | completada | abandonada
            fecha_asignada      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            fecha_completada    TIMESTAMPTZ
        )
        """,
    ),
    (
        "una misión activa por usuario",
        "CREATE UNIQUE INDEX IF NOT EXISTS misiones_una_activa ON misiones_lectura (usuario_discord_id) WHERE estado = 'activa'",
    ),
    (
        "tabla logros_usuarios",
        """
        CREATE TABLE IF NOT EXISTS logros_usuarios (
            usuario_discord_id  TEXT NOT NULL,
            logro               TEXT NOT NULL,
            fecha               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (usuario_discord_id, logro)
        )
        """,
    ),
    ("RLS ribby_config", "ALTER TABLE ribby_config ENABLE ROW LEVEL SECURITY"),
    ("RLS cumpleanos", "ALTER TABLE cumpleanos ENABLE ROW LEVEL SECURITY"),
    ("RLS resenas", "ALTER TABLE resenas ENABLE ROW LEVEL SECURITY"),
    ("RLS misiones_lectura", "ALTER TABLE misiones_lectura ENABLE ROW LEVEL SECURITY"),
    ("RLS logros_usuarios", "ALTER TABLE logros_usuarios ENABLE ROW LEVEL SECURITY"),
    (
        "tabla seguimientos",
        """
        CREATE TABLE IF NOT EXISTS seguimientos (
            usuario_discord_id  TEXT NOT NULL,
            historia_id         INTEGER NOT NULL REFERENCES biblioteca_historias(id) ON DELETE CASCADE,
            fecha               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (usuario_discord_id, historia_id)
        )
        """,
    ),
    ("RLS seguimientos", "ALTER TABLE seguimientos ENABLE ROW LEVEL SECURITY"),
    # ── Memoria estructurada de Ribby y relaciones entre usuarios ──
    (
        "tabla ribby_memoria",
        """
        CREATE TABLE IF NOT EXISTS ribby_memoria (
            usuario_discord_id    TEXT PRIMARY KEY,
            resumen               TEXT,
            mood                  TEXT DEFAULT 'frio',
            interacciones         INTEGER DEFAULT 0,
            ultima_actualizacion  TIMESTAMPTZ DEFAULT NOW()
        )
        """,
    ),
    (
        "columnas de memoria estructurada en ribby_memoria",
        """
        ALTER TABLE ribby_memoria
            ADD COLUMN IF NOT EXISTS hechos     TEXT DEFAULT '[]',   -- JSON: datos concretos (memoria.py)
            ADD COLUMN IF NOT EXISTS pendientes TEXT DEFAULT '[]'    -- JSON: cosas con fecha para preguntar
        """,
    ),
    (
        "tabla relaciones_usuarios",
        """
        CREATE TABLE IF NOT EXISTS relaciones_usuarios (
            usuario_a      TEXT NOT NULL,               -- siempre usuario_a < usuario_b
            usuario_b      TEXT NOT NULL,
            interacciones  INTEGER NOT NULL DEFAULT 0,  -- respuestas y menciones entre ellos
            ultima         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (usuario_a, usuario_b)
        )
        """,
    ),
    ("RLS relaciones_usuarios", "ALTER TABLE relaciones_usuarios ENABLE ROW LEVEL SECURITY"),
    (
        "tabla citas_ribby",
        """
        CREATE TABLE IF NOT EXISTS citas_ribby (
            id                  SERIAL PRIMARY KEY,
            usuario_discord_id  TEXT NOT NULL,
            fecha               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            titulo              TEXT NOT NULL,
            premisa             TEXT,
            lugar               TEXT,                  -- ingrediente sorteado (para no repetirlo con esa persona)
            recuerdo            TEXT,                  -- lo que Ribby guarda de la cita
            desenlace           TEXT,                  -- perfecta | bonita | regular | desastre | a_medias
            quimica             REAL
        )
        """,
    ),
    ("índice citas por usuario", "CREATE INDEX IF NOT EXISTS citas_ribby_usuario ON citas_ribby (usuario_discord_id, fecha DESC)"),
    ("RLS citas_ribby", "ALTER TABLE citas_ribby ENABLE ROW LEVEL SECURITY"),
    (
        "una sola pareja de Ribby",
        "CREATE UNIQUE INDEX IF NOT EXISTS afinidad_una_sola_pareja ON afinidad_usuarios ((es_pareja)) WHERE es_pareja",
    ),
]


async def _asegurar_esquema(pool: asyncpg.Pool) -> None:
    """Aplica de forma idempotente los ajustes de esquema que espera el código."""
    async with pool.acquire() as conn:
        for descripcion, sql in _PASOS_ESQUEMA:
            try:
                await conn.execute(sql)
            except (asyncpg.DuplicateObjectError, asyncpg.DuplicateTableError):
                pass  # Ya existe
            except Exception as e:  # noqa: BLE001
                if "already exists" in str(e).lower():
                    continue
                log.warning(f"No se pudo aplicar '{descripcion}': {e}")


def _now() -> datetime:
    """Timestamp UTC actual."""
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    """Timestamp UTC actual en ISO 8601 (las columnas de fecha históricas son TEXT)."""
    return _now().isoformat()


def _parse_ts(valor: Any) -> datetime:
    """Convierte un timestamp de la BD (TEXT ISO o timestamptz) a datetime con zona."""
    dt = valor if isinstance(valor, datetime) else datetime.fromisoformat(str(valor))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _minutos_desde(inicio: Any, fin: datetime) -> float:
    return max(0.0, (fin - _parse_ts(inicio)).total_seconds() / 60.0)


# ─────────────────────────── Eventos ───────────────────────────

async def crear_evento(pool: asyncpg.Pool, nombre: str, votos_max: int = 1) -> int:
    """Crea un evento y retorna su ID."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO eventos (nombre, fecha_creacion, votos_max_por_usuario) VALUES ($1, $2, $3) RETURNING id",
            nombre, _now_iso(), votos_max,
        )


async def obtener_evento_activo(pool: asyncpg.Pool) -> Optional[Dict[str, Any]]:
    """Retorna el evento que NO esté cerrado (el activo). Solo uno a la vez."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM eventos WHERE estado != 'cerrado' ORDER BY id DESC LIMIT 1")
        return dict(row) if row else None


async def obtener_evento_por_id(pool: asyncpg.Pool, evento_id: int) -> Optional[Dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM eventos WHERE id = $1", evento_id)
        return dict(row) if row else None


async def configurar_canales_evento(
    pool: asyncpg.Pool,
    evento_id: int,
    voz_id: int,
    envio_id: int,
    respaldo_id: Optional[int],
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE eventos SET canal_voz_id = $1, canal_envio_id = $2, canal_respaldo_id = $3 WHERE id = $4",
            voz_id, envio_id, respaldo_id, evento_id,
        )


async def cambiar_estado_evento(pool: asyncpg.Pool, evento_id: int, estado: str) -> None:
    async with pool.acquire() as conn:
        if estado == "cerrado":
            await conn.execute(
                "UPDATE eventos SET estado = $1, fecha_cierre = $2 WHERE id = $3",
                estado, _now_iso(), evento_id,
            )
        else:
            await conn.execute("UPDATE eventos SET estado = $1 WHERE id = $2", estado, evento_id)


async def obtener_ultimos_eventos(pool: asyncpg.Pool, limite: int = 25) -> list[Dict[str, Any]]:
    """Eventos cerrados más recientes (25 = máximo de opciones de un menú de Discord)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM eventos WHERE estado = 'cerrado' ORDER BY id DESC LIMIT $1", limite
        )
        return [dict(r) for r in rows]


# ─────────────────────────── Narración ───────────────────────────

async def crear_narracion(pool: asyncpg.Pool, evento_id: int) -> tuple[int, int]:
    """Crea una nueva narración. Retorna (narracion_id, numero_sesion)."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Bloqueo por evento para que dos comandos simultáneos no obtengan el mismo número
            await conn.execute("SELECT pg_advisory_xact_lock(1, $1::int)", evento_id)
            sesion = await conn.fetchval(
                "SELECT COALESCE(MAX(numero_sesion), 0) + 1 FROM narraciones WHERE evento_id = $1", evento_id
            )
            nid = await conn.fetchval(
                "INSERT INTO narraciones (evento_id, numero_sesion, timestamp_inicio) VALUES ($1, $2, $3) RETURNING id",
                evento_id, sesion, _now_iso(),
            )
            return nid, sesion


async def obtener_narracion_activa(pool: asyncpg.Pool, evento_id: int) -> Optional[Dict[str, Any]]:
    """Narración en curso (sin timestamp_fin) del evento."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM narraciones WHERE evento_id = $1 AND timestamp_fin IS NULL "
            "ORDER BY numero_sesion DESC LIMIT 1",
            evento_id,
        )
        return dict(row) if row else None


async def obtener_narraciones(pool: asyncpg.Pool, evento_id: int) -> list[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM narraciones WHERE evento_id = $1 ORDER BY numero_sesion ASC", evento_id
        )
        return [dict(r) for r in rows]


async def cerrar_narracion_activa(pool: asyncpg.Pool, evento_id: int) -> Optional[tuple[int, float, int]]:
    """Cierra la narración activa. Retorna (narracion_id, duracion_min, numero_sesion) o None."""
    now_dt = _now()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, timestamp_inicio, numero_sesion FROM narraciones "
                "WHERE evento_id = $1 AND timestamp_fin IS NULL ORDER BY numero_sesion DESC LIMIT 1 FOR UPDATE",
                evento_id,
            )
            if not row:
                return None
            duracion_min = _minutos_desde(row["timestamp_inicio"], now_dt)
            await conn.execute(
                "UPDATE narraciones SET timestamp_fin = $1, duracion_minutos = $2 WHERE id = $3",
                now_dt.isoformat(), duracion_min, row["id"],
            )
            await conn.execute(
                "UPDATE eventos SET duracion_narracion_minutos = COALESCE(duracion_narracion_minutos, 0) + $1 "
                "WHERE id = $2",
                duracion_min, evento_id,
            )
            return row["id"], duracion_min, row["numero_sesion"]


async def guardar_duracion_total_narraciones(pool: asyncpg.Pool, evento_id: int) -> None:
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT COALESCE(SUM(duracion_minutos), 0) FROM narraciones WHERE evento_id = $1", evento_id
        )
        await conn.execute(
            "UPDATE eventos SET duracion_narracion_minutos = $1 WHERE id = $2", float(val or 0), evento_id
        )


# ─────────────────────────── Participantes ───────────────────────────

async def registrar_participante(
    pool: asyncpg.Pool,
    evento_id: int,
    discord_id: int,
    nombre: str,
    titulo: Optional[str] = None,
) -> int:
    """
    Registra a un participante o actualiza su nombre/título.

    Al re-registrarse se CONSERVAN los archivos ya subidos (url_pdf/url_portada)
    y la fecha de registro original.
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO participantes
                (evento_id, usuario_discord_id, usuario_nombre, titulo_historia, fecha_registro)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (evento_id, usuario_discord_id)
            DO UPDATE SET
                usuario_nombre  = EXCLUDED.usuario_nombre,
                titulo_historia = COALESCE(EXCLUDED.titulo_historia, participantes.titulo_historia)
            RETURNING id
            """,
            evento_id, str(discord_id), nombre, titulo, _now_iso(),
        )


async def obtener_participante_por_usuario(pool: asyncpg.Pool, evento_id: int, discord_id) -> Optional[Dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM participantes WHERE evento_id = $1 AND usuario_discord_id = $2",
            evento_id, str(discord_id),
        )
        return dict(row) if row else None


async def obtener_participantes(pool: asyncpg.Pool, evento_id: int) -> list[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM participantes WHERE evento_id = $1 ORDER BY id ASC", evento_id)
        return [dict(r) for r in rows]


async def actualizar_pdf(pool: asyncpg.Pool, participante_id: int, url: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE participantes SET url_pdf = $1 WHERE id = $2", url, participante_id)


async def actualizar_portada(pool: asyncpg.Pool, participante_id: int, url: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE participantes SET url_portada = $1 WHERE id = $2", url, participante_id)


async def contar_documentos_subidos(pool: asyncpg.Pool, evento_id: int) -> int:
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT COUNT(*) FROM participantes WHERE evento_id = $1 AND url_pdf IS NOT NULL", evento_id
        )
        return val or 0


# ─────────────────────────── Asistencia en Voz ───────────────────────────

async def registrar_entrada_voz(pool: asyncpg.Pool, evento_id: int, discord_id, narracion_id=None) -> None:
    """Registra la entrada de un usuario al canal de voz (si no tiene ya una sesión abierta)."""
    discord_id_str = str(discord_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM asistencia_voz WHERE evento_id = $1 AND usuario_discord_id = $2 AND timestamp_salida IS NULL",
            evento_id, discord_id_str,
        )
        if not row:
            await conn.execute(
                "INSERT INTO asistencia_voz (evento_id, narracion_id, usuario_discord_id, timestamp_entrada) "
                "VALUES ($1, $2, $3, $4)",
                evento_id, narracion_id, discord_id_str, _now_iso(),
            )


async def registrar_salida_voz(pool: asyncpg.Pool, evento_id: int, discord_id) -> None:
    """Cierra la sesión de voz abierta del usuario y guarda los minutos."""
    now_dt = _now()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, timestamp_entrada FROM asistencia_voz WHERE evento_id = $1 AND usuario_discord_id = $2 "
            "AND timestamp_salida IS NULL ORDER BY id DESC LIMIT 1",
            evento_id, str(discord_id),
        )
        if row:
            await conn.execute(
                "UPDATE asistencia_voz SET timestamp_salida = $1, minutos_totales = $2 WHERE id = $3",
                now_dt.isoformat(), _minutos_desde(row["timestamp_entrada"], now_dt), row["id"],
            )


async def obtener_usuarios_con_sesion_abierta(pool: asyncpg.Pool, evento_id: int) -> set[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT usuario_discord_id FROM asistencia_voz WHERE evento_id = $1 AND timestamp_salida IS NULL",
            evento_id,
        )
        return {r["usuario_discord_id"] for r in rows}


async def cerrar_sesiones_abiertas(pool: asyncpg.Pool, evento_id: int) -> None:
    """Cierra todas las sesiones de voz sin timestamp_salida."""
    now_dt = _now()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, timestamp_entrada FROM asistencia_voz WHERE evento_id = $1 AND timestamp_salida IS NULL",
            evento_id,
        )
        for row in rows:
            await conn.execute(
                "UPDATE asistencia_voz SET timestamp_salida = $1, minutos_totales = $2 WHERE id = $3",
                now_dt.isoformat(), _minutos_desde(row["timestamp_entrada"], now_dt), row["id"],
            )


async def calcular_asistencia_total(pool: asyncpg.Pool, evento_id: int) -> Dict[str, float]:
    """{discord_id: minutos_totales} para el evento."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT usuario_discord_id, SUM(minutos_totales) AS total FROM asistencia_voz "
            "WHERE evento_id = $1 GROUP BY usuario_discord_id",
            evento_id,
        )
        return {r["usuario_discord_id"]: float(r["total"] or 0) for r in rows}


async def contar_asistentes_narracion(pool: asyncpg.Pool, narracion_id: int) -> int:
    """Usuarios distintos que estuvieron en una sesión concreta de narración."""
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT COUNT(DISTINCT usuario_discord_id) FROM asistencia_voz WHERE narracion_id = $1", narracion_id
        )
        return val or 0


# ─────────────────────────── Estadísticas ───────────────────────────

async def contar_libros_biblioteca(pool: asyncpg.Pool) -> int:
    """Total histórico de historias registradas en todos los retos."""
    if not pool:
        return 0
    try:
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM participantes") or 0
    except Exception as e:  # noqa: BLE001
        log.error(f"Error contando libros: {e}")
        return 0


# ─────────────────────────── Votación ───────────────────────────

async def configurar_votos_max(pool: asyncpg.Pool, evento_id: int, max_votos: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE eventos SET votos_max_por_usuario = $1 WHERE id = $2", max_votos, evento_id)


async def contar_votos_usuario(pool: asyncpg.Pool, evento_id: int, votante_discord_id) -> int:
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT COUNT(*) FROM votos WHERE evento_id = $1 AND votante_discord_id = $2",
            evento_id, str(votante_discord_id),
        )
        return val or 0


async def obtener_votos_usuario_lista(pool: asyncpg.Pool, evento_id: int, votante_discord_id) -> list[int]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT participante_id FROM votos WHERE evento_id = $1 AND votante_discord_id = $2",
            evento_id, str(votante_discord_id),
        )
        return [r["participante_id"] for r in rows]


# Resultados posibles de registrar_voto
VOTO_OK = "ok"
VOTO_DUPLICADO = "duplicado"
VOTO_LIMITE = "limite"
VOTO_CERRADO = "cerrado"
VOTO_INVALIDO = "invalido"


async def registrar_voto(
    pool: asyncpg.Pool,
    evento_id: int,
    votante_discord_id,
    participante_id: int,
    es_valido: bool = True,
) -> str:
    """
    Registra un voto de forma atómica.

    Toda la comprobación (estado del evento, historia válida, no auto-voto,
    duplicado y límite) ocurre dentro de una transacción con un bloqueo por
    votante, para que dos clics simultáneos no superen el límite.
    Retorna una de las constantes VOTO_*.
    """
    votante_str = str(votante_discord_id)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1::int, hashtext($2))", evento_id, votante_str)

            evento = await conn.fetchrow(
                "SELECT estado, votos_max_por_usuario FROM eventos WHERE id = $1", evento_id
            )
            if not evento or evento["estado"] != "votando":
                return VOTO_CERRADO

            autor = await conn.fetchval(
                "SELECT usuario_discord_id FROM participantes WHERE id = $1 AND evento_id = $2",
                participante_id, evento_id,
            )
            if autor is None or autor == votante_str:
                return VOTO_INVALIDO

            ya = await conn.fetchval(
                "SELECT 1 FROM votos WHERE evento_id = $1 AND votante_discord_id = $2 AND participante_id = $3",
                evento_id, votante_str, participante_id,
            )
            if ya:
                return VOTO_DUPLICADO

            usados = await conn.fetchval(
                "SELECT COUNT(*) FROM votos WHERE evento_id = $1 AND votante_discord_id = $2",
                evento_id, votante_str,
            ) or 0
            if usados >= (evento["votos_max_por_usuario"] or 1):
                return VOTO_LIMITE

            try:
                await conn.execute(
                    "INSERT INTO votos (evento_id, votante_discord_id, participante_id, timestamp_voto, es_valido) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    evento_id, votante_str, participante_id, _now_iso(), 1 if es_valido else 0,
                )
            except asyncpg.UniqueViolationError:
                return VOTO_DUPLICADO
            return VOTO_OK


async def obtener_resultados_votacion(pool: asyncpg.Pool, evento_id: int) -> list[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT p.usuario_nombre, p.titulo_historia, COUNT(v.id) AS total_votos
            FROM participantes p
            LEFT JOIN votos v ON p.id = v.participante_id AND v.es_valido = 1
            WHERE p.evento_id = $1
            GROUP BY p.id, p.usuario_nombre, p.titulo_historia
            ORDER BY total_votos DESC, p.id ASC""",
            evento_id,
        )
        return [dict(r) for r in rows]


async def contar_votos_totales(pool: asyncpg.Pool, evento_id: int) -> Dict[str, int]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) FILTER (WHERE es_valido = 1) AS validos, "
            "COUNT(*) FILTER (WHERE es_valido = 0) AS nulos FROM votos WHERE evento_id = $1",
            evento_id,
        )
        return {"validos": row["validos"] or 0, "nulos": row["nulos"] or 0}


async def obtener_votos_nulos(pool: asyncpg.Pool, evento_id: int) -> list[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT v.votante_discord_id, p.titulo_historia
            FROM votos v
            JOIN participantes p ON v.participante_id = p.id
            WHERE v.evento_id = $1 AND v.es_valido = 0""",
            evento_id,
        )
        return [dict(r) for r in rows]


# ─────────────────────────── Control de Fraude ───────────────────────────
#
# `habilitados_voto` SOLO se escribe en guardar_habilitados(), que llama
# /evento iniciar_votacion tras evaluar los umbrales. Las descargas se anotan
# únicamente en `descargas_documentos`; antes también creaban una fila en
# habilitados_voto, lo que habilitaba a cualquiera con un solo clic.

async def registrar_descarga(pool: asyncpg.Pool, evento_id: int, discord_id, participante_id: int) -> None:
    """Anota que el usuario descargó un documento (una vez por documento)."""
    # La PK (evento_id, usuario_discord_id, participante_id) evita duplicados,
    # incluso con dos clics simultáneos.
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO descargas_documentos (evento_id, usuario_discord_id, participante_id, timestamp_descarga) "
            "VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            evento_id, str(discord_id), participante_id, _now_iso(),
        )


async def calcular_descargas_por_usuario(pool: asyncpg.Pool, evento_id: int) -> Dict[str, int]:
    """{discord_id: nº de documentos distintos descargados} en el evento."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT usuario_discord_id, COUNT(DISTINCT participante_id) AS total FROM descargas_documentos "
            "WHERE evento_id = $1 GROUP BY usuario_discord_id",
            evento_id,
        )
        return {r["usuario_discord_id"]: int(r["total"]) for r in rows}


async def guardar_habilitados(pool: asyncpg.Pool, evento_id: int, habilitados_dict: Dict[str, Dict[str, Any]]) -> None:
    """Reemplaza por completo la lista de habilitados del evento."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM habilitados_voto WHERE evento_id = $1", evento_id)
            for uid, stats in habilitados_dict.items():
                await conn.execute(
                    "INSERT INTO habilitados_voto (evento_id, usuario_discord_id, minutos_presencia, documentos_descargados) "
                    "VALUES ($1, $2, $3, $4)",
                    evento_id, uid, stats.get("minutos", 0), stats.get("descargas", 0),
                )


async def esta_habilitado(pool: asyncpg.Pool, evento_id: int, discord_id) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM habilitados_voto WHERE evento_id = $1 AND usuario_discord_id = $2",
            evento_id, str(discord_id),
        )
        return row is not None


# ─────────────────────────── Documentos Persistentes ───────────────────────────

async def guardar_documento(
    pool: asyncpg.Pool,
    participante_id: int,
    evento_id: int,
    usuario_discord_id: str,
    tipo: str,  # 'pdf' | 'portada'
    url_discord: str,
    url_respaldo: Optional[str] = None,
    nombre_archivo: Optional[str] = None,
    content_type: Optional[str] = None,
    tamanio_bytes: Optional[int] = None,
) -> str:
    """
    Inserta o actualiza el documento de un participante (incrementa la versión).
    Retorna la url_activa (respaldo si existe, discord si no).
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO documentos_participantes
                    (participante_id, evento_id, usuario_discord_id, tipo,
                     url_discord, url_respaldo, nombre_archivo, content_type,
                     tamanio_bytes, version, fecha_subida)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 1, NOW())
                ON CONFLICT (participante_id, tipo)
                DO UPDATE SET
                    url_discord         = EXCLUDED.url_discord,
                    -- Un archivo nuevo sin respaldo NO debe heredar el respaldo del archivo anterior
                    url_respaldo        = EXCLUDED.url_respaldo,
                    nombre_archivo      = COALESCE(EXCLUDED.nombre_archivo, documentos_participantes.nombre_archivo),
                    content_type        = COALESCE(EXCLUDED.content_type, documentos_participantes.content_type),
                    tamanio_bytes       = COALESCE(EXCLUDED.tamanio_bytes, documentos_participantes.tamanio_bytes),
                    version             = documentos_participantes.version + 1,
                    fecha_actualizacion = NOW()
                RETURNING url_activa
                """,
                participante_id, evento_id, usuario_discord_id, tipo,
                url_discord, url_respaldo, nombre_archivo, content_type, tamanio_bytes,
            )
            url_activa = (row["url_activa"] if row else None) or url_respaldo or url_discord

            # Mantener sincronizada la tabla participantes (la usan los cogs)
            col = "url_pdf" if tipo == "pdf" else "url_portada"
            await conn.execute(f"UPDATE participantes SET {col} = $1 WHERE id = $2", url_activa, participante_id)
            return url_activa


async def sincronizar_urls_desde_documentos(pool: asyncpg.Pool, evento_id: int) -> int:
    """
    Mantenimiento: copia a `participantes` las url_activa de documentos_participantes.
    Útil si alguna vez quedan desincronizadas. Retorna el número de filas actualizadas.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT participante_id, tipo, url_activa FROM documentos_participantes WHERE evento_id = $1", evento_id
        )
        updated = 0
        for row in rows:
            if not row["url_activa"]:
                continue
            col = "url_pdf" if row["tipo"] == "pdf" else "url_portada"
            result = await conn.execute(
                f"UPDATE participantes SET {col} = $1 WHERE id = $2", row["url_activa"], row["participante_id"]
            )
            if result != "UPDATE 0":
                updated += 1
        return updated


# ─────────────────────────── Memoria de Ribby ───────────────────────────

async def obtener_memoria_usuario(pool: asyncpg.Pool, discord_id: int) -> Optional[Dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM ribby_memoria WHERE usuario_discord_id = $1", str(discord_id))
        return dict(row) if row else None


async def guardar_memoria_usuario(
    pool: asyncpg.Pool,
    discord_id: int,
    resumen: str,
    mood: str,
    interacciones: int,
    hechos: Optional[str] = None,
    pendientes: Optional[str] = None,
) -> None:
    """
    Crea o actualiza la memoria de un usuario (upsert). `hechos` y `pendientes`
    son JSON (ver memoria.py); si se pasan como None se conservan los que había.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ribby_memoria
                (usuario_discord_id, resumen, mood, interacciones, ultima_actualizacion, hechos, pendientes)
            VALUES ($1, $2, $3, $4, $5, COALESCE($6::text, '[]'), COALESCE($7::text, '[]'))
            ON CONFLICT (usuario_discord_id)
            DO UPDATE SET
                resumen = EXCLUDED.resumen,
                mood = EXCLUDED.mood,
                interacciones = EXCLUDED.interacciones,
                ultima_actualizacion = EXCLUDED.ultima_actualizacion,
                hechos = CASE WHEN $6::text IS NULL THEN ribby_memoria.hechos ELSE EXCLUDED.hechos END,
                pendientes = CASE WHEN $7::text IS NULL THEN ribby_memoria.pendientes ELSE EXCLUDED.pendientes END
            """,
            # ultima_actualizacion es timestamptz: asyncpg exige un datetime, no un string ISO
            str(discord_id), resumen, mood, interacciones, _now(), hechos, pendientes,
        )


async def guardar_hechos_pendientes(
    pool: asyncpg.Pool, discord_id, hechos: Optional[str] = None, pendientes: Optional[str] = None
) -> None:
    """Actualiza solo los datos y/o pendientes (JSON) de la memoria de un usuario."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ribby_memoria (usuario_discord_id, hechos, pendientes)
            VALUES ($1, COALESCE($2::text, '[]'), COALESCE($3::text, '[]'))
            ON CONFLICT (usuario_discord_id) DO UPDATE SET
                hechos = CASE WHEN $2::text IS NULL THEN ribby_memoria.hechos ELSE EXCLUDED.hechos END,
                pendientes = CASE WHEN $3::text IS NULL THEN ribby_memoria.pendientes ELSE EXCLUDED.pendientes END
            """,
            str(discord_id), hechos, pendientes,
        )


async def olvidar_memoria_usuario(pool: asyncpg.Pool, discord_id) -> bool:
    """Borra todo lo que Ribby recuerda de las charlas con un usuario (no toca su relación ni sus logros)."""
    async with pool.acquire() as conn:
        borrado = await conn.execute("DELETE FROM ribby_memoria WHERE usuario_discord_id = $1", str(discord_id))
        await conn.execute(
            "DELETE FROM relaciones_usuarios WHERE usuario_a = $1 OR usuario_b = $1", str(discord_id)
        )
        return borrado != "DELETE 0"


async def memorias_con_pendientes(pool: asyncpg.Pool) -> list[Dict[str, Any]]:
    """Usuarios con algún pendiente guardado (para que Ribby pregunte cómo les fue)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT usuario_discord_id, pendientes FROM ribby_memoria "
            "WHERE pendientes IS NOT NULL AND pendientes NOT IN ('', '[]')"
        )
        return [dict(r) for r in rows]


# ─────────────────────────── Relaciones entre usuarios ───────────────────────────

async def sumar_relaciones(pool: asyncpg.Pool, pares: list[tuple[str, str, int]]) -> None:
    """Suma interacciones (respuestas/menciones) entre parejas de usuarios. Cada par va ordenado (a < b)."""
    if not pares:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO relaciones_usuarios (usuario_a, usuario_b, interacciones)
            SELECT a, b, n FROM unnest($1::text[], $2::text[], $3::int[]) AS t(a, b, n)
            ON CONFLICT (usuario_a, usuario_b) DO UPDATE SET
                interacciones = relaciones_usuarios.interacciones + EXCLUDED.interacciones,
                ultima = NOW()
            """,
            [p[0] for p in pares], [p[1] for p in pares], [p[2] for p in pares],
        )


async def relaciones_de(pool: asyncpg.Pool, discord_id, limite: int = 5) -> list[tuple[str, int]]:
    """Con quién interactúa más un usuario: [(otro_id, interacciones)]."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT CASE WHEN usuario_a = $1 THEN usuario_b ELSE usuario_a END AS otro, interacciones
            FROM relaciones_usuarios WHERE usuario_a = $1 OR usuario_b = $1
            ORDER BY interacciones DESC, ultima DESC LIMIT $2
            """,
            str(discord_id), limite,
        )
        return [(r["otro"], int(r["interacciones"])) for r in rows]


# ─────────────────────────── Biblioteca de recomendaciones ───────────────────────────

_SQL_CATALOGO = """
    SELECT b.*,
           COALESCE(b.autor_discord_id, a.discord_id) AS autor_discord,
           p.url_pdf, p.url_portada AS portada_reto, p.usuario_discord_id AS participante_discord,
           e.nombre AS evento_nombre,
           COALESCE((SELECT array_agg(t.valor ORDER BY t.valor)
                     FROM biblioteca_etiquetas t WHERE t.historia_id = b.id), '{}') AS tags,
           (SELECT ROUND(AVG(r.puntuacion)::numeric, 1) FROM resenas r WHERE r.historia_id = b.id) AS nota_media,
           (SELECT COUNT(*) FROM resenas r WHERE r.historia_id = b.id) AS num_resenas
    FROM biblioteca_historias b
    LEFT JOIN autores_wattpad a ON a.wattpad_username = lower(b.autor_wattpad)
    LEFT JOIN participantes p ON p.id = b.participante_id
    LEFT JOIN eventos e ON e.id = p.evento_id
"""


def _fila_catalogo(r) -> Dict[str, Any]:
    d = dict(r)
    d["tags"] = list(d.get("tags") or [])
    d["nota_media"] = float(d["nota_media"]) if d.get("nota_media") is not None else None
    return d


async def listar_catalogo(pool: asyncpg.Pool) -> list[Dict[str, Any]]:
    """Todas las historias de la biblioteca con sus tags y datos de reto."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SQL_CATALOGO + " ORDER BY b.id")
        return [_fila_catalogo(r) for r in rows]


async def obtener_historia_biblioteca(pool: asyncpg.Pool, historia_id: int) -> Optional[Dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_SQL_CATALOGO + " WHERE b.id = $1", historia_id)
        return _fila_catalogo(row) if row else None


async def _reemplazar_tags_wattpad(conn, historia_id: int, tags: list[str]) -> None:
    """Sincroniza los tags que vienen de Wattpad sin tocar los aportados por personas."""
    await conn.execute(
        "DELETE FROM biblioteca_etiquetas WHERE historia_id = $1 AND fuente = 'wattpad' AND NOT (valor = ANY($2::text[]))",
        historia_id, tags,
    )
    if tags:
        await conn.execute(
            "INSERT INTO biblioteca_etiquetas (historia_id, valor, fuente) "
            "SELECT $1, unnest($2::text[]), 'wattpad' ON CONFLICT DO NOTHING",
            historia_id, tags,
        )


async def guardar_historia_wattpad(
    pool: asyncpg.Pool, datos: Dict[str, Any], agregada_por: Optional[str] = None
) -> tuple[int, bool]:
    """
    Inserta o actualiza una historia de Wattpad (datos de wattpad._normalizar).
    Retorna (historia_id, es_nueva). Una descripción escrita por el autor en
    Discord no se sobrescribe con la de Wattpad.
    """
    hid, nueva, _ = await guardar_historia_wattpad_detalle(pool, datos, agregada_por)
    return hid, nueva


async def guardar_historia_wattpad_detalle(
    pool: asyncpg.Pool, datos: Dict[str, Any], agregada_por: Optional[str] = None
) -> tuple[int, bool, Optional[int]]:
    """Como guardar_historia_wattpad, pero retorna también el número de partes que tenía antes."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            partes_antes = await conn.fetchval(
                "SELECT partes FROM biblioteca_historias WHERE wattpad_id = $1", datos["wattpad_id"]
            )
            row = await conn.fetchrow(
                """
                INSERT INTO biblioteca_historias
                    (fuente, wattpad_id, titulo, autor_nombre, autor_wattpad, descripcion, descripcion_fuente,
                     url, portada_url, lecturas, votos, partes, completada, madura, agregada_por, fecha_sync)
                VALUES ('wattpad', $1, $2, $3, $4, $5, CASE WHEN $5::text IS NULL THEN NULL ELSE 'wattpad' END,
                        $6, $7, $8, $9, $10, $11, $12, $13, NOW())
                ON CONFLICT (wattpad_id) DO UPDATE SET
                    titulo        = EXCLUDED.titulo,
                    autor_nombre  = EXCLUDED.autor_nombre,
                    autor_wattpad = EXCLUDED.autor_wattpad,
                    descripcion   = CASE WHEN biblioteca_historias.descripcion_fuente = 'autor'
                                         THEN biblioteca_historias.descripcion
                                         ELSE COALESCE(EXCLUDED.descripcion, biblioteca_historias.descripcion) END,
                    descripcion_fuente = CASE WHEN biblioteca_historias.descripcion_fuente = 'autor' THEN 'autor'
                                         WHEN EXCLUDED.descripcion IS NOT NULL THEN 'wattpad'
                                         ELSE biblioteca_historias.descripcion_fuente END,
                    url           = EXCLUDED.url,
                    portada_url   = EXCLUDED.portada_url,
                    lecturas      = EXCLUDED.lecturas,
                    votos         = EXCLUDED.votos,
                    partes        = EXCLUDED.partes,
                    completada    = EXCLUDED.completada,
                    madura        = EXCLUDED.madura,
                    fecha_sync    = NOW()
                RETURNING id, (xmax = 0) AS nueva
                """,
                datos["wattpad_id"], datos["titulo"], datos.get("autor_nombre"), datos.get("autor_wattpad"),
                datos.get("descripcion"), datos.get("url"), datos.get("portada_url"), datos.get("lecturas"),
                datos.get("votos"), datos.get("partes"), datos.get("completada"), bool(datos.get("madura")),
                agregada_por,
            )
            await _reemplazar_tags_wattpad(conn, row["id"], datos.get("tags") or [])
            return row["id"], bool(row["nueva"]), partes_antes


async def sincronizar_retos_biblioteca(pool: asyncpg.Pool) -> int:
    """Crea la ficha de biblioteca de cada participante de reto que aún no la tenga."""
    async with pool.acquire() as conn:
        res = await conn.execute(
            """
            INSERT INTO biblioteca_historias (fuente, participante_id, titulo, autor_nombre, autor_discord_id)
            SELECT 'reto', p.id, COALESCE(NULLIF(p.titulo_historia, ''), 'Sin título'), p.usuario_nombre, p.usuario_discord_id
            FROM participantes p
            WHERE NOT EXISTS (SELECT 1 FROM biblioteca_historias b WHERE b.participante_id = p.id)
            """
        )
        return int(res.split()[-1]) if res else 0


async def historia_de_participante(pool: asyncpg.Pool, participante_id: int) -> int:
    """ID de la ficha de biblioteca del participante (la crea o actualiza su título)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, fuente FROM biblioteca_historias WHERE participante_id = $1", participante_id
        )
        p = await conn.fetchrow(
            "SELECT titulo_historia, usuario_nombre, usuario_discord_id FROM participantes WHERE id = $1", participante_id
        )
        titulo = (p["titulo_historia"] if p else None) or "Sin título"
        if row:
            if row["fuente"] == "reto":  # El título de Wattpad manda sobre el del registro
                await conn.execute("UPDATE biblioteca_historias SET titulo = $1 WHERE id = $2", titulo, row["id"])
            return row["id"]
        return await conn.fetchval(
            "INSERT INTO biblioteca_historias (fuente, participante_id, titulo, autor_nombre, autor_discord_id) "
            "VALUES ('reto', $1, $2, $3, $4) RETURNING id",
            participante_id, titulo, p["usuario_nombre"] if p else None, p["usuario_discord_id"] if p else None,
        )


async def asociar_participante(pool: asyncpg.Pool, historia_id: int, participante_id: int, discord_id: str) -> None:
    """
    Une la ficha de Wattpad `historia_id` con un participante de reto. Si el
    participante ya tenía su propia ficha de reto, se fusiona (tags y resumen)
    y se elimina para que no haya duplicados.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            previa = await conn.fetchrow(
                "SELECT id, descripcion, descripcion_fuente FROM biblioteca_historias "
                "WHERE participante_id = $1 AND id <> $2",
                participante_id, historia_id,
            )
            if previa:
                await conn.execute(
                    "INSERT INTO biblioteca_etiquetas (historia_id, valor, fuente, aportado_por) "
                    "SELECT $1, valor, fuente, aportado_por FROM biblioteca_etiquetas WHERE historia_id = $2 "
                    "ON CONFLICT DO NOTHING",
                    historia_id, previa["id"],
                )
                if previa["descripcion"] and previa["descripcion_fuente"] == "autor":
                    await conn.execute(
                        "UPDATE biblioteca_historias SET descripcion = $1, descripcion_fuente = 'autor' WHERE id = $2",
                        previa["descripcion"], historia_id,
                    )
                await conn.execute("DELETE FROM biblioteca_historias WHERE id = $1", previa["id"])
            await conn.execute(
                "UPDATE biblioteca_historias SET participante_id = $1, autor_discord_id = $2 WHERE id = $3",
                participante_id, discord_id, historia_id,
            )


async def agregar_etiquetas(
    pool: asyncpg.Pool, historia_id: int, valores: list[str], fuente: str, aportado_por: Optional[str]
) -> int:
    """Añade tags (en minúsculas, sin duplicados). Retorna cuántos eran nuevos."""
    limpios = sorted({v.strip().lower()[:60] for v in valores if v and v.strip()})
    if not limpios:
        return 0
    async with pool.acquire() as conn:
        res = await conn.execute(
            "INSERT INTO biblioteca_etiquetas (historia_id, valor, fuente, aportado_por) "
            "SELECT $1, unnest($2::text[]), $3, $4 ON CONFLICT DO NOTHING",
            historia_id, limpios, fuente, aportado_por,
        )
        return int(res.split()[-1])


async def guardar_descripcion(
    pool: asyncpg.Pool, historia_id: int, texto: str, fuente: str
) -> bool:
    """
    Guarda el resumen de una historia. El autor siempre puede escribirlo;
    el resto solo si la historia aún no tiene uno. Retorna si se guardó.
    """
    async with pool.acquire() as conn:
        res = await conn.execute(
            """
            UPDATE biblioteca_historias SET descripcion = $1, descripcion_fuente = $2
            WHERE id = $3 AND ($2 = 'autor' OR descripcion IS NULL OR descripcion = '')
            """,
            texto.strip()[:2000], fuente, historia_id,
        )
        return res != "UPDATE 0"


async def vincular_autor_wattpad(pool: asyncpg.Pool, wattpad_username: str, discord_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO autores_wattpad (wattpad_username, discord_id) VALUES (lower($1), $2) "
            "ON CONFLICT (wattpad_username) DO UPDATE SET discord_id = EXCLUDED.discord_id, fecha = NOW()",
            wattpad_username, discord_id,
        )


async def wattpad_de_discord(pool: asyncpg.Pool, discord_id) -> list[str]:
    """Cuentas de Wattpad vinculadas a un usuario de Discord."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT wattpad_username FROM autores_wattpad WHERE discord_id = $1", str(discord_id))
        return [r["wattpad_username"] for r in rows]


async def eliminar_historia_biblioteca(pool: asyncpg.Pool, historia_id: int) -> bool:
    async with pool.acquire() as conn:
        return await conn.execute("DELETE FROM biblioteca_historias WHERE id = $1", historia_id) != "DELETE 0"


# ─────────────────────────── Medidor de corazones ───────────────────────────

_CAMPOS_AFINIDAD = (
    "corazones", "es_pareja", "fecha_inicio_pareja", "racha_dias", "ultima_interaccion", "total_interacciones",
    "corazones_hoy", "dia_corazones", "coqueteos", "fecha_maximo", "ultimo_regalo", "ultima_cita",
    "ultima_declaracion", "dias_descontados", "citas_total", "regalos_total", "quiz_aciertos",
)
_CAMPOS_FECHA = ("fecha_inicio_pareja", "ultima_interaccion", "fecha_maximo", "ultima_declaracion")


def _estado_desde_fila(row) -> Dict[str, Any]:
    estado: Dict[str, Any] = {c: row[c] for c in _CAMPOS_AFINIDAD}
    estado["corazones"] = float(estado["corazones"] or 0)
    estado["corazones_hoy"] = float(estado["corazones_hoy"] or 0)
    estado["es_pareja"] = bool(estado["es_pareja"])
    for c in ("racha_dias", "total_interacciones", "coqueteos", "dias_descontados", "citas_total", "regalos_total",
              "quiz_aciertos"):
        estado[c] = int(estado[c] or 0)
    for c in _CAMPOS_FECHA:  # Datos antiguos con otro formato: se descartan en vez de romper
        try:
            if estado[c]:
                _parse_ts(estado[c])
        except ValueError:
            estado[c] = None
    try:
        eventos = json.loads(row["historial_eventos"] or "[]")
        estado["eventos"] = [e for e in eventos if isinstance(e, dict) and "texto" in e]
    except (ValueError, TypeError):
        estado["eventos"] = []
    estado["usuario_discord_id"] = row["usuario_discord_id"]
    estado["nombre_display"] = row["nombre_display"]
    return estado


async def obtener_afinidad(pool: asyncpg.Pool, discord_id) -> Optional[Dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM afinidad_usuarios WHERE usuario_discord_id = $1", str(discord_id))
        return _estado_desde_fila(row) if row else None


async def pareja_actual(pool: asyncpg.Pool) -> Optional[Dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM afinidad_usuarios WHERE es_pareja LIMIT 1")
        return _estado_desde_fila(row) if row else None


async def guardar_afinidad(pool: asyncpg.Pool, discord_id, nombre: str, estado: Dict[str, Any], nivel: str) -> None:
    """
    Guarda el estado completo. Si se intenta registrar una segunda pareja, el
    índice único lanza asyncpg.UniqueViolationError (lo maneja quien llama).
    """
    valores = [estado.get(c) for c in _CAMPOS_AFINIDAD]
    columnas = ", ".join(_CAMPOS_AFINIDAD)
    marcadores = ", ".join(f"${i}" for i in range(5, 5 + len(_CAMPOS_AFINIDAD)))
    actualizar = ", ".join(f"{c} = EXCLUDED.{c}" for c in _CAMPOS_AFINIDAD)
    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            INSERT INTO afinidad_usuarios (usuario_discord_id, nombre_display, nivel_relacion, historial_eventos, {columnas})
            VALUES ($1, $2, $3, $4, {marcadores})
            ON CONFLICT (usuario_discord_id) DO UPDATE SET
                nombre_display = EXCLUDED.nombre_display,
                nivel_relacion = EXCLUDED.nivel_relacion,
                historial_eventos = EXCLUDED.historial_eventos,
                {actualizar}
            """,
            str(discord_id), nombre[:100], nivel, json.dumps(estado.get("eventos") or [], ensure_ascii=False), *valores,
        )


async def reiniciar_afinidad(pool: asyncpg.Pool, discord_id) -> bool:
    async with pool.acquire() as conn:
        return await conn.execute(
            "DELETE FROM afinidad_usuarios WHERE usuario_discord_id = $1", str(discord_id)
        ) != "DELETE 0"


async def candidatos_iniciativa(pool: asyncpg.Pool, corazones_minimos: float = 45.0) -> list[Dict[str, Any]]:
    """Usuarios con los que Ribby tiene confianza suficiente para escribirles por su cuenta."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM afinidad_usuarios WHERE (corazones >= $1 OR es_pareja) AND ultima_interaccion IS NOT NULL",
            corazones_minimos,
        )
        return [_estado_desde_fila(r) for r in rows]


# ─────────────────────────── Configuración de Ribby (clave/valor) ───────────────────────────

async def config_obtener(pool: asyncpg.Pool, clave: str) -> Optional[str]:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT valor FROM ribby_config WHERE clave = $1", clave)


async def config_guardar(pool: asyncpg.Pool, clave: str, valor: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO ribby_config (clave, valor) VALUES ($1, $2) "
            "ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, fecha = NOW()",
            clave, valor,
        )


async def config_borrar(pool: asyncpg.Pool, clave: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM ribby_config WHERE clave = $1", clave)


async def config_borrar_patron(pool: asyncpg.Pool, patron: str) -> int:
    """Borra las claves que encajen con un patrón LIKE (p. ej. 'quiz:%')."""
    async with pool.acquire() as conn:
        return int((await conn.execute("DELETE FROM ribby_config WHERE clave LIKE $1", patron)).split()[-1])


async def config_con_prefijo(pool: asyncpg.Pool, prefijo: str) -> Dict[str, str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT clave, valor FROM ribby_config WHERE clave LIKE $1", prefijo + "%")
        return {r["clave"]: r["valor"] for r in rows}


async def retroceder_misiones(pool: asyncpg.Pool, discord_id, dias: float) -> None:
    """Modo de pruebas: hace como si las misiones activas se hubieran asignado hace `dias` días."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE misiones_lectura SET fecha_asignada = fecha_asignada - make_interval(secs => $2) "
            "WHERE usuario_discord_id = $1 AND estado = 'activa'",
            str(discord_id), dias * 86400,
        )


# ─────────────────────────── Cumpleaños ───────────────────────────

async def guardar_cumpleanos(pool: asyncpg.Pool, discord_id, dia: int, mes: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO cumpleanos (usuario_discord_id, dia, mes) VALUES ($1, $2, $3) "
            "ON CONFLICT (usuario_discord_id) DO UPDATE SET dia = EXCLUDED.dia, mes = EXCLUDED.mes",
            str(discord_id), dia, mes,
        )


async def cumpleanos_del_dia(pool: asyncpg.Pool, dia: int, mes: int) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT usuario_discord_id FROM cumpleanos WHERE dia = $1 AND mes = $2", dia, mes)
        return [r["usuario_discord_id"] for r in rows]


async def tiene_cumpleanos(pool: asyncpg.Pool, discord_id) -> bool:
    async with pool.acquire() as conn:
        return bool(await conn.fetchval("SELECT 1 FROM cumpleanos WHERE usuario_discord_id = $1", str(discord_id)))


# ─────────────────────────── Reseñas ───────────────────────────

async def guardar_resena(
    pool: asyncpg.Pool, historia_id: int, discord_id, nombre: str, puntuacion: int, texto: str
) -> bool:
    """Guarda (o reemplaza) la reseña de un usuario. Retorna True si es nueva."""
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            """
            INSERT INTO resenas (historia_id, usuario_discord_id, usuario_nombre, puntuacion, texto)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (historia_id, usuario_discord_id) DO UPDATE SET
                puntuacion = EXCLUDED.puntuacion, texto = EXCLUDED.texto,
                usuario_nombre = EXCLUDED.usuario_nombre, fecha = NOW()
            RETURNING (xmax = 0)
            """,
            historia_id, str(discord_id), nombre[:100], puntuacion, texto.strip()[:2000],
        ))


async def resenas_de_historia(pool: asyncpg.Pool, historia_id: int, limite: int = 5) -> list[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM resenas WHERE historia_id = $1 ORDER BY fecha DESC LIMIT $2", historia_id, limite
        )
        return [dict(r) for r in rows]


async def contar_resenas_usuario(pool: asyncpg.Pool, discord_id) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM resenas WHERE usuario_discord_id = $1", str(discord_id)) or 0


# ─────────────────────────── Misiones de lectura ───────────────────────────

async def mision_activa(pool: asyncpg.Pool, discord_id) -> Optional[Dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM misiones_lectura WHERE usuario_discord_id = $1 AND estado = 'activa'", str(discord_id)
        )
        return dict(row) if row else None


async def crear_mision(pool: asyncpg.Pool, discord_id, historia_id: int) -> int:
    """Abandona la misión activa (si había) y crea una nueva."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE misiones_lectura SET estado = 'abandonada' WHERE usuario_discord_id = $1 AND estado = 'activa'",
                str(discord_id),
            )
            return await conn.fetchval(
                "INSERT INTO misiones_lectura (usuario_discord_id, historia_id) VALUES ($1, $2) RETURNING id",
                str(discord_id), historia_id,
            )


async def completar_mision(pool: asyncpg.Pool, mision_id: int) -> bool:
    async with pool.acquire() as conn:
        return await conn.execute(
            "UPDATE misiones_lectura SET estado = 'completada', fecha_completada = NOW() WHERE id = $1 AND estado = 'activa'",
            mision_id,
        ) != "UPDATE 0"


async def contar_misiones_completadas(pool: asyncpg.Pool, discord_id) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM misiones_lectura WHERE usuario_discord_id = $1 AND estado = 'completada'", str(discord_id)
        ) or 0


async def historias_leidas(pool: asyncpg.Pool, discord_id) -> set[int]:
    """Historias que el usuario ya reseñó o completó como misión."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT historia_id FROM resenas WHERE usuario_discord_id = $1 "
            "UNION SELECT historia_id FROM misiones_lectura WHERE usuario_discord_id = $1 AND estado = 'completada'",
            str(discord_id),
        )
        return {r["historia_id"] for r in rows}


# ─────────────────────────── Logros ───────────────────────────

async def logros_de(pool: asyncpg.Pool, discord_id) -> Dict[str, datetime]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT logro, fecha FROM logros_usuarios WHERE usuario_discord_id = $1", str(discord_id))
        return {r["logro"]: r["fecha"] for r in rows}


async def otorgar_logros(pool: asyncpg.Pool, discord_id, claves: list[str]) -> list[str]:
    """Inserta los logros que aún no tenía. Retorna solo los recién desbloqueados."""
    if not claves:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "INSERT INTO logros_usuarios (usuario_discord_id, logro) SELECT $1, unnest($2::text[]) "
            "ON CONFLICT DO NOTHING RETURNING logro",
            str(discord_id), list(claves),
        )
        return [r["logro"] for r in rows]


# ─────────────────────────── Capítulos de la historia de Ribby ───────────────────────────

async def capitulos_leidos(pool: asyncpg.Pool, discord_id) -> Dict[int, int]:
    """{capítulo: elección tomada} de los capítulos que el usuario ya terminó."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT capitulo, eleccion FROM ribby_capitulos WHERE usuario_discord_id = $1", str(discord_id)
        )
        return {r["capitulo"]: r["eleccion"] for r in rows}


async def guardar_capitulo(pool: asyncpg.Pool, discord_id, capitulo: int, eleccion: int) -> bool:
    """Registra la primera lectura de un capítulo. Retorna False si ya lo había leído."""
    async with pool.acquire() as conn:
        res = await conn.execute(
            "INSERT INTO ribby_capitulos (usuario_discord_id, capitulo, eleccion) VALUES ($1, $2, $3) "
            "ON CONFLICT DO NOTHING",
            str(discord_id), capitulo, eleccion,
        )
        return res != "INSERT 0 0"


# ─────────────────────────── Seguimiento de historias ───────────────────────────

async def seguir_historia(pool: asyncpg.Pool, discord_id, historia_id: int) -> bool:
    async with pool.acquire() as conn:
        res = await conn.execute(
            "INSERT INTO seguimientos (usuario_discord_id, historia_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            str(discord_id), historia_id,
        )
        return res != "INSERT 0 0"


async def dejar_de_seguir(pool: asyncpg.Pool, discord_id, historia_id: int) -> bool:
    async with pool.acquire() as conn:
        return await conn.execute(
            "DELETE FROM seguimientos WHERE usuario_discord_id = $1 AND historia_id = $2", str(discord_id), historia_id
        ) != "DELETE 0"


async def interesados_en_historia(pool: asyncpg.Pool, historia_id: int) -> set[str]:
    """Quien la sigue o la tiene como misión de lectura activa."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT usuario_discord_id FROM seguimientos WHERE historia_id = $1 "
            "UNION SELECT usuario_discord_id FROM misiones_lectura WHERE historia_id = $1 AND estado = 'activa'",
            historia_id,
        )
        return {r["usuario_discord_id"] for r in rows}


async def historias_seguidas(pool: asyncpg.Pool, discord_id) -> list[int]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT historia_id FROM seguimientos WHERE usuario_discord_id = $1", str(discord_id))
        return [r["historia_id"] for r in rows]


async def contar_seguidores(pool: asyncpg.Pool, historia_ids: list[int]) -> int:
    if not historia_ids:
        return 0
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(DISTINCT usuario_discord_id) FROM seguimientos WHERE historia_id = ANY($1::int[])",
            historia_ids,
        ) or 0


async def resenas_de_historias(pool: asyncpg.Pool, historia_ids: list[int], limite: int = 3) -> list[Dict[str, Any]]:
    if not historia_ids:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT r.*, b.titulo FROM resenas r JOIN biblioteca_historias b ON b.id = r.historia_id "
            "WHERE r.historia_id = ANY($1::int[]) ORDER BY r.fecha DESC LIMIT $2",
            historia_ids, limite,
        )
        return [dict(r) for r in rows]


async def ids_wattpad_guardados(pool: asyncpg.Pool) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT wattpad_id FROM biblioteca_historias WHERE wattpad_id IS NOT NULL")
        return [r["wattpad_id"] for r in rows]


# ─────────────────────────── Citas con Ribby ───────────────────────────

async def guardar_cita(
    pool: asyncpg.Pool, discord_id, titulo: str, premisa: str, lugar: str, recuerdo: str, desenlace: str, quimica: float,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO citas_ribby (usuario_discord_id, titulo, premisa, lugar, recuerdo, desenlace, quimica) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            str(discord_id), titulo, premisa, lugar, recuerdo, desenlace, quimica,
        )


async def citas_de(pool: asyncpg.Pool, discord_id, limite: int = 6) -> list[Dict[str, Any]]:
    """Últimas citas de un usuario con Ribby (para no repetirlas y para que las recuerde)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT titulo, premisa, lugar, recuerdo AS resumen, desenlace, fecha FROM citas_ribby "
            "WHERE usuario_discord_id = $1 ORDER BY fecha DESC LIMIT $2",
            str(discord_id), limite,
        )
        return [dict(r) for r in rows]


async def premisas_recientes(pool: asyncpg.Pool, limite: int = 40) -> list[str]:
    """Premisas de las últimas citas de todo el servidor: ninguna cita debe parecerse a otra."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT titulo, premisa FROM citas_ribby ORDER BY fecha DESC LIMIT $1", limite
        )
        return [f"{r['titulo']}: {r['premisa'] or ''}" for r in rows]


async def mejores_amigos_ribby(pool: asyncpg.Pool, limite: int = 5) -> list[Dict[str, Any]]:
    """Las personas a las que Ribby tiene más cariño (sin contar a su pareja), para contárselo a su creador."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM afinidad_usuarios WHERE NOT COALESCE(es_pareja, FALSE) AND corazones >= 15 "
            "ORDER BY corazones DESC, total_interacciones DESC LIMIT $1",
            limite,
        )
        return [_estado_desde_fila(r) for r in rows]


async def secretos_descubiertos(pool: asyncpg.Pool) -> Dict[str, tuple[str, datetime]]:
    """{logro de secreto: (quién lo descubrió primero, cuándo)} en todo el servidor."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT ON (logro) logro, usuario_discord_id, fecha FROM logros_usuarios "
            "WHERE logro LIKE 'secreto\\_%' ORDER BY logro, fecha ASC"
        )
        return {r["logro"]: (r["usuario_discord_id"], r["fecha"]) for r in rows}


async def borrar_resena(pool: asyncpg.Pool, historia_id: int, discord_id) -> Optional[Dict[str, Any]]:
    """Borra la reseña de un usuario en una historia. Retorna la reseña borrada (o None si no había)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM resenas WHERE historia_id = $1 AND usuario_discord_id = $2 RETURNING *",
            historia_id, str(discord_id),
        )
        return dict(row) if row else None


async def resenas_de_usuario(pool: asyncpg.Pool, discord_id) -> list[Dict[str, Any]]:
    """Reseñas escritas por un usuario (con el título de la historia), las más recientes primero."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT r.*, b.titulo FROM resenas r JOIN biblioteca_historias b ON b.id = r.historia_id "
            "WHERE r.usuario_discord_id = $1 ORDER BY r.fecha DESC",
            str(discord_id),
        )
        return [dict(r) for r in rows]
