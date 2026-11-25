import json
import os
from decimal import Decimal, InvalidOperation

import boto3
import psycopg2


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def get_connection():
    host = os.environ["DB_HOST"]
    port = int(os.environ["DB_PORT"])
    dbname = os.environ["DB_NAME"]
    username = os.environ["DB_USER"]
    region = os.environ["AWS_REGION"]

    token = boto3.client("rds", region_name=region).generate_db_auth_token(
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

    params = event.get("pathParameters") or {}
    if not isinstance(params, dict):
        raise ValueError("ID inválido.")

    try:
        service_id = int(params.get("id"))
        if service_id <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("ID inválido.") from None

    body = event.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("JSON inválido.") from None

    if not isinstance(body, dict):
        raise ValueError("El body debe ser un objeto JSON.")

    allowed = ("diagnostico", "tratamiento", "presupuesto")
    changes = {key: body[key] for key in allowed if key in body}

    if not changes:
        raise ValueError("No se enviaron campos para actualizar.")

    for key in ("diagnostico", "tratamiento"):
        if key in changes:
            value = changes[key]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"El campo {key} debe ser un texto no vacío.")
            changes[key] = value.strip()

    if "presupuesto" in changes:
        value = changes["presupuesto"]
        if isinstance(value, bool):
            raise ValueError("Presupuesto inválido.")
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("Presupuesto inválido.") from None

        if not amount.is_finite() or amount < 0:
            raise ValueError("El presupuesto debe ser un número no negativo.")

        changes["presupuesto"] = amount

    return service_id, changes


def verificar_rol_operativo(event):
    if not isinstance(event, dict):
        return 401

    contexto = event.get("requestContext") or {}
    if not isinstance(contexto, dict):
        return 401

    autorizador = contexto.get("authorizer") or {}
    if not isinstance(autorizador, dict):
        return 401

    claims = autorizador.get("claims") or {}
    if not isinstance(claims, dict):
        return 401

    usuario_sub = claims.get("sub")

    if not isinstance(usuario_sub, str) or not usuario_sub.strip():
        return 401

    grupos = claims.get("cognito:groups", [])

    if isinstance(grupos, str):
        grupos = {
            grupo.strip().strip('"').strip("'")
            for grupo in grupos.strip("[]").split(",")
        }
    elif isinstance(grupos, list):
        grupos = {
            grupo.strip()
            for grupo in grupos
            if isinstance(grupo, str)
        }
    else:
        grupos = set()

    roles_permitidos = {
        "Tecnico",
        "Técnico",
        "Administrador",
    }

    if not grupos.intersection(roles_permitidos):
        return 403

    return 200


def lambda_handler(event, context):
    autorizacion = verificar_rol_operativo(event)

    if autorizacion == 401:
        return response(
            401,
            {"message": "Usuario no autenticado."},
        )

    if autorizacion == 403:
        return response(
            403,
            {"message": "No tienes permisos para actualizar diagnósticos."},
        )

    try:
        service_id, changes = validate_request(event)
    except ValueError as error:
        return response(400, {"message": str(error)})

    connection = None

    try:
        connection = get_connection()

        # Solo se construyen columnas de una lista permitida.
        assignments = ", ".join(f"{column} = %s" for column in changes)
        values = list(changes.values()) + [service_id]

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE public.servicios
                SET {assignments}
                WHERE id = %s
                RETURNING id, diagnostico, tratamiento, presupuesto;
                """,
                values,
            )
            updated = cursor.fetchone()

        if updated is None:
            connection.rollback()
            return response(404, {"message": "Servicio no encontrado."})

        connection.commit()

        return response(200, {
            "id": updated[0],
            "diagnostico": updated[1],
            "tratamiento": updated[2],
            "presupuesto": str(updated[3]) if updated[3] is not None else None,
            "message": "Diagnóstico actualizado correctamente.",
        })

    except Exception:
        if connection is not None:
            connection.rollback()
        print("ActualizarDiagnostico: error interno.")
        return response(500, {"message": "Error interno."})

    finally:
        if connection is not None:
            connection.close()
