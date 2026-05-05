"""
database.py — Toda la lógica de SQLite para el Bot de Retos Literarios.

Usa aiosqlite para operaciones asíncronas compatibles con discord.py.
Todas las tablas se crean automáticamente al llamar init_db().
"""

from __future__ import annotations

import os
from typing import Dict, Optional

import aiosqlite
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "literario.db")


# ─────────────────────────── Inicialización ───────────────────────────

async def init_db():
    """Crea las tablas si no existen y retorna la conexión."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    db = await aiosqlite.connect(DB_PATH)
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA foreign_keys=ON;")

    await db.executescript("""
        CREATE TABLE IF NOT EXISTS eventos (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre                      TEXT    NOT NULL,
            estado                      TEXT    NOT NULL DEFAULT 'abierto',
            fecha_creacion              TEXT    NOT NULL,
            fecha_cierre                TEXT,
            canal_voz_id                INTEGER,
            canal_envio_id              INTEGER,
            canal_respaldo_id           INTEGER,
            duracion_narracion_minutos  REAL    DEFAULT 0,
            timestamp_inicio_narracion  TEXT
        );

        CREATE TABLE IF NOT EXISTS participantes (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id           INTEGER NOT NULL REFERENCES eventos(id),
            usuario_discord_id  TEXT    NOT NULL,
            usuario_nombre      TEXT    NOT NULL,
            titulo_historia     TEXT,
            url_portada         TEXT,
            url_pdf             TEXT,
            fecha_registro      TEXT    NOT NULL,
            UNIQUE(evento_id, usuario_discord_id)
        );

        CREATE TABLE IF NOT EXISTS asistencia_voz (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id           INTEGER NOT NULL REFERENCES eventos(id),
            usuario_discord_id  TEXT    NOT NULL,
            timestamp_entrada   TEXT    NOT NULL,
            timestamp_salida    TEXT,
            minutos_totales     REAL    DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS votos (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id               INTEGER NOT NULL REFERENCES eventos(id),
            votante_discord_id      TEXT    NOT NULL,
            participante_id         INTEGER NOT NULL REFERENCES participantes(id),
            timestamp_voto          TEXT    NOT NULL,
            UNIQUE(evento_id, votante_discord_id)
        );

        CREATE TABLE IF NOT EXISTS habilitados_voto (
            evento_id           INTEGER NOT NULL REFERENCES eventos(id),
            usuario_discord_id  TEXT    NOT NULL,
            minutos_presencia   REAL    DEFAULT 0,
            PRIMARY KEY (evento_id, usuario_discord_id)
        );
    """)

    await db.commit()
    return db


def _now() -> str:
    """Timestamp UTC en formato ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────── Eventos ───────────────────────────

async def crear_evento(db: aiosqlite.Connection, nombre: str) -> int:
    """Crea un evento y retorna su ID."""
    cursor = await db.execute(
        "INSERT INTO eventos (nombre, fecha_creacion) VALUES (?, ?)",
        (nombre, _now()),
    )
    await db.commit()
    return cursor.lastrowid


async def obtener_evento_activo(db: aiosqlite.Connection):
    """Retorna el evento que NO esté cerrado (el activo). Solo uno a la vez."""
    async with db.execute(
        "SELECT * FROM eventos WHERE estado != 'cerrado' ORDER BY id DESC LIMIT 1"
    ) as cursor:
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))


async def obtener_evento_por_id(db: aiosqlite.Connection, evento_id: int):
    """Retorna un evento por su ID."""
    async with db.execute("SELECT * FROM eventos WHERE id = ?", (evento_id,)) as cursor:
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))


async def configurar_evento(
    db: aiosqlite.Connection,
    evento_id: int,
    canal_voz_id: int,
    canal_envio_id: int,
    canal_respaldo_id: Optional[int] = None,
):
    """Asocia canales al evento activo."""
    await db.execute(
        """UPDATE eventos
           SET canal_voz_id = ?, canal_envio_id = ?, canal_respaldo_id = ?
           WHERE id = ?""",
        (canal_voz_id, canal_envio_id, canal_respaldo_id, evento_id),
    )
    await db.commit()


