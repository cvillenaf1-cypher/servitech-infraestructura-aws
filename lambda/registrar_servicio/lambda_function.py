"""Registra un servicio en PostgreSQL desde un evento de API Gateway."""

import json
import os

import boto3
import psycopg2


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Content-Type": "application/json",
        },
        "body": json.dumps(body),
    }


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

def obtener_cliente_autenticado(event):
    if not isinstance(event, dict):
        return None

    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer") or {}
    claims = authorizer.get("claims") or {}

    if not isinstance(claims, dict):
        return None

    cliente_sub = claims.get("sub")

    if not isinstance(cliente_sub, str):
        return None

    cliente_sub = cliente_sub.strip()

    return cliente_sub if cliente_sub else None

def lambda_handler(event, context):
    try:
        body = get_request_body(event)
    except ValueError as error:
        return response(400, {"message": str(error)})

    cliente_sub = obtener_cliente_autenticado(event)

    if cliente_sub is None:
        return response(
            401,
            {"message": "Se requiere un cliente autenticado."},
        )

    connection = None
    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
             INSERT INTO public.servicios (
                cliente,
                equipo,
                descripcion,
                cliente_sub
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id;
                """,
                        (
            body["cliente"],
            body["equipo"],
            body["descripcion"],
            cliente_sub,
        ),
            )
            service_id = cursor.fetchone()[0]

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
