\set ON_ERROR_STOP on
\encoding UTF8

-- SOLO para PostgreSQL local desechable, con schema.sql y aprovisionamiento
-- ya aplicados. Ejecutar como administrador capaz de SET ROLE servitech_app.
-- Todos los datos sintéticos de esta prueba se revierten, incluso ante error
-- si psql termina con ON_ERROR_STOP. No usar como datos iniciales ni en AWS.
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.sedes WHERE id LIKE '__prueba_31_%') THEN
        RAISE EXCEPTION 'La base contiene identificadores reservados para esta prueba.';
    END IF;
END;
$$;

INSERT INTO public.sedes (id, nombre, activa) VALUES
    ('__prueba_31_a', 'Sede sintética A', TRUE),
    ('__prueba_31_b', 'Sede sintética B', TRUE);
INSERT INTO public.sedes (id, nombre) VALUES ('__prueba_31_inactiva', 'Inactiva');

-- Identidad opaca que deliberadamente no tiene formato UUID.
INSERT INTO public.usuario_sede_rol (usuario_sub, sede_id, rol, activo) VALUES
    ('sub/opaco:prueba', '__prueba_31_a', 'Administrador', TRUE),
    ('sub/opaco:prueba', '__prueba_31_b', 'Técnico', TRUE),
    ('sub/opaco:prueba', '__prueba_31_b', 'Cliente', TRUE);
INSERT INTO public.usuario_sede_rol (usuario_sub, sede_id, rol)
    VALUES ('sub/inactivo', '__prueba_31_a', 'Cliente');

DO $$
BEGIN
    IF (SELECT activa FROM public.sedes WHERE id = '__prueba_31_inactiva')
       OR (SELECT activo FROM public.usuario_sede_rol WHERE usuario_sub = 'sub/inactivo') THEN
        RAISE EXCEPTION 'Las sedes y asignaciones deben estar inactivas por defecto.';
    END IF;
    IF (SELECT count(*) FROM public.usuario_sede_rol
        WHERE usuario_sub = 'sub/opaco:prueba') <> 3 THEN
        RAISE EXCEPTION 'Debe admitirse multisede y varios roles por sede.';
    END IF;
    BEGIN
        INSERT INTO public.usuario_sede_rol (usuario_sub, sede_id, rol)
            VALUES ('sub/opaco:prueba', '__prueba_31_a', 'Administrador');
        RAISE EXCEPTION 'Se admitió una asignación duplicada.';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO public.usuario_sede_rol (usuario_sub, sede_id, rol)
            VALUES ('sub/prueba', '__prueba_31_ausente', 'Cliente');
        RAISE EXCEPTION 'Se admitió una sede inexistente.';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO public.usuario_sede_rol (usuario_sub, sede_id, rol)
            VALUES ('sub/prueba', '__prueba_31_a', 'Tecnico');
        RAISE EXCEPTION 'Se admitió un rol que no coincide exactamente con Cognito.';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO public.usuario_sede_rol (usuario_sub, sede_id, rol)
            VALUES (' ', '__prueba_31_a', 'Cliente');
        RAISE EXCEPTION 'Se admitió una identidad vacía.';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO public.sedes (id, nombre) VALUES (' ', 'Inválida');
        RAISE EXCEPTION 'Se admitió un ID de sede vacío.';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO public.sedes (id, nombre) VALUES ('__prueba_31_vacia', ' ');
        RAISE EXCEPTION 'Se admitió un nombre vacío.';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        DELETE FROM public.sedes WHERE id = '__prueba_31_a';
        RAISE EXCEPTION 'Se permitió borrar una sede referenciada.';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
    BEGIN
        UPDATE public.sedes SET id = '__prueba_31_otro' WHERE id = '__prueba_31_a';
        RAISE EXCEPTION 'Se permitió cambiar un ID de sede referenciado.';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
END;
$$;

SET LOCAL ROLE servitech_app;

DO $$
DECLARE
    tabla REGCLASS;
    sentencia TEXT;
BEGIN
    IF (SELECT count(*) FROM public.usuario_sede_rol
        WHERE usuario_sub = 'sub/opaco:prueba') <> 3
       OR NOT EXISTS (SELECT 1 FROM public.sedes WHERE id = '__prueba_31_a') THEN
        RAISE EXCEPTION 'La aplicación debe poder leer ambas tablas.';
    END IF;

    FOREACH tabla IN ARRAY ARRAY[
        'public.sedes'::REGCLASS, 'public.usuario_sede_rol'::REGCLASS
    ] LOOP
        IF has_table_privilege(current_user, tabla,
                               'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, SELECT WITH GRANT OPTION')
           OR has_any_column_privilege(current_user, tabla,
                                        'INSERT, UPDATE, REFERENCES, SELECT WITH GRANT OPTION') THEN
            RAISE EXCEPTION 'La aplicación tiene privilegios excesivos sobre %.', tabla;
        END IF;
    END LOOP;

    FOREACH sentencia IN ARRAY ARRAY[
        'INSERT INTO public.sedes (id, nombre) VALUES (''__prueba_31_prohibida'', ''Prohibida'')',
        'UPDATE public.sedes SET activa = TRUE WHERE FALSE',
        'DELETE FROM public.sedes WHERE FALSE',
        'TRUNCATE public.usuario_sede_rol, public.sedes',
        'INSERT INTO public.usuario_sede_rol (usuario_sub, sede_id, rol) VALUES (''sub/prohibido'', ''__prueba_31_a'', ''Administrador'')',
        'UPDATE public.usuario_sede_rol SET activo = TRUE WHERE FALSE',
        'DELETE FROM public.usuario_sede_rol WHERE FALSE'
    ] LOOP
        BEGIN
            EXECUTE sentencia;
            RAISE EXCEPTION 'La aplicación pudo ejecutar: %', sentencia;
        EXCEPTION WHEN insufficient_privilege THEN NULL;
        END;
    END LOOP;
END;
$$;

RESET ROLE;
ROLLBACK;
\echo 'Pruebas de sedes/asignaciones completadas; datos sintéticos revertidos.'
