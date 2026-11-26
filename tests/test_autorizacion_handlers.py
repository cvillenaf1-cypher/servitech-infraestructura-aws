"""Autorización y efectos de los handlers con BD/SDK simulados, sin AWS."""
import io
import json
import unittest
from unittest.mock import MagicMock, Mock, patch

from test_estado_evidencias import cargar_modulo, estado, evidencias, evento
from servitech_authz import Identity, CLIENTE

registro = cargar_modulo("registro_auth_test", "registrar_servicio")
diagnostico = cargar_modulo("diagnostico_auth_test", "actualizar_diagnostico")
consulta = cargar_modulo("consulta_auth_test", "consultar_servicio")


def solicitud(grupos=("Cliente",), **body):
    request = evento(sub="sub/opaco", grupos=list(grupos))
    request["body"] = json.dumps(body or {
        "cliente": "Sintético", "equipo": "Prueba", "descripcion": "Prueba",
        "sede_id": "A", "cliente_sub": "suplantado",
    })
    return request


class TestAutorizacionHandlers(unittest.TestCase):
    def test_registro_usa_sub_confiable_sin_asignacion_operativa(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (10,)
        with patch.object(registro, "get_connection", return_value=connection):
            result = registro.lambda_handler(solicitud(), None)
        self.assertEqual(result["statusCode"], 201)
        query, params = cursor.execute.call_args.args
        self.assertIn("FROM public.sedes WHERE id = %s AND activa", query)
        self.assertNotIn("usuario_sede_rol", query)
        self.assertEqual(params[-2:], ("sub/opaco", "A"))
        self.assertNotIn("suplantado", params)
        connection.commit.assert_called_once_with()

    def test_registro_deniega_sede_no_activa(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = None
        with patch.object(registro, "get_connection", return_value=connection):
            result = registro.lambda_handler(solicitud(), None)
        self.assertEqual(result["statusCode"], 403)
        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()

    def test_administrador_sin_cliente_no_registra(self):
        with patch.object(registro, "get_connection") as connect:
            self.assertEqual(registro.lambda_handler(solicitud(("Administrador",)), None)["statusCode"], 403)
        connect.assert_not_called()

    def test_diagnostico_sin_fila_autorizada_revierte(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        with patch.object(diagnostico, "get_connection", return_value=connection):
            result = diagnostico.lambda_handler(solicitud(("Técnico",), diagnostico="Revisado"), None)
        self.assertEqual(result["statusCode"], 404)
        self.assertIn("auth_assignment", cursor.execute.call_args.args[0])
        self.assertEqual(cursor.execute.call_args.args[1][-2:], ["sub/opaco", "Técnico"])
        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()

    def test_estado_sin_acceso_o_revocado_no_consulta_ni_publica(self):
        for rows, status in (([None], 404), ([("Recibido", 1, "propietario"), None], 403)):
            with self.subTest(status=status):
                connection = MagicMock()
                cursor = connection.cursor.return_value.__enter__.return_value
                cursor.fetchone.side_effect = rows
                with patch.object(estado, "get_connection", return_value=connection), \
                        patch.object(estado, "obtener_telefono_verificado") as phone, \
                        patch.object(estado, "publicar_evento_pendiente") as publish:
                    result = estado.lambda_handler(solicitud(("Técnico",), estado="Reparado"), None)
                self.assertEqual(result["statusCode"], status)
                connection.rollback.assert_called_once_with()
                connection.commit.assert_not_called()
                phone.assert_not_called()
                publish.assert_not_called()
                self.assertFalse(any("INSERT" in call.args[0] for call in cursor.execute.call_args_list))

    def test_alias_tecnico_no_concede_acceso(self):
        for module in (consulta, diagnostico, estado):
            with self.subTest(module=module.__name__), patch.object(module, "get_connection") as connect:
                result = module.lambda_handler(solicitud(("Tecnico",), diagnostico="Prueba", estado="Reparado"), None)
                self.assertEqual(result["statusCode"], 403)
                connect.assert_not_called()


class TestConsultaDesdeEvidencias(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.factory = patch.object(evidencias.boto3, "client", return_value=self.client, create=True)
        self.factory.start()
        self.addCleanup(self.factory.stop)
        self.env = patch.dict(evidencias.os.environ, {"CONSULTAR_SERVICIO_FUNCTION": "consulta-prueba"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.identity = Identity("sub/opaco", frozenset((CLIENTE,)))

    def reply(self, status=200, body=None, **kwargs):
        stream = io.BytesIO(json.dumps({"statusCode": status, "body": json.dumps(body or {"id": 10})}).encode())
        self.client.invoke.return_value = {"StatusCode": 200, "Payload": stream, **kwargs}
        return stream

    def test_invocacion_sincrona_con_identidad_minima(self):
        stream = self.reply()
        self.assertEqual(evidencias.verificar_acceso(10, self.identity), 200)
        args = self.client.invoke.call_args.kwargs
        self.assertEqual(args["FunctionName"], "consulta-prueba")
        self.assertEqual(args["InvocationType"], "RequestResponse")
        payload = json.loads(args["Payload"])
        self.assertEqual(set(payload), {"pathParameters", "requestContext"})
        self.assertEqual(payload["requestContext"]["authorizer"]["claims"]["sub"], self.identity.sub)
        self.assertTrue(stream.closed)

    def test_denegaciones_no_crean_url(self):
        for remote, expected in ((401, 403), (403, 403), (404, 404)):
            with self.subTest(status=remote):
                self.reply(remote)
                result = evidencias.lambda_handler(solicitud(accion="subir", tipo="image/png"), None)
                self.assertEqual(result["statusCode"], expected)
                self.client.generate_presigned_url.assert_not_called()

    def test_respuestas_incorrectas_no_crean_url(self):
        for status, body, kwargs in (
            (500, {"id": 10}, {}), (200, {"id": 11}, {}),
            (200, {"id": True}, {}), (200, {"otro": 10}, {}),
            (200, {"id": 10}, {"FunctionError": "Unhandled"}),
        ):
            with self.subTest(status=status, body=body, kwargs=kwargs):
                self.reply(status, body, **kwargs)
                result = evidencias.lambda_handler(solicitud(accion="subir", tipo="image/png"), None)
                self.assertEqual(result["statusCode"], 503)
                self.client.generate_presigned_url.assert_not_called()

    def test_error_conexion_no_crea_url(self):
        self.client.invoke.side_effect = TimeoutError("simulado")
        result = evidencias.lambda_handler(solicitud(accion="subir", tipo="image/png"), None)
        self.assertEqual(result["statusCode"], 503)
        self.client.generate_presigned_url.assert_not_called()

    def test_json_invalido_no_crea_url(self):
        self.client.invoke.return_value = {"StatusCode": 200, "Payload": io.BytesIO(b"invalido")}
        result = evidencias.lambda_handler(solicitud(accion="subir", tipo="image/png"), None)
        self.assertEqual(result["statusCode"], 503)
        self.client.generate_presigned_url.assert_not_called()

    def test_acceso_confirmado_permite_url(self):
        self.reply()
        self.client.generate_presigned_url.return_value = "url-sintetica"
        with patch.dict(evidencias.os.environ, {"EVIDENCIAS_BUCKET": "bucket-prueba", "AWS_REGION": "us-east-2"}):
            result = evidencias.lambda_handler(solicitud(accion="subir", tipo="image/png"), None)
        self.assertEqual(result["statusCode"], 200)
        self.client.generate_presigned_url.assert_called_once()


if __name__ == "__main__":
    unittest.main()
