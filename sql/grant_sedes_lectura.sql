\set ON_ERROR_STOP on
\encoding UTF8

-- Un único DO es atómico tanto por separado como dentro de una migración.
-- Ejecutar como propietario administrativo de las dos tablas (no como app).
DO $$
DECLARE
    tabla REGCLASS;
    columna RECORD;
    candidato RECORD;
    app_oid OID;
BEGIN
    SELECT oid INTO app_oid FROM pg_roles WHERE rolname = 'servitech_app';

    FOREACH tabla IN ARRAY ARRAY[
        'public.sedes'::REGCLASS, 'public.usuario_sede_rol'::REGCLASS
    ] LOOP
        -- Incluye privilegios materializados desde ALTER DEFAULT PRIVILEGES.
        EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %s FROM PUBLIC', tabla);
        IF app_oid IS NOT NULL THEN
            EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %s FROM servitech_app', tabla);
        END IF;
        -- Revocar privilegios de tabla no elimina concesiones por columna.
        FOR columna IN
            SELECT attname FROM pg_attribute
            WHERE attrelid = tabla AND attnum > 0 AND NOT attisdropped
        LOOP
            EXECUTE format('REVOKE ALL PRIVILEGES (%I) ON TABLE %s FROM PUBLIC',
                           columna.attname, tabla);
            IF app_oid IS NOT NULL THEN
                EXECUTE format('REVOKE ALL PRIVILEGES (%I) ON TABLE %s FROM servitech_app',
                               columna.attname, tabla);
            END IF;
        END LOOP;
    END LOOP;

    IF app_oid IS NULL THEN
        RAISE NOTICE 'servitech_app no existe: ejecutar su aprovisionamiento después del esquema.';
        RETURN;
    END IF;

    -- MEMBER incluye membresías transitivas aunque NOINHERIT o SET FALSE
    -- restrinjan su uso actual. Se rechaza conservadoramente esa exposición;
    -- no se revocan permisos de roles compartidos con otros componentes.
    FOR candidato IN
        SELECT oid, rolname, rolsuper, rolcreaterole, rolcreatedb,
               rolreplication, rolbypassrls
        FROM pg_roles
        WHERE oid = app_oid OR pg_has_role(app_oid, oid, 'MEMBER')
    LOOP
        IF candidato.rolsuper OR candidato.rolcreaterole OR candidato.rolcreatedb
           OR candidato.rolreplication OR candidato.rolbypassrls
           OR has_schema_privilege(candidato.oid, 'public', 'CREATE')
           OR has_database_privilege(candidato.oid, current_database(), 'CREATE')
           OR EXISTS (SELECT 1 FROM pg_database
                      WHERE datname = current_database() AND datdba = candidato.oid)
           OR EXISTS (SELECT 1 FROM pg_namespace
                      WHERE nspname = 'public' AND nspowner = candidato.oid) THEN
            RAISE EXCEPTION 'Rol % incompatible con lectura exclusiva de asignaciones; revisar administración y membresías.', candidato.rolname;
        END IF;

        FOREACH tabla IN ARRAY ARRAY[
            'public.sedes'::REGCLASS, 'public.usuario_sede_rol'::REGCLASS
        ] LOOP
            IF EXISTS (SELECT 1 FROM pg_class
                       WHERE oid = tabla AND relowner = candidato.oid)
               OR has_table_privilege(candidato.oid, tabla,
                                      'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')
               OR has_any_column_privilege(candidato.oid, tabla, 'INSERT, UPDATE, REFERENCES')
               OR has_table_privilege(candidato.oid, tabla, 'SELECT WITH GRANT OPTION')
               OR has_any_column_privilege(candidato.oid, tabla, 'SELECT WITH GRANT OPTION') THEN
                RAISE EXCEPTION 'Rol % tiene propiedad o permisos no permitidos sobre %; revisar concesiones heredadas/predeterminadas.', candidato.rolname, tabla;
            END IF;
        END LOOP;
    END LOOP;

    GRANT SELECT ON TABLE public.sedes, public.usuario_sede_rol TO servitech_app;
END;
$$;
