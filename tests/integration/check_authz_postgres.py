"""Pruebas explícitas sobre PostgreSQL LOCAL desechable, nunca sobre AWS.

El ejecutor crea el esquema y servitech_app y entrega conexiones psycopg2
administrativa/de aplicación. run_checks devuelve los casos ejecutados.
No importar desde el descubrimiento unitario: requiere PostgreSQL real.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lambda" / "shared"))
import servitech_authz as auth


def run_checks(admin, app):
    for connection in (admin, app):
        if connection.info.host != "127.0.0.1":
            raise RuntimeError("Solo se admite el contenedor local en loopback.")
    results = []
    client = auth.Identity("cliente/opaco", frozenset((auth.CLIENTE,)))
    staff = auth.Identity("personal/opaco", auth.STAFF_ROLES)
    tech = auth.Identity(staff.sub, frozenset((auth.TECNICO,)))

    def check(name, action, denied=False):
        try:
            action()
        except auth.AuthorizationDenied:
            if not denied:
                raise
        else:
            if denied:
                raise AssertionError("Se autorizó indebidamente: " + name)
        finally:
            app.rollback()
        results.append(name)

    def service(identity, number, owner=False, roles=()):
        with app.cursor() as cursor:
            auth.require_service_access(cursor, identity, number, allow_owner=owner, staff_roles=roles)

    def site(identity, site_id, role):
        with app.cursor() as cursor:
            auth.require_site_role(cursor, identity, site_id, role)

    with admin.cursor() as cursor:
        cursor.execute("""
            INSERT INTO public.sedes(id,nombre,activa) VALUES
                ('A','Sintética A',true), ('B','Sintética B',true),
                ('C','Sintética C inactiva',false), ('D','Sintética D',true);
            INSERT INTO public.usuario_sede_rol(usuario_sub,sede_id,rol,activo) VALUES
                ('personal/opaco','A','Administrador',true),
                ('personal/opaco','B','Técnico',true),
                ('personal/opaco','C','Administrador',true),
                ('personal/opaco','D','Administrador',false);
            INSERT INTO public.servicios(id,cliente,equipo,descripcion,cliente_sub,sede_id) VALUES
                (3101,'Sintético','Equipo','Prueba','cliente/opaco','A'),
                (3102,'Sintético','Equipo','Prueba','cliente/opaco','B'),
                (3103,'Sintético','Equipo','Prueba','cliente/opaco','C'),
                (3104,'Sintético','Equipo','Prueba','cliente/opaco','D'),
                (3105,'Sintético','Equipo','Prueba','ajeno','A'),
                (3106,'Sintético','Equipo','Histórico',NULL,'A'),
                (3107,'Sintético','Equipo','Histórico','cliente/opaco',NULL),
                (3108,'Sintético','Equipo','Histórico','cliente/opaco','ausente'),
                (3109,'Sintético','Equipo','Histórico',E'\\t','A');
            """)
    admin.commit()
    check("Cliente propietario sin asignación operativa", lambda: service(client, 3101, owner=True))
    check("Cliente propietario en otra sede activa", lambda: service(client, 3102, owner=True))
    check("Cliente ajeno", lambda: service(client, 3105, owner=True), denied=True)
    check("Cliente sin permiso operativo", lambda: service(client, 3101, roles=auth.STAFF_ROLES), denied=True)
    check("Cliente en sede inactiva", lambda: service(client, 3103, owner=True), denied=True)
    for number in (3106, 3107, 3108, 3109):
        check(f"Histórico incompleto {number}", lambda n=number: service(staff, n, roles=auth.STAFF_ROLES), denied=True)
    check("Administrador A", lambda: service(staff, 3101, roles=(auth.ADMINISTRADOR,)))
    check("Técnico B", lambda: service(staff, 3102, roles=(auth.TECNICO,)))
    check("No propagar Administrador A hacia B", lambda: service(staff, 3102, roles=(auth.ADMINISTRADOR,)), denied=True)
    check("No propagar Técnico B hacia A", lambda: service(staff, 3101, roles=(auth.TECNICO,)), denied=True)
    check("Asignación sin grupo coincidente", lambda: service(tech, 3101, roles=auth.STAFF_ROLES), denied=True)
    check("Asignación inactiva", lambda: service(staff, 3104, roles=auth.STAFF_ROLES), denied=True)
    check("Personal en sede inactiva", lambda: service(staff, 3103, roles=auth.STAFF_ROLES), denied=True)
    check("Rol exacto por sede A", lambda: site(staff, "A", auth.ADMINISTRADOR))
    check("Rol exacto por sede B", lambda: site(staff, "B", auth.TECNICO))
    check("Rol incorrecto por sede B", lambda: site(staff, "B", auth.ADMINISTRADOR), denied=True)
    check("Sede inexistente", lambda: site(staff, "ausente", auth.TECNICO), denied=True)
    check("Sin asignación de usuario", lambda: service(auth.Identity("otro", auth.STAFF_ROLES), 3101, roles=auth.STAFF_ROLES), denied=True)
    check("Sub parametrizado no permite inyección", lambda: service(auth.Identity("x' OR TRUE --", frozenset((auth.CLIENTE,))), 3101, owner=True), denied=True)

    def atomic_update(number, allowed):
        predicate = auth.service_access_predicate(staff, staff_roles=(auth.ADMINISTRADOR,))
        with app.cursor() as cursor:
            cursor.execute("UPDATE public.servicios AS svc SET diagnostico = %s WHERE svc.id = %s AND "
                           + predicate.sql + " RETURNING svc.id", ("Prueba sintética", number, *predicate.params))
            assert cursor.fetchone() == ((number,) if allowed else None)
    check("Predicado en UPDATE permite Administrador A", lambda: atomic_update(3101, True))
    check("Predicado en UPDATE deniega Administrador B", lambda: atomic_update(3102, False))

    with app.cursor() as cursor:
        cursor.execute("SELECT bool_and(NOT has_table_privilege(current_user,t,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')) "
                       "FROM unnest(ARRAY['public.sedes'::regclass,'public.usuario_sede_rol'::regclass]) t")
        assert cursor.fetchone() == (True,)
    app.rollback()
    results.append("Conservación de solo lectura en tablas de autorización")
    return results
