"""Autorización para claims confiables de REST/Cognito; no verifica JWT.

No abre conexiones, confirma transacciones, publica eventos ni cambia datos.
Los handlers conservan el control de sus transacciones y efectos externos.
"""

from dataclasses import dataclass
import json


CLIENTE = "Cliente"
TECNICO = "Técnico"
ADMINISTRADOR = "Administrador"
GROUPS = frozenset((CLIENTE, TECNICO, ADMINISTRADOR))
STAFF_ROLES = frozenset((TECNICO, ADMINISTRADOR))


class AuthenticationError(Exception):
    """Identidad ausente o inválida; el adaptador HTTP podrá responder 401."""


class AuthorizationDenied(Exception):
    """Identidad sin permiso suficiente; 403, sin revelar existencia del recurso."""


class AuthorizationInfrastructureError(Exception):
    """Fallo de consulta/configuración transaccional; nunca convertir en permiso."""


def _valid_text(value):
    return isinstance(value, str) and bool(value.strip()) and "\x00" not in value


@dataclass(frozen=True)
class Identity:
    sub: str
    groups: frozenset[str]

    def __post_init__(self):
        if not _valid_text(self.sub):
            raise AuthenticationError("Identidad inválida.")
        if not isinstance(self.groups, frozenset) or not self.groups <= GROUPS:
            raise AuthorizationDenied("Grupos inválidos.")


def parse_groups(value):
    """CSV de REST o lista de strings del claim; nombres exactos, sin alias.

    No usa strip de corchetes/comillas, eval, coerciones ni búsqueda por subcadena.
    None representa claim ausente y no concede ningún rol.
    """
    if value is None:
        return frozenset()
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list):
        values = value
    else:
        raise AuthorizationDenied("Formato de grupos inválido.")
    if any(not isinstance(role, str) or role not in GROUPS for role in values):
        raise AuthorizationDenied("Grupo no reconocido.")
    if len(values) != len(set(values)):
        raise AuthorizationDenied("Grupos duplicados.")
    return frozenset(values)


def identity_from_rest_event(event):
    """Leer solo claims colocados por el autorizador, nunca body/headers."""
    node = event
    for key in ("requestContext", "authorizer", "claims"):
        if not isinstance(node, dict):
            raise AuthenticationError("Claims de autenticación ausentes.")
        node = node.get(key)
    if not isinstance(node, dict) or not _valid_text(node.get("sub")):
        raise AuthenticationError("Identidad ausente o inválida.")
    return Identity(node["sub"], parse_groups(node.get("cognito:groups")))


def has_role(identity, role):
    if role not in GROUPS:
        raise ValueError("El código debe solicitar un rol oficial.")
    return role in identity.groups


def is_owner(identity, owner_sub):
    """Solo igualdad de identidad; no autoriza por sí sola una operación."""
    return _valid_text(owner_sub) and identity.sub == owner_sub


@dataclass(frozen=True)
class SqlPredicate:
    sql: str
    params: tuple


def _eligible_staff(identity, staff_roles):
    if not isinstance(staff_roles, (tuple, list, set, frozenset)) or any(
        role not in STAFF_ROLES for role in staff_roles
    ):
        raise ValueError("La política debe especificar roles operativos oficiales.")
    return tuple(sorted(identity.groups.intersection(staff_roles)))


def service_access_predicate(identity, *, allow_owner=False, staff_roles=()):
    """Predicado para public.servicios AS svc; política elegida por el servidor.

    Los valores van separados en params. Insertar sql sin cambiar el alias svc
    en el WHERE de SELECT/UPDATE; no decidir permisos con una lectura anterior.
    Por defecto no habilita ninguna operación. No concede acceso global.
    """
    if type(allow_owner) is not bool:
        raise ValueError("allow_owner debe ser booleano y definido por el servidor.")
    roles = _eligible_staff(identity, staff_roles)
    clauses, params = [], []
    if allow_owner and has_role(identity, CLIENTE):
        clauses.append("svc.cliente_sub = %s")
        params.append(identity.sub)
    if roles:
        placeholders = ", ".join("%s" for _ in roles)
        clauses.append(f"""EXISTS (
            SELECT 1 FROM public.usuario_sede_rol AS auth_assignment
            WHERE auth_assignment.usuario_sub = %s
              AND auth_assignment.sede_id = svc.sede_id
              AND auth_assignment.activo
              AND auth_assignment.rol IN ({placeholders})
        )""")
        params.extend((identity.sub, *roles))
    if not clauses:
        raise AuthorizationDenied("No hay un rol habilitado para esta operación.")
    return SqlPredicate(
        """(svc.cliente_sub IS NOT NULL AND svc.cliente_sub ~ '[^[:space:]]'
        AND svc.sede_id IS NOT NULL AND svc.sede_id ~ '[^[:space:]]'
        AND EXISTS (SELECT 1 FROM public.sedes AS auth_site
                    WHERE auth_site.id = svc.sede_id AND auth_site.activa)
        AND (""" + " OR ".join(clauses) + "))",
        tuple(params),
    )


def _fetch_one(cursor, query, params=()):
    try:
        cursor.execute(query, params)
        return cursor.fetchone()
    except Exception as error:
        raise AuthorizationInfrastructureError("No se pudo comprobar la autorización.") from error


def require_service_access(cursor, identity, service_id, *, allow_owner=False, staff_roles=()):
    """Comprobación de lectura; para escrituras usar el predicado en la mutación.

    El llamador posee la conexión y decide rollback/commit. No usar un resultado
    positivo como autorización permanente ni como caché para una escritura.
    """
    if type(service_id) is not int or service_id <= 0:
        raise AuthorizationDenied("Servicio inválido.")
    predicate = service_access_predicate(identity, allow_owner=allow_owner, staff_roles=staff_roles)
    row = _fetch_one(cursor,
                     "SELECT 1 FROM public.servicios AS svc WHERE svc.id = %s AND " + predicate.sql,
                     (service_id, *predicate.params))
    if row is None:
        raise AuthorizationDenied("Acceso al servicio denegado.")


def require_site_role(cursor, identity, site_id, role):
    """Exigir exactamente el rol operativo solicitado en esa sede activa."""
    roles = _eligible_staff(identity, (role,))
    if not _valid_text(site_id) or not roles:
        raise AuthorizationDenied("Acceso a la sede denegado.")
    row = _fetch_one(cursor, """
        SELECT 1 FROM public.usuario_sede_rol AS assignment
        JOIN public.sedes AS site ON site.id = assignment.sede_id
        WHERE assignment.usuario_sub = %s AND assignment.sede_id = %s
          AND assignment.rol = %s AND assignment.activo AND site.activa
        """, (identity.sub, site_id, role))
    if row is None:
        raise AuthorizationDenied("Rol no autorizado en esta sede.")



def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
        },
        "body": json.dumps(body),
    }
