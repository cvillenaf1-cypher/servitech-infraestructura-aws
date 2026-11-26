import json
import os
import re

import boto3
from servitech_authz import (
    AuthenticationError, AuthorizationDenied, identity_from_rest_event,
    service_access_predicate, STAFF_ROLES, CLIENTE, response,
)
import psycopg2
from botocore.config import Config


class CognitoNoDisponible(RuntimeError):
    """No se pudo completar la consulta del propietario de forma segura."""


def get_connection():
    host = os.environ["DB_HOST"]
    port = int(os.environ["DB_PORT"])
    dbname = os.environ["DB_NAME"]
    username = os.environ["DB_USER"]
    region = os.environ["AWS_REGION"]

    token = boto3.client(
        "rds", region_name=region
    ).generate_db_auth_token(
        DBHostname=host,
        Port=port,
        DBUsername=username,
        Region=region,
    )

    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=username,
        password=token,
        sslmode="verify-full",
        sslrootcert="/var/task/amazon-trust-roots.pem",
        connect_timeout=5,
    )


def validate_request(event):
    if not isinstance(event, dict):
        raise ValueError("Solicitud inválida.")

    params = event.get("pathParameters")

    if not isinstance(params, dict):
        raise ValueError("Falta el ID del servicio.")

    raw_id = params.get("id")

    if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
        raise ValueError("El ID debe ser un entero positivo.")

    if not re.fullmatch(r"[0-9]+", str(raw_id)):
        raise ValueError("El ID debe ser un entero positivo.")

    service_id = int(raw_id)

    if service_id <= 0:
        raise ValueError("El ID debe ser mayor que cero.")

    body = event.get("body")

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("El body debe contener JSON válido.") from None

    if not isinstance(body, dict):
        raise ValueError("El body debe ser un objeto JSON.")

    estado = body.get("estado")

    if not isinstance(estado, str) or not estado.strip():
        raise ValueError("El estado es obligatorio.")

    return service_id, estado.strip()

def obtener_servicio(cursor, service_id, access):
    cursor.execute(
        """
        SELECT estado, version, cliente_sub
        FROM public.servicios AS svc
        WHERE svc.id = %s AND
        """ + access.sql + " FOR UPDATE OF svc;",
        (service_id, *access.params),
    )
    return cursor.fetchone()


def actualizar_estado_e_historial(
    cursor, service_id, estado_nuevo, identity
):
    access = service_access_predicate(identity, staff_roles=STAFF_ROLES)
    servicio = obtener_servicio(cursor, service_id, access)

    if servicio is None:
        return None

    estado_anterior, version_actual, cliente_sub = servicio

    if estado_anterior == estado_nuevo:
        raise ValueError("El servicio ya tiene ese estado.")

    cursor.execute(
        """
        UPDATE public.servicios AS svc
        SET estado = %s,
            version = version + 1
        WHERE svc.id = %s AND
        """ + access.sql + " RETURNING version;",
        (estado_nuevo, service_id, *access.params),
    )

    updated = cursor.fetchone()
    if updated is None:
        raise AuthorizationDenied("La autorización cambió durante la operación.")
    version_nueva = updated[0]

    cursor.execute(
        """
        INSERT INTO public.servicio_estado_historial (
            servicio_id,
            version,
            estado_anterior,
            estado_nuevo,
            actor_sub
        )
        VALUES (%s, %s, %s, %s, %s);
        """,
        (
            service_id,
            version_nueva,
            estado_anterior,
            estado_nuevo,
            identity.sub,
        ),
    )

    return {
        "servicio_id": service_id,
        "version": version_nueva,
        "estado_anterior": estado_anterior,
        "estado_nuevo": estado_nuevo,
        "cliente_sub": cliente_sub,
    }


