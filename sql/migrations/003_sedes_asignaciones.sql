\set ON_ERROR_STOP on
\encoding UTF8

BEGIN;

-- Catálogo administrativo: esta migración no inserta sedes ni asignaciones.
CREATE TABLE IF NOT EXISTS public.sedes (
    id TEXT PRIMARY KEY CHECK (btrim(id) <> ''),
    nombre TEXT NOT NULL CHECK (btrim(nombre) <> ''),
    activa BOOLEAN NOT NULL DEFAULT FALSE,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.usuario_sede_rol (
    usuario_sub TEXT NOT NULL CHECK (btrim(usuario_sub) <> ''),
    sede_id TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('Cliente', 'Técnico', 'Administrador')),
    activo BOOLEAN NOT NULL DEFAULT FALSE,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT usuario_sede_rol_pk PRIMARY KEY (usuario_sub, sede_id, rol),
    CONSTRAINT usuario_sede_rol_sede_fk FOREIGN KEY (sede_id)
        REFERENCES public.sedes (id) ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- La PK sirve a la consulta por usuario/sede/rol; este índice permite buscar
-- todas las asignaciones de una sede y comprobar la FK, incluso las inactivas.
CREATE INDEX IF NOT EXISTS usuario_sede_rol_sede_rol_idx
    ON public.usuario_sede_rol (sede_id, rol);

-- No se añade aún una FK desde servicios: sus sedes históricas pueden no
-- estar catalogadas. No se alteran ni regularizan sus datos automáticamente.
\ir ../grant_sedes_lectura.sql

COMMIT;
