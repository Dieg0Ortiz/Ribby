"""
database.py — Lógica de base de datos PostgreSQL (Supabase) para Ribby.

Usa asyncpg para operaciones asíncronas de altísimo rendimiento.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Any

import asyncpg
from datetime import datetime, timezone

import config

log = logging.getLogger("bot-literario.database")

# ─────────────────────────── Inicialización ───────────────────────────

async def init_db() -> asyncpg.Pool:
    """Crea y retorna un pool de conexiones a PostgreSQL."""
    if not config.DATABASE_URL:
        log.warning("DATABASE_URL no está configurada. El bot podría no funcionar correctamente.")
        # Retornamos un objeto dummy o lanzamos error. Mejor intentar conectar si existe.
        pass

    log.info("Conectando a PostgreSQL (Supabase)...")
    try:
        # statement_cache_size=0 es necesario para que funcione con el "Transaction Pooler" de Supabase
        pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=10, statement_cache_size=0)
        return pool
    except Exception as e:
        log.error(f"Error conectando a la base de datos: {e}")
        raise


def _now() -> datetime:
    """Retorna el timestamp UTC actual como objeto datetime."""
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    """Retorna el timestamp UTC actual en formato ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────── Eventos ───────────────────────────

async def crear_evento(pool: asyncpg.Pool, nombre: str) -> int:
    """Crea un evento y retorna su ID."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO eventos (nombre, fecha_creacion) VALUES ($1, $2) RETURNING id",
            nombre, _now_iso()
        )


async def obtener_evento_activo(pool: asyncpg.Pool) -> Optional[Dict[str, Any]]:
    """Retorna el evento que NO esté cerrado (el activo). Solo uno a la vez."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM eventos WHERE estado != 'cerrado' ORDER BY id DESC LIMIT 1"
        )
        return dict(row) if row else None


async def obtener_evento_por_id(pool: asyncpg.Pool, evento_id: int) -> Optional[Dict[str, Any]]:
    """Obtiene información de un evento por ID."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM eventos WHERE id = $1", evento_id)
        return dict(row) if row else None


async def configurar_canales_evento(
    pool: asyncpg.Pool,
    evento_id: int,
    voz_id: int,
    envio_id: int,
    respaldo_id: int
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE eventos SET canal_voz_id = $1, canal_envio_id = $2, canal_respaldo_id = $3 WHERE id = $4",
            voz_id, envio_id, respaldo_id, evento_id
        )


async def actualizar_estado_evento(pool: asyncpg.Pool, evento_id: int, estado: str) -> None:
    async with pool.acquire() as conn:
        query = "UPDATE eventos SET estado = $1"
        args = [estado]
        if estado == "cerrado":
            query += ", fecha_cierre = $2"
            args.append(_now_iso())
        
        query += f" WHERE id = ${len(args) + 1}"
        args.append(evento_id)
        
        await conn.execute(query, *args)


# ─────────────────────────── Narración ───────────────────────────

async def iniciar_narracion(pool: asyncpg.Pool, evento_id: int, sesion: int) -> int:
    """Registra el inicio de una sesión de narración y retorna su ID."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO narraciones (evento_id, numero_sesion, timestamp_inicio) VALUES ($1, $2, $3) RETURNING id",
            evento_id, sesion, _now_iso()
        )