def registrar_evento_outbox(cursor, cambio, telefono_verificado_e164):
    cliente_sub = cambio["cliente_sub"]

    if not isinstance(cliente_sub, str) or not cliente_sub.strip():
        raise ValueError("El servicio no tiene un cliente asociado.")

    if (
        not isinstance(telefono_verificado_e164, str)
        or not re.fullmatch(r"\+[1-9][0-9]{1,14}", telefono_verificado_e164)
    ):
        raise ValueError("Se requiere un teléfono verificado válido.")

    cursor.execute(
        """
        INSERT INTO public.servicio_outbox (
            servicio_id,
            version,
            cliente_sub,
            estado,
            telefono_verificado_e164
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING event_id;
        """,
        (
            cambio["servicio_id"],
            cambio["version"],
            cliente_sub,
            cambio["estado_nuevo"],
            telefono_verificado_e164,
        ),
    )

    return str(cursor.fetchone()[0])


def obtener_actor_autenticado(event):
    return identity_from_rest_event(event).sub


def consultar_cognito(operacion, context, **parametros):
    # Cada solicitud tiene hasta 1 s de conexión y 2 s de lectura, sin reintentos.
    # Reservar margen para rollback antes del timeout de la Lambda (15 s).
    if context is not None and context.get_remaining_time_in_millis() <= 4000:
        raise CognitoNoDisponible("Tiempo insuficiente para consultar Cognito.")

    try:
        return operacion(**parametros)
    except Exception:
        # No exponer respuestas del SDK, teléfonos ni identificadores al cliente.
        raise CognitoNoDisponible("No se pudo consultar Cognito.") from None


def obtener_telefono_verificado(cliente_sub, context=None):
    pool_id = os.environ.get(
        "COGNITO_USER_POOL_ID", ""
    ).strip()

    if not pool_id:
        raise NotImplementedError(
            "Falta configurar Cognito."
        )

    if not isinstance(cliente_sub, str) or not cliente_sub.strip():
        raise ValueError(
            "El cliente no tiene un identificador válido."
        )

    # sub es opaco: conservarlo exactamente y escapar su valor en el filtro.
    filtro = "sub = " + json.dumps(cliente_sub, ensure_ascii=False)
    if len(filtro) > 256:  # Límite del filtro de ListUsers, no formato de sub.
        raise ValueError("El identificador excede el límite de consulta.")

    try:
        cognito = boto3.client(
            "cognito-idp",
            region_name=os.environ["AWS_REGION"],
            config=Config(
                connect_timeout=1,
                read_timeout=2,
                retries={"mode": "standard", "total_max_attempts": 1},
            ),
        )
    except Exception:
        raise CognitoNoDisponible("No se pudo iniciar la consulta Cognito.") from None

    parametros = {"UserPoolId": pool_id, "Filter": filtro, "Limit": 2}
    usuarios = []
    # ListUsers es eventualmente consistente; solo sirve para resolver Username.
    # Recorrer páginas vacías sin aceptar un resultado parcial o ambiguo.
    for _ in range(5):
        resultado = consultar_cognito(cognito.list_users, context, **parametros)
        usuarios.extend(resultado.get("Users", []))
        if len(usuarios) > 1:
            raise ValueError("La identidad del cliente es ambigua.")
        token = resultado.get("PaginationToken")
        if not token:
            break
        parametros["PaginationToken"] = token
    else:
        raise CognitoNoDisponible("No se pudo completar la búsqueda del cliente.")

    if len(usuarios) != 1:
        raise ValueError(
            "No se encontró al cliente en Cognito."
        )

    usuario = usuarios[0]
    atributos = {
        atributo["Name"]: atributo.get("Value")
        for atributo in usuario.get("Attributes", [])
    }
    username = usuario.get("Username")
    if (
        atributos.get("sub") != cliente_sub
        or not isinstance(username, str)
        or not username
    ):
        raise ValueError("No se pudo comprobar la identidad del cliente.")

    usuario_actual = consultar_cognito(
        cognito.admin_get_user, context, UserPoolId=pool_id, Username=username
    )
    atributos = {
        atributo["Name"]: atributo.get("Value")
        for atributo in usuario_actual.get("UserAttributes", [])
    }
    if (
        usuario_actual.get("Username") != username
        or atributos.get("sub") != cliente_sub
    ):
        raise ValueError("No se pudo comprobar la identidad del cliente.")

    if usuario_actual.get("Enabled") is not True:
        raise ValueError("La cuenta del cliente no está habilitada.")

    telefono = atributos.get("phone_number")

    if (
        atributos.get("phone_number_verified") != "true"
        or not isinstance(telefono, str)
        or not re.fullmatch(
            r"\+[1-9][0-9]{1,14}", telefono
        )
    ):
        raise ValueError(
            "El cliente no tiene teléfono verificado."
        )

    return telefono



