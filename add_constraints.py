import asyncio
import asyncpg
import os
import sys
from dotenv import load_dotenv

load_dotenv()

async def add_constraints():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("No DATABASE_URL found.")
        sys.exit(1)

    print("Connecting to Supabase to add missing unique constraints...")
    conn = await asyncpg.connect(db_url)
    
    queries = [
        "ALTER TABLE narraciones ADD CONSTRAINT narraciones_evento_sesion_key UNIQUE (evento_id, numero_sesion);",
        "ALTER TABLE participantes ADD CONSTRAINT participantes_evento_usuario_key UNIQUE (evento_id, usuario_discord_id);",
        "ALTER TABLE votos ADD CONSTRAINT votos_evento_votante_key UNIQUE (evento_id, votante_discord_id);"
    ]
    
    for q in queries:
        try:
            await conn.execute(q)
            print(f"Success: {q}")
        except asyncpg.exceptions.DuplicateTableError:
            print(f"Constraint already exists for: {q}")
        except asyncpg.exceptions.InvalidTableDefinitionError:
            print(f"Constraint already exists (InvalidTableDefinitionError) for: {q}")
        except Exception as e:
            if "already exists" in str(e):
                print(f"Constraint already exists: {e}")
            else:
                print(f"Error executing {q}: {e}")
                
    await conn.close()
    print("Done.")

if __name__ == "__main__":
    asyncio.run(add_constraints())
