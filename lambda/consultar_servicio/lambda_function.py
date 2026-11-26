"""Consulta un servicio en PostgreSQL desde un evento de API Gateway."""

from datetime import datetime
import json
import os

import boto3
from servitech_authz import (
    AuthenticationError, AuthorizationDenied, identity_from_rest_event,
    service_access_predicate, STAFF_ROLES, CLIENTE, response,
)
import psycopg2


def get_service_id(event):
    if not isinstance(event, dict):
        raise ValueError("El ID debe ser un entero positivo.")

    parameters = event.get("pathParameters")
    if not isinstance(parameters, dict):
        raise ValueError("El ID debe ser un entero positivo.")

    value = parameters.get("id")
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("El ID debe ser un entero positivo.")
    if isinstance(value, str) and not value.strip().isdecimal():
        raise ValueError("El ID debe ser un entero positivo.")

    try:
        service_id = int(value)
    except ValueError:
        raise ValueError("El ID debe ser un entero positivo.") from None
    if service_id <= 0:
        raise ValueError("El ID debe ser un entero positivo.")

    return service_id




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
        service_id = get_service_id(event)
    except ValueError as error:
        return response(400, {"message": str(error)})

    try:
        identity = identity_from_rest_event(event)
        access = service_access_predicate(identity, allow_owner=True, staff_roles=STAFF_ROLES)
    except AuthenticationError:
        return response(401, {"message": "Usuario no autenticado."})
    except AuthorizationDenied:
        return response(403, {"message": "Acceso no autorizado."})

    connection = None
    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    cliente,
                    equipo,
                    descripcion,
                    fecha_registro
                FROM public.servicios AS svc
                WHERE svc.id = %s AND
                """ + access.sql,
                (service_id, *access.params),
            )
            service = cursor.fetchone()

        connection.commit()
        if service is None:
            return response(404, {"message": "Servicio no encontrado"})

        registered_at = service[4]
        if isinstance(registered_at, datetime):
            registered_at = registered_at.isoformat()

        return response(
            200,
            {
                "id": service[0],
                "cliente": service[1],
                "equipo": service[2],
                "descripcion": service[3],
                "fecha_registro": registered_at,
            },
        )
    except Exception:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                print("ConsultarServicio: no se pudo revertir la transacción.")
        print("ConsultarServicio: error interno al consultar el servicio.")
        return response(500, {"message": "Error interno al consultar el servicio."})
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                print("ConsultarServicio: no se pudo cerrar la conexión.")
