BEGIN;

ALTER TABLE public.servicios
    ADD COLUMN IF NOT EXISTS numero_serie TEXT,
    ADD COLUMN IF NOT EXISTS fecha_recepcion TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS diagnostico TEXT,
    ADD COLUMN IF NOT EXISTS tratamiento TEXT,
    ADD COLUMN IF NOT EXISTS presupuesto NUMERIC
        CONSTRAINT servicios_presupuesto_valido
        CHECK (presupuesto >= 0 AND presupuesto < 'Infinity'::NUMERIC),
    ADD COLUMN IF NOT EXISTS estado TEXT
        CONSTRAINT servicios_estado_no_vacio CHECK (btrim(estado) <> ''),
    ADD COLUMN IF NOT EXISTS version BIGINT NOT NULL DEFAULT 0
        CONSTRAINT servicios_version_no_negativa CHECK (version >= 0),
    ADD COLUMN IF NOT EXISTS cliente_sub TEXT
        CONSTRAINT servicios_cliente_sub_no_vacio CHECK (btrim(cliente_sub) <> ''),
    ADD COLUMN IF NOT EXISTS sede_id TEXT
        CONSTRAINT servicios_sede_id_no_vacio CHECK (btrim(sede_id) <> '');

CREATE INDEX IF NOT EXISTS servicios_cliente_sub_idx
    ON public.servicios (cliente_sub) WHERE cliente_sub IS NOT NULL;

CREATE INDEX IF NOT EXISTS servicios_sede_id_idx
    ON public.servicios (sede_id) WHERE sede_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.servicio_estado_historial (
    servicio_id INTEGER NOT NULL,
    version BIGINT NOT NULL CHECK (version > 0),
    estado_anterior TEXT CHECK (btrim(estado_anterior) <> ''),
    estado_nuevo TEXT NOT NULL CHECK (btrim(estado_nuevo) <> ''),
    actor_sub TEXT CHECK (btrim(actor_sub) <> ''),
    cambiado_en TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT servicio_estado_historial_pk PRIMARY KEY (servicio_id, version),
    CONSTRAINT servicio_estado_historial_servicio_fk
        FOREIGN KEY (servicio_id) REFERENCES public.servicios (id)
);

COMMIT;