async def obtener_narracion_activa(pool: asyncpg.Pool, evento_id: int) -> Optional[Dict[str, Any]]:
    """Obtiene la narración en curso (sin timestamp_fin) para el evento."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM narraciones WHERE evento_id = $1 AND timestamp_fin IS NULL ORDER BY numero_sesion DESC LIMIT 1",
            evento_id
        )
        return dict(row) if row else None


async def detener_narracion(pool: asyncpg.Pool, narracion_id: int) -> None:
    """Cierra la narración actual calculando su duración en minutos."""
    now_dt = _now()
    now_iso = now_dt.isoformat()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT timestamp_inicio, evento_id FROM narraciones WHERE id = $1", narracion_id)
        if not row:
            return
            
        t_inicio = datetime.fromisoformat(row["timestamp_inicio"])
        t_fin = now_dt
        duracion_min = (t_fin - t_inicio).total_seconds() / 60.0

        await conn.execute(
            "UPDATE narraciones SET timestamp_fin = $1, duracion_minutos = $2 WHERE id = $3",
            now_iso, duracion_min, narracion_id
        )

        # Actualizar total en evento
        await conn.execute(
            "UPDATE eventos SET duracion_narracion_minutos = duracion_narracion_minutos + $1 WHERE id = $2",
            duracion_min, row["evento_id"]
        )


# ─────────────────────────── Participantes ───────────────────────────

async def registrar_participante(
    pool: asyncpg.Pool,
    evento_id: int,
    discord_id: int,
    nombre: str,
    titulo: Optional[str] = None,
    url_portada: Optional[str] = None,
    url_pdf: Optional[str] = None
) -> int:
    """Registra o actualiza un participante."""
    discord_id_str = str(discord_id)
    async with pool.acquire() as conn:
        # PostgreSQL UPSERT logic
        query = """
            INSERT INTO participantes 
                (evento_id, usuario_discord_id, usuario_nombre, titulo_historia, url_portada, url_pdf, fecha_registro)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (evento_id, usuario_discord_id) 
            DO UPDATE SET 
                usuario_nombre = EXCLUDED.usuario_nombre,
                titulo_historia = EXCLUDED.titulo_historia,
                url_portada = EXCLUDED.url_portada,
                url_pdf = EXCLUDED.url_pdf,
                fecha_registro = EXCLUDED.fecha_registro
            RETURNING id
        """
        return await conn.fetchval(
            query,
            evento_id, discord_id_str, nombre, titulo, url_portada, url_pdf, _now_iso()
        )


async def obtener_participante(pool: asyncpg.Pool, evento_id: int, discord_id: int) -> Optional[Dict[str, Any]]:
    discord_id_str = str(discord_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM participantes WHERE evento_id = $1 AND usuario_discord_id = $2",
            evento_id, discord_id_str
        )
        return dict(row) if row else None


async def obtener_todos_participantes(pool: asyncpg.Pool, evento_id: int) -> list[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM participantes WHERE evento_id = $1 ORDER BY id ASC",
            evento_id
        )
        return [dict(r) for r in rows]


# ─────────────────────────── Asistencia en Voz ───────────────────────────

async def registrar_entrada_voz(pool: asyncpg.Pool, evento_id: int, discord_id, narracion_id=None) -> None:
    """Registra cuándo entra un usuario al canal de voz."""
    discord_id_str = str(discord_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM asistencia_voz WHERE evento_id = $1 AND usuario_discord_id = $2 AND timestamp_salida IS NULL",
            evento_id, discord_id_str
        )
        if not row:
            await conn.execute(
                "INSERT INTO asistencia_voz (evento_id, narracion_id, usuario_discord_id, timestamp_entrada) VALUES ($1, $2, $3, $4)",
                evento_id, narracion_id, discord_id_str, _now_iso()
            )


async def registrar_salida_voz(pool: asyncpg.Pool, evento_id: int, discord_id, narracion_id=None) -> None:
    """Calcula y guarda el tiempo que estuvo conectado."""
    discord_id_str = str(discord_id)
    now_dt = _now()
    now_iso = now_dt.isoformat()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, timestamp_entrada FROM asistencia_voz WHERE evento_id = $1 AND usuario_discord_id = $2 AND timestamp_salida IS NULL ORDER BY id DESC LIMIT 1",
            evento_id, discord_id_str
        )
        if row:
            t_ent = datetime.fromisoformat(row["timestamp_entrada"])
            t_sal = now_dt
            mins = (t_sal - t_ent).total_seconds() / 60.0

            await conn.execute(
                "UPDATE asistencia_voz SET timestamp_salida = $1, minutos_totales = $2 WHERE id = $3",
                now_iso, mins, row["id"]
            )


async def obtener_minutos_asistencia(pool: asyncpg.Pool, evento_id: int, discord_id: int) -> float:
    """Suma total de minutos de un usuario en un evento."""
    discord_id_str = str(discord_id)
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT SUM(minutos_totales) FROM asistencia_voz WHERE evento_id = $1 AND usuario_discord_id = $2",
            evento_id, discord_id_str
        )
        return float(val) if val else 0.0


# ─────────────────────────── Estadísticas Globales ───────────────────────────

async def contar_libros_biblioteca(pool: asyncpg.Pool) -> int:
    """Cuenta el total histórico de cuentos/libros registrados en todas las veladas."""
    # Como el usuario usa esto incluso cuando el bot arranca, verificamos que el pool exista
    if not pool:
        return 0
    try:
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT COUNT(*) FROM participantes")
            return val or 0
    except Exception as e:
        log.error(f"Error contando libros: {e}")
        return 0


async def contar_veladas_realizadas(pool: asyncpg.Pool) -> int:
    """Cuenta el total histórico de eventos cerrados."""
    if not pool:
        return 0
    try:
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT COUNT(*) FROM eventos")
            return val or 0
    except Exception as e:
        log.error(f"Error contando veladas: {e}")
        return 0


# ─────────────────────────── Votación ───────────────────────────

async def registrar_voto(pool: asyncpg.Pool, evento_id: int, votante_discord_id, participante_id: int, es_valido: bool = True) -> bool:
    votante_str = str(votante_discord_id)
    es_valido_int = 1 if es_valido else 0
    async with pool.acquire() as conn:
        # Check if already voted
        existing = await conn.fetchrow(
            "SELECT id FROM votos WHERE evento_id = $1 AND votante_discord_id = $2",
            evento_id, votante_str
        )
        if existing:
            return False  # Already voted
        await conn.execute(
            "INSERT INTO votos (evento_id, votante_discord_id, participante_id, timestamp_voto, es_valido) VALUES ($1, $2, $3, $4, $5)",
            evento_id, votante_str, participante_id, _now_iso(), es_valido_int
        )
        return True


async def obtener_voto_usuario(pool: asyncpg.Pool, evento_id: int, votante_discord_id: int) -> Optional[int]:
    votante_str = str(votante_discord_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT participante_id FROM votos WHERE evento_id = $1 AND votante_discord_id = $2 AND es_valido = 1",
            evento_id, votante_str
        )
        return row["participante_id"] if row else None


async def anular_voto(pool: asyncpg.Pool, evento_id: int, votante_discord_id: int) -> bool:
    votante_str = str(votante_discord_id)
    async with pool.acquire() as conn:
        res = await conn.execute(
            "UPDATE votos SET es_valido = 0 WHERE evento_id = $1 AND votante_discord_id = $2",
            evento_id, votante_str
        )
        # res looks like "UPDATE 1"
        return res != "UPDATE 0"


async def contar_votos(pool: asyncpg.Pool, evento_id: int) -> list[Dict[str, Any]]:
    """
    Retorna lista de participantes ordenados por votos (de mayor a menor).
    Formato: [{'participante_id': 1, 'nombre': 'Juan', 'votos': 5}, ...]
    """
    async with pool.acquire() as conn:
        query = """
            SELECT p.id as participante_id, p.usuario_nombre as nombre, COUNT(v.id) as votos
            FROM participantes p
            LEFT JOIN votos v ON p.id = v.participante_id AND v.es_valido = 1
            WHERE p.evento_id = $1
            GROUP BY p.id, p.usuario_nombre
            ORDER BY votos DESC, p.id ASC
        """
        rows = await conn.fetch(query, evento_id)
        return [dict(r) for r in rows]


# ─────────────────────────── Control de Fraude ───────────────────────────

async def habilitar_votante(pool: asyncpg.Pool, evento_id: int, discord_id: int, minutos: float) -> None:
    discord_id_str = str(discord_id)
    async with pool.acquire() as conn:
        query = """
            INSERT INTO habilitados_voto (evento_id, usuario_discord_id, minutos_presencia)
            VALUES ($1, $2, $3)
            ON CONFLICT (evento_id, usuario_discord_id) 
            DO UPDATE SET minutos_presencia = EXCLUDED.minutos_presencia
        """
        await conn.execute(query, evento_id, discord_id_str, minutos)


async def incrementar_documentos_descargados(pool: asyncpg.Pool, evento_id: int, discord_id: int, participante_id: int) -> None:
    """Registra la descarga de un documento y aumenta el contador del usuario si es un documento nuevo."""
    discord_id_str = str(discord_id)
    async with pool.acquire() as conn:
        # Verificar si ya lo descargó
        row = await conn.fetchrow(
            "SELECT 1 FROM descargas_documentos WHERE evento_id = $1 AND usuario_discord_id = $2 AND participante_id = $3",
            evento_id, discord_id_str, participante_id
        )
        if not row:
            # Registrar descarga
            await conn.execute(
                "INSERT INTO descargas_documentos (evento_id, usuario_discord_id, participante_id, timestamp_descarga) VALUES ($1, $2, $3, $4)",
                evento_id, discord_id_str, participante_id, _now_iso()
            )
            # Incrementar contador general
            await conn.execute(
                """
                INSERT INTO habilitados_voto (evento_id, usuario_discord_id, documentos_descargados)
                VALUES ($1, $2, 1)
                ON CONFLICT (evento_id, usuario_discord_id) 
                DO UPDATE SET documentos_descargados = habilitados_voto.documentos_descargados + 1
                """,
                evento_id, discord_id_str
            )


async def obtener_estatus_votante(pool: asyncpg.Pool, evento_id: int, discord_id: int) -> Optional[Dict[str, Any]]:
    discord_id_str = str(discord_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT minutos_presencia, documentos_descargados FROM habilitados_voto WHERE evento_id = $1 AND usuario_discord_id = $2",
            evento_id, discord_id_str
        )
        return dict(row) if row else None


# ─────────────────────────── Historial de Eventos ───────────────────────────

async def obtener_ultimos_eventos(pool: asyncpg.Pool, limite: int = 5) -> list[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM eventos WHERE estado = 'cerrado' ORDER BY id DESC LIMIT $1",
            limite
        )
        return [dict(r) for r in rows]


# ─────────────────── Funciones de compatibilidad con Cogs ───────────────────

# Alias: los cogs usan este nombre
async def cambiar_estado_evento(pool, evento_id, estado):
    return await actualizar_estado_evento(pool, evento_id, estado)


async def obtener_participante_por_usuario(pool, evento_id, discord_id):
    return await obtener_participante(pool, evento_id, discord_id)


async def obtener_participantes(pool, evento_id):
    return await obtener_todos_participantes(pool, evento_id)


async def actualizar_pdf(pool, participante_id, url):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE participantes SET url_pdf = $1 WHERE id = $2",
            url, participante_id
        )


async def actualizar_portada(pool, participante_id, url):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE participantes SET url_portada = $1 WHERE id = $2",
            url, participante_id
        )


async def crear_narracion(pool, evento_id):
    """Crea una nueva narración. Retorna (narracion_id, numero_sesion)."""
    async with pool.acquire() as conn:
        # Obtener el número de sesión siguiente
        val = await conn.fetchval(
            "SELECT COALESCE(MAX(numero_sesion), 0) + 1 FROM narraciones WHERE evento_id = $1",
            evento_id
        )
        sesion = val or 1
        nid = await conn.fetchval(
            "INSERT INTO narraciones (evento_id, numero_sesion, timestamp_inicio) VALUES ($1, $2, $3) RETURNING id",
            evento_id, sesion, _now_iso()
        )
        return nid, sesion


async def obtener_narraciones(pool, evento_id):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM narraciones WHERE evento_id = $1 ORDER BY numero_sesion ASC",
            evento_id
        )
        return [dict(r) for r in rows]


async def cerrar_narracion_activa(pool, evento_id):
    """Cierra la narración activa. Retorna (narracion_id, duracion_min, numero_sesion) o None."""
    now_dt = _now()
    now_iso = now_dt.isoformat()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, timestamp_inicio, numero_sesion FROM narraciones WHERE evento_id = $1 AND timestamp_fin IS NULL ORDER BY numero_sesion DESC LIMIT 1",
            evento_id
        )
        if not row:
            return None
        t_inicio = datetime.fromisoformat(row["timestamp_inicio"])
        t_fin = now_dt
        duracion_min = (t_fin - t_inicio).total_seconds() / 60.0
        await conn.execute(
            "UPDATE narraciones SET timestamp_fin = $1, duracion_minutos = $2 WHERE id = $3",
            now_iso, duracion_min, row["id"]
        )
        await conn.execute(
            "UPDATE eventos SET duracion_narracion_minutos = duracion_narracion_minutos + $1 WHERE id = $2",
            duracion_min, evento_id
        )
        return row["id"], duracion_min, row["numero_sesion"]


async def cerrar_sesiones_abiertas(pool, evento_id):
    """Cierra todas las sesiones de voz que no tengan timestamp_salida."""
    now_dt = _now()
    now_iso = now_dt.isoformat()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, timestamp_entrada FROM asistencia_voz WHERE evento_id = $1 AND timestamp_salida IS NULL",
            evento_id
        )
        for row in rows:
            t_ent = datetime.fromisoformat(row["timestamp_entrada"])
            t_sal = now_dt
            mins = (t_sal - t_ent).total_seconds() / 60.0
            await conn.execute(
                "UPDATE asistencia_voz SET timestamp_salida = $1, minutos_totales = $2 WHERE id = $3",
                now_iso, mins, row["id"]
            )


async def calcular_asistencia_total(pool, evento_id) -> Dict[str, float]:
    """Retorna {discord_id: minutos_totales} para el evento."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT usuario_discord_id, SUM(minutos_totales) as total FROM asistencia_voz WHERE evento_id = $1 GROUP BY usuario_discord_id",
            evento_id
        )
        return {r["usuario_discord_id"]: float(r["total"] or 0) for r in rows}


