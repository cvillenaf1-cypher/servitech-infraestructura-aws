BEGIN;

-- La contraseña se asigna después mediante el prompt interactivo de psql.
CREATE ROLE servitech_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;

GRANT CONNECT ON DATABASE servitech TO servitech_app;
GRANT USAGE ON SCHEMA public TO servitech_app;

DO $$
BEGIN
    IF current_database() <> 'servitech' THEN
        RAISE EXCEPTION 'Ejecutar el aprovisionamiento en la base servitech.';
    END IF;

    IF has_schema_privilege('servitech_app', 'public', 'CREATE')
        OR has_database_privilege('servitech_app', current_database(), 'CREATE') THEN
        RAISE EXCEPTION 'Revisar permisos CREATE concedidos a PUBLIC antes de aprovisionar la aplicación.';
    END IF;
END;
$$;

GRANT SELECT ON TABLE public.servicios, public.servicio_estado_historial TO servitech_app;

GRANT INSERT (cliente, equipo, descripcion, numero_serie, fecha_recepcion, cliente_sub, sede_id)
    ON TABLE public.servicios TO servitech_app;

GRANT UPDATE (diagnostico, tratamiento, presupuesto, estado, version)
    ON TABLE public.servicios TO servitech_app;

GRANT INSERT (servicio_id, version, estado_anterior, estado_nuevo, actor_sub)
    ON TABLE public.servicio_estado_historial TO servitech_app;

GRANT USAGE ON SEQUENCE public.servicios_id_seq TO servitech_app;

COMMIT;