async def cambiar_estado_evento(db: aiosqlite.Connection, evento_id: int, nuevo_estado: str):
    """Cambia el estado de un evento (abierto, narrando, votando, cerrado)."""
    extra = ""
    params: list = [nuevo_estado]

    if nuevo_estado == "narrando":
        extra = ", timestamp_inicio_narracion = ?"
        params.append(_now())
    elif nuevo_estado == "cerrado":
        extra = ", fecha_cierre = ?"
        params.append(_now())

    params.append(evento_id)
    await db.execute(
        f"UPDATE eventos SET estado = ?{extra} WHERE id = ?",
        params,
    )
    await db.commit()


async def guardar_duracion_narracion(db: aiosqlite.Connection, evento_id: int, minutos: float):
    """Guarda la duración total de la narración en minutos."""
    await db.execute(
        "UPDATE eventos SET duracion_narracion_minutos = ? WHERE id = ?",
        (minutos, evento_id),
    )
    await db.commit()


async def obtener_eventos_cerrados(db: aiosqlite.Connection):
    """Retorna todos los eventos cerrados para el historial."""
    async with db.execute(
        "SELECT * FROM eventos WHERE estado = 'cerrado' ORDER BY fecha_cierre DESC"
    ) as cursor:
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) async for row in cursor]


# ─────────────────────────── Participantes ───────────────────────────

async def registrar_participante(
    db: aiosqlite.Connection,
    evento_id: int,
    usuario_discord_id: str,
    usuario_nombre: str,
    titulo_historia: Optional[str] = None,
) -> int:
    """Registra un participante. Retorna su ID."""
    cursor = await db.execute(
        """INSERT INTO participantes
           (evento_id, usuario_discord_id, usuario_nombre, titulo_historia, fecha_registro)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(evento_id, usuario_discord_id)
           DO UPDATE SET titulo_historia = COALESCE(excluded.titulo_historia, titulo_historia),
                         usuario_nombre  = excluded.usuario_nombre""",
        (evento_id, usuario_discord_id, usuario_nombre, titulo_historia, _now()),
    )
    await db.commit()
    return cursor.lastrowid


async def obtener_participantes(db: aiosqlite.Connection, evento_id: int):
    """Retorna la lista de participantes de un evento."""
    async with db.execute(
        "SELECT * FROM participantes WHERE evento_id = ? ORDER BY id",
        (evento_id,),
    ) as cursor:
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) async for row in cursor]


async def obtener_participante_por_usuario(
    db: aiosqlite.Connection, evento_id: int, usuario_discord_id: str
):
    """Busca un participante específico."""
    async with db.execute(
        "SELECT * FROM participantes WHERE evento_id = ? AND usuario_discord_id = ?",
        (evento_id, usuario_discord_id),
    ) as cursor:
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))


async def actualizar_pdf(db: aiosqlite.Connection, participante_id: int, url_pdf: str):
    """Actualiza la URL del PDF de un participante."""
    await db.execute(
        "UPDATE participantes SET url_pdf = ? WHERE id = ?",
        (url_pdf, participante_id),
    )
    await db.commit()


async def actualizar_portada(db: aiosqlite.Connection, participante_id: int, url_portada: str):
    """Actualiza la URL de la portada de un participante."""
    await db.execute(
        "UPDATE participantes SET url_portada = ? WHERE id = ?",
        (url_portada, participante_id),
    )
    await db.commit()


# ─────────────────────────── Asistencia de voz ───────────────────────────

async def registrar_entrada_voz(
    db: aiosqlite.Connection, evento_id: int, usuario_discord_id: str
):
    """Registra la entrada de un usuario al canal de voz."""
    await db.execute(
        "INSERT INTO asistencia_voz (evento_id, usuario_discord_id, timestamp_entrada) VALUES (?, ?, ?)",
        (evento_id, usuario_discord_id, _now()),
    )
    await db.commit()