async def guardar_duracion_total_narraciones(pool, evento_id):
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT COALESCE(SUM(duracion_minutos), 0) FROM narraciones WHERE evento_id = $1",
            evento_id
        )
        await conn.execute(
            "UPDATE eventos SET duracion_narracion_minutos = $1 WHERE id = $2",
            float(val or 0), evento_id
        )


async def contar_documentos_subidos(pool, evento_id) -> int:
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT COUNT(*) FROM participantes WHERE evento_id = $1 AND url_pdf IS NOT NULL",
            evento_id
        )
        return val or 0


async def calcular_descargas_por_usuario(pool, evento_id) -> Dict[str, int]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT usuario_discord_id, COUNT(*) as total FROM descargas_documentos WHERE evento_id = $1 GROUP BY usuario_discord_id",
            evento_id
        )
        return {r["usuario_discord_id"]: int(r["total"]) for r in rows}


async def guardar_habilitados(pool, evento_id, habilitados_dict):
    async with pool.acquire() as conn:
        for uid, stats in habilitados_dict.items():
            await conn.execute(
                """INSERT INTO habilitados_voto (evento_id, usuario_discord_id, minutos_presencia, documentos_descargados)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (evento_id, usuario_discord_id)
                DO UPDATE SET minutos_presencia = EXCLUDED.minutos_presencia, documentos_descargados = EXCLUDED.documentos_descargados""",
                evento_id, uid, stats.get("minutos", 0), stats.get("descargas", 0)
            )


