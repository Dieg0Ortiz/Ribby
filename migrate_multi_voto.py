"""
migrate_multi_voto.py — Migración para soporte de multi-voto por evento.

Cambios:
  1. Agrega columna `votos_max_por_usuario` a la tabla `eventos` (default 1).
  2. Elimina el constraint UNIQUE (evento_id, votante_discord_id) de `votos`
     para permitir múltiples votos por usuario.
  3. Agrega constraint UNIQUE (evento_id, votante_discord_id, participante_id)
     para evitar votar más de una vez por la misma historia.

Uso:
  python migrate_multi_voto.py
"""

import asyncio
import asyncpg
import os
import sys
from dotenv import load_dotenv

load_dotenv()


async def migrate():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌  No DATABASE_URL found in .env")
        sys.exit(1)

    print("🔗  Conectando a la base de datos...")
    conn = await asyncpg.connect(db_url)

    steps = [
        # 1. Agregar columna votos_max_por_usuario a eventos
        (
            "Agregar columna votos_max_por_usuario a eventos",
            """
            ALTER TABLE eventos
            ADD COLUMN IF NOT EXISTS votos_max_por_usuario INTEGER NOT NULL DEFAULT 1;
            """,
        ),
        # 2. Eliminar constraint UNIQUE que limita a 1 voto por usuario
        (
            "Eliminar constraint votos_evento_votante_key (1 voto por usuario)",
            """
            ALTER TABLE votos
            DROP CONSTRAINT IF EXISTS votos_evento_votante_key;
            """,
        ),
        # 3. Agregar constraint para evitar votar 2 veces por la misma historia
        (
            "Agregar constraint UNIQUE (evento, votante, participante)",
            """
            ALTER TABLE votos
            ADD CONSTRAINT votos_evento_votante_participante_key
            UNIQUE (evento_id, votante_discord_id, participante_id);
            """,
        ),
    ]

    for description, query in steps:
        try:
            await conn.execute(query)
            print(f"  ✅  {description}")
        except asyncpg.exceptions.DuplicateObjectError:
            print(f"  ⏭️  {description} (ya existe)")
        except asyncpg.exceptions.InvalidTableDefinitionError as e:
            if "already exists" in str(e):
                print(f"  ⏭️  {description} (ya existe)")
            else:
                print(f"  ❌  {description}: {e}")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"  ⏭️  {description} (ya existe)")
            else:
                print(f"  ❌  {description}: {e}")

    await conn.close()
    print("\n✨  Migración completada.")


if __name__ == "__main__":
    asyncio.run(migrate())