async def registrar_salida_voz(
    db: aiosqlite.Connection, evento_id: int, usuario_discord_id: str
):
    """Registra la salida y calcula los minutos de permanencia."""
    ahora = _now()
    # Buscar el registro abierto más reciente
    async with db.execute(
        """SELECT id, timestamp_entrada FROM asistencia_voz
           WHERE evento_id = ? AND usuario_discord_id = ? AND timestamp_salida IS NULL
           ORDER BY id DESC LIMIT 1""",
        (evento_id, usuario_discord_id),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        return  # No había entrada abierta

    reg_id, ts_entrada = row
    dt_entrada = datetime.fromisoformat(ts_entrada)
    dt_salida = datetime.fromisoformat(ahora)
    minutos = (dt_salida - dt_entrada).total_seconds() / 60.0

    await db.execute(
        "UPDATE asistencia_voz SET timestamp_salida = ?, minutos_totales = ? WHERE id = ?",
        (ahora, round(minutos, 2), reg_id),
    )
    await db.commit()


async def cerrar_sesiones_abiertas(db: aiosqlite.Connection, evento_id: int):
    """Cierra todas las sesiones de voz que aún estén abiertas (usuario sigue en canal)."""
    ahora = _now()
    async with db.execute(
        """SELECT id, timestamp_entrada, usuario_discord_id FROM asistencia_voz
           WHERE evento_id = ? AND timestamp_salida IS NULL""",
        (evento_id,),
    ) as cursor:
        abiertas = await cursor.fetchall()

    for reg_id, ts_entrada, _ in abiertas:
        dt_entrada = datetime.fromisoformat(ts_entrada)
        dt_salida = datetime.fromisoformat(ahora)
        minutos = (dt_salida - dt_entrada).total_seconds() / 60.0
        await db.execute(
            "UPDATE asistencia_voz SET timestamp_salida = ?, minutos_totales = ? WHERE id = ?",
            (ahora, round(minutos, 2), reg_id),
        )

    await db.commit()


async def calcular_asistencia_total(db: aiosqlite.Connection, evento_id: int):
    """Retorna un dict {usuario_discord_id: minutos_totales} con el tiempo acumulado."""
    async with db.execute(
        """SELECT usuario_discord_id, SUM(minutos_totales) as total
           FROM asistencia_voz WHERE evento_id = ?
           GROUP BY usuario_discord_id""",
        (evento_id,),
    ) as cursor:
        return {row[0]: row[1] async for row in cursor}


# ─────────────────────────── Habilitados para votar ───────────────────────────

async def guardar_habilitados(
    db: aiosqlite.Connection, evento_id: int, habilitados: Dict[str, float]
):
    """Guarda la lista de usuarios habilitados para votar."""
    for uid, minutos in habilitados.items():
        await db.execute(
            """INSERT OR REPLACE INTO habilitados_voto
               (evento_id, usuario_discord_id, minutos_presencia) VALUES (?, ?, ?)""",
            (evento_id, uid, minutos),
        )
    await db.commit()


async def esta_habilitado(
    db: aiosqlite.Connection, evento_id: int, usuario_discord_id: str
) -> bool:
    """Verifica si un usuario está habilitado para votar."""
    async with db.execute(
        "SELECT 1 FROM habilitados_voto WHERE evento_id = ? AND usuario_discord_id = ?",
        (evento_id, usuario_discord_id),
    ) as cursor:
        return await cursor.fetchone() is not None


# ─────────────────────────── Votos ───────────────────────────

async def registrar_voto(
    db: aiosqlite.Connection, evento_id: int, votante_discord_id: str, participante_id: int
) -> bool:
    """Registra un voto. Retorna True si se guardó, False si ya existía."""
    try:
        await db.execute(
            """INSERT INTO votos (evento_id, votante_discord_id, participante_id, timestamp_voto)
               VALUES (?, ?, ?, ?)""",
            (evento_id, votante_discord_id, participante_id, _now()),
        )
        await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def ya_voto(db: aiosqlite.Connection, evento_id: int, votante_discord_id: str) -> bool:
    """Verifica si el usuario ya votó en este evento."""
    async with db.execute(
        "SELECT 1 FROM votos WHERE evento_id = ? AND votante_discord_id = ?",
        (evento_id, votante_discord_id),
    ) as cursor:
        return await cursor.fetchone() is not None


async def obtener_resultados_votacion(db: aiosqlite.Connection, evento_id: int):
    """Retorna los resultados de la votación ordenados por cantidad de votos."""
    async with db.execute(
        """SELECT p.id, p.usuario_nombre, p.titulo_historia, COUNT(v.id) as total_votos
           FROM participantes p
           LEFT JOIN votos v ON v.participante_id = p.id AND v.evento_id = p.evento_id
           WHERE p.evento_id = ?
           GROUP BY p.id
           ORDER BY total_votos DESC""",
        (evento_id,),
    ) as cursor:
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) async for row in cursor]
