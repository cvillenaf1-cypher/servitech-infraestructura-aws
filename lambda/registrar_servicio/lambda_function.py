"""Registra un servicio en PostgreSQL desde un evento de API Gateway."""

import json
import os

import boto3
from servitech_authz import (
    AuthenticationError, AuthorizationDenied, identity_from_rest_event,
    CLIENTE, response,
)
import psycopg2


def get_request_body(event):
    if not isinstance(event, dict) or event.get("body") is None:
        raise ValueError("El body es obligatorio.")

    body = event["body"]
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("El body debe contener JSON válido.") from None

    if not isinstance(body, dict):
        raise ValueError("El body debe ser un objeto JSON.")

    for field in ("cliente", "equipo", "descripcion"):
        value = body.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"El campo {field} debe ser un texto no vacío.")

    return body




def get_connection():
    host = os.environ["DB_HOST"]
    port = int(os.environ["DB_PORT"])
    dbname = os.environ["DB_NAME"]
    username = os.environ["DB_USER"]
    region = os.environ["AWS_REGION"]

    rds_client = boto3.client("rds", region_name=region)

    token = rds_client.generate_db_auth_token(
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

def lambda_handler(event, context):
    try:
        body = get_request_body(event)
    except ValueError as error:
        return response(400, {"message": str(error)})

    try:
        identity = identity_from_rest_event(event)
        if CLIENTE not in identity.groups:
            raise AuthorizationDenied()
    except AuthenticationError:
        return response(401, {"message": "Se requiere un cliente autenticado."})
    except AuthorizationDenied:
        return response(403, {"message": "Solo el Cliente puede registrar su propio servicio."})

    sede_id = body.get("sede_id")
    if not isinstance(sede_id, str) or not sede_id.strip() or "\x00" in sede_id:
        return response(400, {"message": "Se requiere una sede válida."})

    connection = None
    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.servicios (
                    cliente, equipo, descripcion, cliente_sub, sede_id
                )
                SELECT %s, %s, %s, %s, id
                FROM public.sedes WHERE id = %s AND activa
                RETURNING id;
                """,
                (body["cliente"], body["equipo"], body["descripcion"],
                 identity.sub, sede_id),
            )
            created = cursor.fetchone()
            if created is None:
                connection.rollback()
                return response(403, {"message": "Sede no disponible."})
            service_id = created[0]

        connection.commit()
        return response(
            201,
            {"id": service_id, "message": "Servicio registrado correctamente"},
        )
    except Exception:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                print("RegistrarServicio: no se pudo revertir la transacción.")
        print("RegistrarServicio: error interno al registrar el servicio.")
        return response(500, {"message": "Error interno al registrar el servicio."})
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                print("RegistrarServicio: no se pudo cerrar la conexión.")
