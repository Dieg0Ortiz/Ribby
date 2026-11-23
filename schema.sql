-- ════════════════════════════════════════════════════════════════════
-- schema.sql — Esquema de la base de datos de Ribby (Supabase)
-- ════════════════════════════════════════════════════════════════════
--
-- Copia del esquema de producción (exportado de Supabase) con las tablas
-- que usa el código. Es documentación: Supabase es la fuente de verdad.
--
-- El código usa ON CONFLICT sobre estas columnas, así que en producción
-- tiene que existir un índice/constraint UNIQUE para cada una (el export
-- de Supabase no muestra los índices; se pueden comprobar con:
--   SELECT tablename, indexname, indexdef FROM pg_indexes
--   WHERE schemaname = 'public' ORDER BY tablename;):
--     participantes            (evento_id, usuario_discord_id)
--     documentos_participantes (participante_id, tipo)
--     votos                    (evento_id, votante_discord_id, participante_id)  ← lo crea el bot al arrancar
--
-- Tablas antiguas que el código actual NO usa: memoria_usuarios,
-- conocidos_ribby, afinidad_usuarios.

CREATE TABLE public.eventos (
  id integer NOT NULL DEFAULT nextval('eventos_id_seq'::regclass),
  nombre text NOT NULL,
  estado text NOT NULL DEFAULT 'abierto'::text,      -- abierto | narrando | votando | cerrado
  fecha_creacion text NOT NULL,                      -- ISO 8601
  fecha_cierre text,
  canal_voz_id bigint,
  canal_envio_id bigint,
  canal_respaldo_id bigint,
  duracion_narracion_minutos real DEFAULT 0,
  timestamp_inicio_narracion text,                   -- sin uso (heredada)
  votos_max_por_usuario integer NOT NULL DEFAULT 1,
  CONSTRAINT eventos_pkey PRIMARY KEY (id)
);

CREATE TABLE public.narraciones (
  id integer NOT NULL DEFAULT nextval('narraciones_id_seq'::regclass),
  evento_id integer NOT NULL REFERENCES public.eventos(id),
  numero_sesion integer NOT NULL DEFAULT 1,
  timestamp_inicio text NOT NULL,
  timestamp_fin text,
  duracion_minutos real DEFAULT 0,
  CONSTRAINT narraciones_pkey PRIMARY KEY (id)
);

CREATE TABLE public.participantes (
  id integer NOT NULL DEFAULT nextval('participantes_id_seq'::regclass),
  evento_id integer NOT NULL REFERENCES public.eventos(id),
  usuario_discord_id text NOT NULL,
  usuario_nombre text NOT NULL,
  titulo_historia text,
  url_portada text,
  url_pdf text,
  fecha_registro text NOT NULL,
  CONSTRAINT participantes_pkey PRIMARY KEY (id)
);

CREATE TABLE public.asistencia_voz (
  id integer NOT NULL DEFAULT nextval('asistencia_voz_id_seq'::regclass),
  evento_id integer NOT NULL REFERENCES public.eventos(id),
  narracion_id integer REFERENCES public.narraciones(id),
  usuario_discord_id text NOT NULL,
  timestamp_entrada text NOT NULL,
  timestamp_salida text,
  minutos_totales real DEFAULT 0,
  CONSTRAINT asistencia_voz_pkey PRIMARY KEY (id)
);

CREATE TABLE public.votos (
  id integer NOT NULL DEFAULT nextval('votos_id_seq'::regclass),
  evento_id integer NOT NULL REFERENCES public.eventos(id),
  votante_discord_id text NOT NULL,
  participante_id integer NOT NULL REFERENCES public.participantes(id),
  timestamp_voto text NOT NULL,
  es_valido integer DEFAULT 1,                       -- 1 válido, 0 anulado por el antifraude
  CONSTRAINT votos_pkey PRIMARY KEY (id)
);

-- Solo la escribe /evento iniciar_votacion (database.guardar_habilitados)
CREATE TABLE public.habilitados_voto (
  evento_id integer NOT NULL REFERENCES public.eventos(id),
  usuario_discord_id text NOT NULL,
  minutos_presencia real DEFAULT 0,
  documentos_descargados integer DEFAULT 0,
  CONSTRAINT habilitados_voto_pkey PRIMARY KEY (evento_id, usuario_discord_id)
);

