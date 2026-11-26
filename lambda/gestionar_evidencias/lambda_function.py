import json
import os
import re
import uuid

import boto3
from servitech_authz import (
    AuthenticationError, AuthorizationDenied, identity_from_rest_event,
    service_access_predicate, STAFF_ROLES, response,
)
from botocore.config import Config


TIPOS_PERMITIDOS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/pdf": "pdf",
}


class ConsultaNoDisponible(RuntimeError):
    pass


def verificar_acceso(servicio_id, identity):
    # Solo reenviar identidad ya validada del autorizador. IAM limita la
    # invocación a ConsultarServicio; no hay flag para saltarse su autorización.
    payload = {
        "pathParameters": {"id": str(servicio_id)},
        "requestContext": {"authorizer": {"claims": {
            "sub": identity.sub, "cognito:groups": sorted(identity.groups),
        }}},
    }
    try:
        client = boto3.client("lambda", config=Config(
            connect_timeout=1, read_timeout=18, retries={"total_max_attempts": 1},
        ))
        result = client.invoke(
            FunctionName=os.environ["CONSULTAR_SERVICIO_FUNCTION"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )
        stream = result.get("Payload")
        if stream is None:
            raise ConsultaNoDisponible()
        try:
            reply = json.loads(stream.read())
        finally:
            stream.close()
        if result.get("StatusCode") != 200 or result.get("FunctionError"):
            raise ConsultaNoDisponible()
        if reply.get("statusCode") in (401, 403, 404):
            return reply["statusCode"] if reply["statusCode"] != 401 else 403
        if reply.get("statusCode") != 200:
            raise ConsultaNoDisponible()
        # No emitir URL ante una respuesta incompleta o para otro servicio.
        returned_id = json.loads(reply["body"]).get("id")
        if type(returned_id) is not int or returned_id != servicio_id:
            raise ConsultaNoDisponible()
        return 200
    except Exception as error:
        raise ConsultaNoDisponible() from error


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

    identity = identity_from_rest_event(event)
    service_access_predicate(identity, allow_owner=True, staff_roles=STAFF_ROLES)

    body = event.get("body")

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("JSON inválido.") from None

    if not isinstance(body, dict):
        raise ValueError("Se requiere un body JSON.")

    return servicio_id, identity, body


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
        servicio_id, identity, body = validar_solicitud(event)

        estado = verificar_acceso(servicio_id, identity)

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

    except AuthenticationError:
        return response(401, {"message": "Usuario no autenticado."})

    except AuthorizationDenied:
        return response(403, {"message": "Acceso no autorizado."})

    except ConsultaNoDisponible:
        return response(503, {"message": "No se pudo validar el acceso al servicio."})

    except ValueError as error:
        return response(400, {"message": str(error)})

    except Exception:
        print("GestionarEvidencias: error interno.")
        return response(
            500,
            {"message": "Error interno al gestionar evidencias."},
        )