def publicar_evento_pendiente(connection, event_id, cambio, telefono):
    bus_arn = os.environ.get("EVENT_BUS_ARN", "").strip()

    if not bus_arn:
        return False

    detalle = {
        "event_id": event_id,
        "servicio_id": cambio["servicio_id"],
        "version": cambio["version"],
        "cliente_sub": cambio["cliente_sub"],
        "estado": cambio["estado_nuevo"],
        "telefono_verificado_e164": telefono,
    }

    try:
        resultado = boto3.client("events").put_events(
            Entries=[{
                "Source": "servitech.servicios",
                "DetailType": "ServicioEstadoActualizado",
                "Detail": json.dumps(detalle),
                "EventBusName": bus_arn,
            }]
        )

        if (
            resultado.get("FailedEntryCount", 1) != 0
            or not resultado.get("Entries", [{}])[0].get("EventId")
        ):
            return False

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.servicio_outbox
                SET publicado_en = CURRENT_TIMESTAMP
                WHERE event_id = %s
                  AND publicado_en IS NULL;
                """,
                (event_id,),
            )

        connection.commit()
        return True

    except Exception:
        connection.rollback()
        print("ActualizarEstado: evento pendiente de reintento.")
        return False


def verificar_rol_estado(event):
    try:
        return bool(identity_from_rest_event(event).groups.intersection(STAFF_ROLES))
    except (AuthenticationError, AuthorizationDenied):
        return False


def lambda_handler(event, context):
    try:
        service_id, estado_nuevo = validate_request(event)
    except ValueError as error:
        return response(400, {"message": str(error)})

    try:
        identity = identity_from_rest_event(event)
        service_access_predicate(identity, staff_roles=STAFF_ROLES)
    except AuthenticationError:
        return response(401, {"message": "Usuario no autenticado."})
    except AuthorizationDenied:
        return response(
            403,
            {"message": "No tienes permisos para actualizar estados."},
        )

    connection = None

    try:
        connection = get_connection()

        with connection.cursor() as cursor:
            cambio = actualizar_estado_e_historial(
                cursor,
                service_id,
                estado_nuevo,
                identity,
            )

            if cambio is None:
                connection.rollback()
                return response(
                    404,
                    {"message": "Servicio no encontrado."},
                )

            telefono = obtener_telefono_verificado(
                cambio["cliente_sub"], context
            )

            event_id = registrar_evento_outbox(
                cursor,
                cambio,
                telefono,
            )


        connection.commit()

        publicado = publicar_evento_pendiente(
            connection,
            event_id,
            cambio,
            telefono,
        )

        return response(
            200 if publicado else 202,
            {
                "message": (
                    "Estado actualizado y evento publicado."
                    if publicado
                    else "Estado actualizado; evento pendiente."
                ),
                "servicio_id": service_id,
                "version": cambio["version"],
                "event_id": event_id,
                "publicado": publicado,
            },
        )


    except AuthorizationDenied:
        if connection is not None:
            connection.rollback()
        return response(403, {"message": "Acceso no autorizado."})

    except CognitoNoDisponible:
        if connection is not None:
            connection.rollback()

        return response(
            503,
            {"message": "No se pudo verificar el teléfono del propietario."},
        )

    except NotImplementedError:
        if connection is not None:
            connection.rollback()

        return response(
            503,
            {
                "message": "Integracion de telefono verificado pendiente."
            },
        )

    except ValueError as error:
        if connection is not None:
            connection.rollback()

        return response(409, {"message": str(error)})

    except Exception:
        if connection is not None:
            connection.rollback()

        print("ActualizarEstado: error interno.")

        return response(
            500,
            {"message": "Error interno al actualizar el estado."},
        )

    finally:
        if connection is not None:
            connection.close()
