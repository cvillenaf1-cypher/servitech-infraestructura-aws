\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS public.servicios (
    id SERIAL PRIMARY KEY,
    cliente VARCHAR(150) NOT NULL,
    equipo VARCHAR(150) NOT NULL,
    descripcion TEXT NOT NULL,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

\ir migrations/001_servicios_historial.sql