async def ya_voto(pool, evento_id, discord_id) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM votos WHERE evento_id = $1 AND votante_discord_id = $2",
            evento_id, str(discord_id)
        )
        return row is not None


async def esta_habilitado(pool, evento_id, discord_id) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM habilitados_voto WHERE evento_id = $1 AND usuario_discord_id = $2",
            evento_id, str(discord_id)
        )
        return row is not None


async def registrar_descarga(pool, evento_id, discord_id, participante_id):
    return await incrementar_documentos_descargados(pool, evento_id, discord_id, participante_id)


async def obtener_resultados_votacion(pool, evento_id) -> list[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT p.usuario_nombre, p.titulo_historia, COUNT(v.id) as total_votos
            FROM participantes p
            LEFT JOIN votos v ON p.id = v.participante_id AND v.es_valido = 1
            WHERE p.evento_id = $1
            GROUP BY p.id, p.usuario_nombre, p.titulo_historia
            ORDER BY total_votos DESC, p.id ASC""",
            evento_id
        )
        return [dict(r) for r in rows]


async def contar_votos_totales(pool, evento_id) -> Dict[str, int]:
    async with pool.acquire() as conn:
        validos = await conn.fetchval(
            "SELECT COUNT(*) FROM votos WHERE evento_id = $1 AND es_valido = 1", evento_id
        )
        nulos = await conn.fetchval(
            "SELECT COUNT(*) FROM votos WHERE evento_id = $1 AND es_valido = 0", evento_id
        )
        return {"validos": validos or 0, "nulos": nulos or 0}


async def obtener_votos_nulos(pool, evento_id) -> list[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT v.votante_discord_id, p.titulo_historia
            FROM votos v
            JOIN participantes p ON v.participante_id = p.id
            WHERE v.evento_id = $1 AND v.es_valido = 0""",
            evento_id
        )
        return [dict(r) for r in rows]