CREATE TABLE public.descargas_documentos (
  evento_id integer NOT NULL REFERENCES public.eventos(id),
  usuario_discord_id text NOT NULL,
  participante_id integer NOT NULL REFERENCES public.participantes(id),
  timestamp_descarga text NOT NULL,
  CONSTRAINT descargas_documentos_pkey PRIMARY KEY (evento_id, usuario_discord_id, participante_id)
);

CREATE TABLE public.documentos_participantes (
  id integer NOT NULL DEFAULT nextval('documentos_participantes_id_seq'::regclass),
  participante_id integer NOT NULL REFERENCES public.participantes(id),
  evento_id integer NOT NULL REFERENCES public.eventos(id),
  usuario_discord_id text NOT NULL,
  tipo text NOT NULL CHECK (tipo = ANY (ARRAY['pdf'::text, 'portada'::text])),
  url_discord text,
  url_respaldo text,
  url_activa text,                                   -- COALESCE(url_respaldo, url_discord)
  nombre_archivo text,
  content_type text,
  tamanio_bytes bigint,
  version integer NOT NULL DEFAULT 1,
  fecha_subida timestamp with time zone NOT NULL DEFAULT now(),
  fecha_actualizacion timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT documentos_participantes_pkey PRIMARY KEY (id)
);

CREATE TABLE public.ribby_memoria (
  usuario_discord_id text NOT NULL,
  resumen text,
  mood text DEFAULT 'frio'::text,
  interacciones integer DEFAULT 0,
  ultima_actualizacion timestamp with time zone DEFAULT now(),
  CONSTRAINT ribby_memoria_pkey PRIMARY KEY (usuario_discord_id)
);

-- ── Biblioteca de recomendaciones (las crea el bot al arrancar si no existen) ──

CREATE TABLE public.biblioteca_historias (
  id                 SERIAL PRIMARY KEY,
  fuente             TEXT NOT NULL,                 -- 'wattpad' | 'reto'
  wattpad_id         TEXT UNIQUE,
  participante_id    INTEGER UNIQUE REFERENCES public.participantes(id) ON DELETE SET NULL,
  titulo             TEXT NOT NULL,
  autor_nombre       TEXT,
  autor_wattpad      TEXT,
  autor_discord_id   TEXT,
  descripcion        TEXT,
  descripcion_fuente TEXT,                          -- 'wattpad' | 'autor' | 'usuario'
  url                TEXT,
  portada_url        TEXT,
  lecturas           INTEGER,
  votos              INTEGER,
  partes             INTEGER,
  completada         BOOLEAN,
  madura             BOOLEAN NOT NULL DEFAULT FALSE,
  agregada_por       TEXT,                          -- discord id, o 'lista'
  fecha_alta         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  fecha_sync         TIMESTAMPTZ
);

CREATE TABLE public.biblioteca_etiquetas (
  historia_id   INTEGER NOT NULL REFERENCES public.biblioteca_historias(id) ON DELETE CASCADE,
  valor         TEXT NOT NULL,                      -- en minúsculas
  fuente        TEXT NOT NULL,                      -- 'wattpad' | 'autor' | 'usuario'
  aportado_por  TEXT,
  fecha         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (historia_id, valor)
);

