import json
import os
import re
import uuid

import boto3
import psycopg2
from botocore.config import Config


TIPOS_PERMITIDOS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/pdf": "pdf",
}


def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body),
    }


def get_connection():
    host = os.environ["DB_HOST"]
    port = int(os.environ["DB_PORT"])
    region = os.environ["AWS_REGION"]
    username = os.environ["DB_USER"]

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
        dbname=os.environ["DB_NAME"],
        user=username,
        password=token,
        sslmode="verify-full",
        sslrootcert="/var/task/amazon-trust-roots.pem",
        connect_timeout=5,
    )


def validar_solicitud(event):
    if not isinstance(event, dict):
        raise ValueError("Solicitud inválida.")

    parametros = event.get("pathParameters") or {}
    if not isinstance(parametros, dict):
        raise ValueError("ID inválido.")

    valor_id = parametros.get("id")

    if isinstance(valor_id, bool) or not re.fullmatch(
        r"[0-9]+", str(valor_id)
    ):
        raise ValueError("ID inválido.")

    servicio_id = int(valor_id)
    if servicio_id <= 0:
        raise ValueError("ID inválido.")

    contexto = event.get("requestContext") or {}
    autorizador = contexto.get("authorizer") or {}
    claims = autorizador.get("claims") or {}

    if not isinstance(claims, dict):
        return servicio_id, None, None

    usuario_sub = claims.get("sub")
    if not isinstance(usuario_sub, str) or not usuario_sub.strip():
        return servicio_id, None, None

    body = event.get("body")

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("JSON inválido.") from None

    if not isinstance(body, dict):
        raise ValueError("Se requiere un body JSON.")

    return servicio_id, usuario_sub.strip(), body


def verificar_propietario(servicio_id, usuario_sub):
    conexion = get_connection()

    try:
        with conexion.cursor() as cursor:
            cursor.execute(
                """
                SELECT cliente_sub
                FROM public.servicios
                WHERE id = %s;
                """,
                (servicio_id,),
            )
            resultado = cursor.fetchone()

        if resultado is None:
            return 404

        if not resultado[0] or resultado[0] != usuario_sub:
            return 403

        return 200

    finally:
        conexion.close()


def generar_url_subida(s3, bucket, servicio_id, body, expiracion):
    tipo = body.get("tipo")

    if tipo not in TIPOS_PERMITIDOS:
        raise ValueError(
            "Solo se permiten JPG, PNG y PDF."
        )

    extension = TIPOS_PERMITIDOS[tipo]

    clave = (
        f"servicios/{servicio_id}/"
        f"{uuid.uuid4().hex}.{extension}"
    )

    url = s3.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": bucket,
            "Key": clave,
            "ContentType": tipo,
        },
        ExpiresIn=expiracion,
        HttpMethod="PUT",
    )

    return {
        "accion": "subir",
        "clave": clave,
        "url": url,
        "metodo": "PUT",
        "headers": {
            "Content-Type": tipo,
        },
        "expira_en_segundos": expiracion,
    }


def generar_url_descarga(s3, bucket, servicio_id, body, expiracion):
    clave = body.get("clave")

    patron = (
        rf"servicios/{servicio_id}/"
        r"[0-9a-f]{32}\.(jpg|png|pdf)"
    )

    if not isinstance(clave, str) or not re.fullmatch(
        patron, clave
    ):
        raise ValueError("Clave de evidencia inválida.")

    url = s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": bucket,
            "Key": clave,
        },
        ExpiresIn=expiracion,
        HttpMethod="GET",
    )

    return {
        "accion": "descargar",
        "clave": clave,
        "url": url,
        "metodo": "GET",
        "expira_en_segundos": expiracion,
    }


def lambda_handler(event, context):
    try:
        servicio_id, usuario_sub, body = validar_solicitud(event)

        if usuario_sub is None:
            return response(
                401, {"message": "Usuario no autenticado."}
            )

        estado = verificar_propietario(
            servicio_id, usuario_sub
        )

        if estado == 404:
            return response(
                404, {"message": "Servicio no encontrado."}
            )

        if estado == 403:
            return response(
                403, {"message": "Acceso no autorizado."}
            )

        bucket = os.environ["EVIDENCIAS_BUCKET"]
        expiracion = 300

        s3 = boto3.client(
            "s3",
            region_name=os.environ["AWS_REGION"],
            config=Config(signature_version="s3v4"),
        )

        accion = body.get("accion")

        if accion == "subir":
            resultado = generar_url_subida(
                s3, bucket, servicio_id, body, expiracion
            )
        elif accion == "descargar":
            resultado = generar_url_descarga(
                s3, bucket, servicio_id, body, expiracion
            )
        else:
            raise ValueError("Acción inválida.")

        return response(200, resultado)

    except ValueError as error:
        return response(400, {"message": str(error)})

    except Exception:
        print("GestionarEvidencias: error interno.")
        return response(
            500,
            {"message": "Error interno al gestionar evidencias."},
        )