# ─────────────────────────── Documentos Persistentes ───────────────────────────

async def guardar_documento(
    pool: asyncpg.Pool,
    participante_id: int,
    evento_id: int,
    usuario_discord_id: str,
    tipo: str,  # 'pdf' | 'portada'
    url_discord: str,
    url_respaldo: str = None,
    nombre_archivo: str = None,
    content_type: str = None,
    tamanio_bytes: int = None,
) -> str:
    """
    Inserta o actualiza el documento de un participante.
    Incrementa el número de versión en cada actualización.
    Retorna la url_activa (respaldo si existe, discord si no).
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO documentos_participantes
                (participante_id, evento_id, usuario_discord_id, tipo,
                 url_discord, url_respaldo, nombre_archivo, content_type,
                 tamanio_bytes, version, fecha_subida)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 1, NOW())
            ON CONFLICT (participante_id, tipo)
            DO UPDATE SET
                url_discord       = EXCLUDED.url_discord,
                url_respaldo      = COALESCE(EXCLUDED.url_respaldo, documentos_participantes.url_respaldo),
                nombre_archivo    = COALESCE(EXCLUDED.nombre_archivo, documentos_participantes.nombre_archivo),
                content_type      = COALESCE(EXCLUDED.content_type, documentos_participantes.content_type),
                tamanio_bytes     = COALESCE(EXCLUDED.tamanio_bytes, documentos_participantes.tamanio_bytes),
                version           = documentos_participantes.version + 1,
                fecha_actualizacion = NOW()
            RETURNING url_activa
            """,
            participante_id, evento_id, usuario_discord_id, tipo,
            url_discord, url_respaldo, nombre_archivo, content_type, tamanio_bytes,
        )

        url_activa = row["url_activa"] if row else url_respaldo or url_discord

        # Sincronizar con la tabla participantes para compatibilidad con código existente
        if tipo == "pdf":
            await conn.execute(
                "UPDATE participantes SET url_pdf = $1 WHERE id = $2",
                url_activa, participante_id,
            )
        elif tipo == "portada":
            await conn.execute(
                "UPDATE participantes SET url_portada = $1 WHERE id = $2",
                url_activa, participante_id,
            )

        return url_activa