CREATE TABLE public.autores_wattpad (
  wattpad_username  TEXT PRIMARY KEY,               -- en minúsculas
  discord_id        TEXT NOT NULL,
  fecha             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Las tres tienen RLS activado (la anon key de Supabase no puede acceder).

-- ── Medidor de corazones (tabla que ya existía; el bot añade las columnas nuevas) ──

CREATE TABLE public.afinidad_usuarios (
  usuario_discord_id   text NOT NULL PRIMARY KEY,
  nombre_display       text NOT NULL,
  corazones            real DEFAULT 0.0,            -- 0 a 100
  nivel_relacion       text DEFAULT 'desconocido',  -- desconocido | amigo | mejor_amigo | algo_mas | enamorada | pareja
  es_pareja            boolean DEFAULT false,
  fecha_inicio_pareja  text,
  racha_dias           integer DEFAULT 0,
  ultima_interaccion   text,
  total_interacciones  integer DEFAULT 0,
  historial_eventos    text DEFAULT '[]'::text,     -- JSON: momentos importantes
  -- Columnas añadidas por el bot:
  corazones_hoy        real DEFAULT 0,
  dia_corazones        text,
  coqueteos            integer DEFAULT 0,
  fecha_maximo         text,                        -- cuándo llegó a 100 (para el enfriamiento)
  ultimo_regalo        text,
  ultima_cita          text,
  ultima_declaracion   text,
  dias_descontados     integer DEFAULT 0
);
-- Garantiza que Ribby solo tenga una pareja:
CREATE UNIQUE INDEX afinidad_una_sola_pareja ON public.afinidad_usuarios ((es_pareja)) WHERE es_pareja;
-- Contadores añadidos por el bot: citas_total, regalos_total (integer DEFAULT 0)

-- ── Vida social de Ribby (las crea el bot al arrancar; todas con RLS activado) ──

CREATE TABLE public.ribby_config (           -- clave/valor: canal de Ribby, celebraciones ya hechas, avisos...
  clave  text PRIMARY KEY,
  valor  text,
  fecha  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.cumpleanos (
  usuario_discord_id  text PRIMARY KEY,
  dia                 integer NOT NULL CHECK (dia BETWEEN 1 AND 31),
  mes                 integer NOT NULL CHECK (mes BETWEEN 1 AND 12)
);

CREATE TABLE public.resenas (
  id                  serial PRIMARY KEY,
  historia_id         integer NOT NULL REFERENCES public.biblioteca_historias(id) ON DELETE CASCADE,
  usuario_discord_id  text NOT NULL,
  usuario_nombre      text,
  puntuacion          integer NOT NULL CHECK (puntuacion BETWEEN 1 AND 5),
  texto               text NOT NULL,
  fecha               timestamptz NOT NULL DEFAULT now(),
  UNIQUE (historia_id, usuario_discord_id)
);

CREATE TABLE public.misiones_lectura (
  id                  serial PRIMARY KEY,
  usuario_discord_id  text NOT NULL,
  historia_id         integer NOT NULL REFERENCES public.biblioteca_historias(id) ON DELETE CASCADE,
  estado              text NOT NULL DEFAULT 'activa',   -- activa | completada | abandonada
  fecha_asignada      timestamptz NOT NULL DEFAULT now(),
  fecha_completada    timestamptz
);
CREATE UNIQUE INDEX misiones_una_activa ON public.misiones_lectura (usuario_discord_id) WHERE estado = 'activa';

CREATE TABLE public.logros_usuarios (
  usuario_discord_id  text NOT NULL,
  logro               text NOT NULL,                     -- claves de logros.py
  fecha               timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (usuario_discord_id, logro)
);
-- Contador añadido por el bot en afinidad_usuarios: quiz_aciertos (integer DEFAULT 0)

CREATE TABLE public.ribby_capitulos (        -- capítulos de la historia de Ribby ya leídos y la decisión tomada
  usuario_discord_id  text NOT NULL,
  capitulo            integer NOT NULL,
  eleccion            integer NOT NULL,
  fecha               timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (usuario_discord_id, capitulo)
);

CREATE TABLE public.seguimientos (           -- avisos de capítulos nuevos
  usuario_discord_id  text NOT NULL,
  historia_id         integer NOT NULL REFERENCES public.biblioteca_historias(id) ON DELETE CASCADE,
  fecha               timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (usuario_discord_id, historia_id)
);

-- ── Modo de pruebas ──
-- El esquema "pruebas" contiene una copia (misma estructura, datos aparte) de todas las
-- tablas del bot. El bot lo crea al arrancar con:
--   CREATE SCHEMA IF NOT EXISTS pruebas;
--   CREATE TABLE IF NOT EXISTS pruebas.<tabla> (LIKE public.<tabla> INCLUDING ALL);
-- Quién está en modo de pruebas se guarda en public.ribby_config (claves 'modo_prueba:<id>').
