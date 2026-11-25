import json
import os
import re

import boto3
import psycopg2


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(body),
    }


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

def obtener_servicio(cursor, service_id):
    cursor.execute(
        """
        SELECT estado, version, cliente_sub
        FROM public.servicios
        WHERE id = %s
        FOR UPDATE;
        """,
        (service_id,),
    )
    return cursor.fetchone()


def actualizar_estado_e_historial(
    cursor, service_id, estado_nuevo, actor_sub=None
):
    servicio = obtener_servicio(cursor, service_id)

    if servicio is None:
        return None

    estado_anterior, version_actual, cliente_sub = servicio

    if estado_anterior == estado_nuevo:
        raise ValueError("El servicio ya tiene ese estado.")

    cursor.execute(
        """
        UPDATE public.servicios
        SET estado = %s,
            version = version + 1
        WHERE id = %s
        RETURNING version;
        """,
        (estado_nuevo, service_id),
    )

    version_nueva = cursor.fetchone()[0]

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
            actor_sub,
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
    if not isinstance(event, dict):
        raise ValueError("Solicitud inválida.")

    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer") or {}
    claims = authorizer.get("claims") or {}

    if not isinstance(claims, dict):
        raise ValueError("No se pudo verificar la identidad.")

    actor_sub = claims.get("sub")

    if not isinstance(actor_sub, str) or not actor_sub.strip():
        raise ValueError("No se encontró un usuario autenticado.")

    return actor_sub.strip()



def obtener_telefono_verificado(cliente_sub):
    pool_id = os.environ.get(
        "COGNITO_USER_POOL_ID", ""
    ).strip()

    if not pool_id:
        raise NotImplementedError(
            "Falta configurar Cognito."
        )

    if (
        not isinstance(cliente_sub, str)
        or not re.fullmatch(
            r"[0-9a-fA-F-]{36}", cliente_sub
        )
    ):
        raise ValueError(
            "El cliente no tiene un identificador válido."
        )

    cognito = boto3.client(
        "cognito-idp",
        region_name=os.environ["AWS_REGION"],
    )

    resultado = cognito.list_users(
        UserPoolId=pool_id,
        Filter=f'sub = "{cliente_sub}"',
        Limit=2,
    )

    usuarios = resultado.get("Users", [])

    if len(usuarios) != 1:
        raise ValueError(
            "No se encontró al cliente en Cognito."
        )

    usuario = usuarios[0]

    if usuario.get("Enabled") is False:
        raise ValueError(
            "La cuenta del cliente está deshabilitada."
        )

    atributos = {
        atributo["Name"]: atributo.get("Value")
        for atributo in usuario.get("Attributes", [])
    }

    telefono = atributos.get("phone_number")

    if (
        atributos.get("sub") != cliente_sub
        or atributos.get("phone_number_verified") != "true"
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
    contexto = event.get("requestContext") or {}
    autorizador = contexto.get("authorizer") or {}
    claims = autorizador.get("claims") or {}

    grupos = claims.get("cognito:groups", [])

    if isinstance(grupos, str):
        try:
            grupos = json.loads(grupos)
        except json.JSONDecodeError:
            grupos = grupos.strip("[]").split(",")

    if isinstance(grupos, str):
        grupos = [grupos]

    if not isinstance(grupos, list):
        return False

    grupos = {
        grupo.strip().strip("'\"")
        for grupo in grupos
        if isinstance(grupo, str)
    }

    permitidos = {"Tecnico", "Técnico", "Administrador"}

    return bool(grupos.intersection(permitidos))


def lambda_handler(event, context):
    try:
        service_id, estado_nuevo = validate_request(event)
    except ValueError as error:
        return response(400, {"message": str(error)})

    try:
        actor_sub = obtener_actor_autenticado(event)
    except ValueError:
        return response(401, {"message": "Usuario no autenticado."})

    if not verificar_rol_estado(event):
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
                actor_sub,
            )

            if cambio is None:
                connection.rollback()
                return response(
                    404,
                    {"message": "Servicio no encontrado."},
                )

            telefono = obtener_telefono_verificado(
                cambio["cliente_sub"]
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