async def obtener_documento(
    pool: asyncpg.Pool,
    participante_id: int,
    tipo: str,  # 'pdf' | 'portada'
) -> Optional[Dict[str, Any]]:
    """Retorna el documento activo de un participante."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT url_activa, url_discord, url_respaldo,
                   nombre_archivo, version, fecha_subida
            FROM documentos_participantes
            WHERE participante_id = $1 AND tipo = $2
            """,
            participante_id, tipo,
        )
        return dict(row) if row else None


async def obtener_documentos_evento(
    pool: asyncpg.Pool,
    evento_id: int,
    tipo: str = None,  # None = todos, 'pdf' | 'portada'
) -> list[Dict[str, Any]]:
    """Retorna todos los documentos de un evento, opcionalmente filtrados por tipo."""
    async with pool.acquire() as conn:
        if tipo:
            rows = await conn.fetch(
                """
                SELECT * FROM v_documentos_completos
                WHERE evento_id = $1 AND tipo = $2
                ORDER BY participante_id ASC
                """,
                evento_id, tipo,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM v_documentos_completos
                WHERE evento_id = $1
                ORDER BY participante_id ASC, tipo ASC
                """,
                evento_id,
            )
        return [dict(r) for r in rows]


async def actualizar_url_respaldo_documento(
    pool: asyncpg.Pool,
    participante_id: int,
    tipo: str,
    url_respaldo: str,
) -> None:
    """
    Actualiza solo la URL de respaldo de un documento ya guardado.
    Útil cuando el reenvío al canal privado tarda o falla inicialmente.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE documentos_participantes
            SET url_respaldo = $1, fecha_actualizacion = NOW()
            WHERE participante_id = $2 AND tipo = $3
            """,
            url_respaldo, participante_id, tipo,
        )
        # Sincronizar participantes con la nueva url_activa
        row = await conn.fetchrow(
            "SELECT url_activa FROM documentos_participantes WHERE participante_id = $1 AND tipo = $2",
            participante_id, tipo,
        )
        if row:
            col = "url_pdf" if tipo == "pdf" else "url_portada"
            await conn.execute(
                f"UPDATE participantes SET {col} = $1 WHERE id = $2",
                row["url_activa"], participante_id,
            )


async def sincronizar_urls_desde_documentos(pool: asyncpg.Pool, evento_id: int) -> int:
    """
    Utilidad de mantenimiento: recorre documentos_participantes y actualiza
    la tabla participantes con las url_activa más recientes.
    Útil para ejecutar después de un reinicio si hay desincronización.
    Retorna el número de filas actualizadas.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT participante_id, tipo, url_activa FROM documentos_participantes WHERE evento_id = $1",
            evento_id,
        )
        updated = 0
        for row in rows:
            if not row["url_activa"]:
                continue
            col = "url_pdf" if row["tipo"] == "pdf" else "url_portada"
            result = await conn.execute(
                f"UPDATE participantes SET {col} = $1 WHERE id = $2",
                row["url_activa"], row["participante_id"],
            )
            if result != "UPDATE 0":
                updated += 1
        return updated

# ─────────────────────────── Memoria de Ribby ───────────────────────────

async def obtener_memoria_usuario(pool: asyncpg.Pool, discord_id: int) -> Optional[Dict[str, Any]]:
    """Carga el resumen de memoria de un usuario. Retorna None si no existe."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ribby_memoria WHERE usuario_discord_id = $1",
            str(discord_id)
        )
        return dict(row) if row else None


async def guardar_memoria_usuario(
    pool: asyncpg.Pool,
    discord_id: int,
    resumen: str,
    mood: str,
    interacciones: int,
) -> None:
    """Crea o actualiza el resumen de memoria de un usuario (upsert)."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ribby_memoria (usuario_discord_id, resumen, mood, interacciones, ultima_actualizacion)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (usuario_discord_id)
            DO UPDATE SET
                resumen = EXCLUDED.resumen,
                mood = EXCLUDED.mood,
                interacciones = EXCLUDED.interacciones,
                ultima_actualizacion = EXCLUDED.ultima_actualizacion
            """,
            str(discord_id), resumen, mood, interacciones, _now_iso()
        )