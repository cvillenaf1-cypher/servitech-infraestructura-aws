BEGIN;

CREATE TABLE IF NOT EXISTS public.servicio_outbox (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    servicio_id INTEGER NOT NULL,
    version BIGINT NOT NULL,
    cliente_sub TEXT NOT NULL CHECK (btrim(cliente_sub) <> ''),
    estado TEXT NOT NULL CHECK (btrim(estado) <> ''),
    telefono_verificado_e164 TEXT NOT NULL
        CHECK (telefono_verificado_e164 ~ '^[+][1-9][0-9]{1,14}$'),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    publicado_en TIMESTAMPTZ,
    intentos INTEGER NOT NULL DEFAULT 0 CHECK (intentos >= 0),
    disponible_desde TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT servicio_outbox_servicio_version_unico UNIQUE (servicio_id, version),
    CONSTRAINT servicio_outbox_historial_fk
        FOREIGN KEY (servicio_id, version)
        REFERENCES public.servicio_estado_historial (servicio_id, version)
);

CREATE INDEX IF NOT EXISTS servicio_outbox_pendientes_idx
    ON public.servicio_outbox (disponible_desde, creado_en, event_id)
    WHERE publicado_en IS NULL;

COMMIT;
