"""Pruebas locales con respuestas de Cognito ficticias; no contactan AWS."""
import copy
import json
import unittest
from unittest.mock import MagicMock, Mock, patch

from test_estado_evidencias import estado, evento


class TestCognitoEstado(unittest.TestCase):
    def setUp(self):
        self.sub = 'cliente-opaco/á"\\identidad'
        self.telefono = "+12025550123"  # Solo fixture, nunca se registra en AWS.
        self.usuario = {
            "Username": "cliente-prueba",
            "Attributes": [{"Name": "sub", "Value": self.sub}],
        }
        self.actual = {
            "Username": "cliente-prueba",
            "Enabled": True,
            "UserAttributes": [
                {"Name": "sub", "Value": self.sub},
                {"Name": "phone_number", "Value": self.telefono},
                {"Name": "phone_number_verified", "Value": "true"},
            ],
        }
        self.cognito = Mock()
        self.cognito.list_users.return_value = {"Users": [self.usuario]}
        self.cognito.admin_get_user.return_value = self.actual
        self.context = Mock()
        self.context.get_remaining_time_in_millis.return_value = 15000
        self.env = patch.dict(estado.os.environ, {
            "COGNITO_USER_POOL_ID": "pool-prueba",
            "AWS_REGION": "us-east-2",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.factory = patch.object(
            estado.boto3, "client", return_value=self.cognito, create=True
        )
        self.client = self.factory.start()
        self.addCleanup(self.factory.stop)

    def consultar(self):
        return estado.obtener_telefono_verificado(self.sub, self.context)

    def ejecutar_handler(self, codigo):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            ("Recibido", 1, self.sub), (2,), ("evento-prueba",),
        ]
        with patch.object(estado, "get_connection", return_value=connection), \
                patch.object(estado, "publicar_evento_pendiente") as publicar:
            publicar.side_effect = lambda *args: (
                connection.commit.assert_called_once_with() or False
            )
            solicitud = evento(sub="tecnico-distinto", grupos=["Técnico"])
            # Datos no confiables del body deben ignorarse para elegir destinatario.
            body = json.loads(solicitud["body"])
            body.update(cliente_sub="intruso", telefono=self.telefono)
            solicitud["body"] = json.dumps(body)
            resultado = estado.lambda_handler(solicitud, self.context)
        self.assertEqual(resultado["statusCode"], codigo)
        connection.close.assert_called_once_with()
        consultas = [c.args[0] for c in cursor.execute.call_args_list]
        self.assertTrue(any("UPDATE public.servicios" in q for q in consultas))
        self.assertTrue(any("INSERT INTO public.servicio_estado_historial" in q
                            for q in consultas))
        if codigo != 202:
            connection.rollback.assert_called_once_with()
            connection.commit.assert_not_called()
            publicar.assert_not_called()
            self.assertFalse(any("INSERT INTO public.servicio_outbox" in q
                                 for q in consultas))
            self.assertNotIn(self.telefono, resultado["body"])
            self.assertNotIn(self.sub, resultado["body"])
        else:
            connection.rollback.assert_not_called()
            publicar.assert_called_once()
            self.assertEqual(publicar.call_args.args[2]["cliente_sub"], self.sub)
            self.assertEqual(publicar.call_args.args[3], self.telefono)
            insercion = cursor.execute.call_args_list[-1]
            self.assertIn("INSERT INTO public.servicio_outbox", insercion.args[0])
            self.assertEqual(insercion.args[1][2], self.sub)
            self.assertEqual(insercion.args[1][-1], self.telefono)

    def test_sub_opaco_y_telefono_de_admin_get_user(self):
        self.usuario["Attributes"].extend([
            {"Name": "phone_number", "Value": "+12025550124"},
            {"Name": "phone_number_verified", "Value": "false"},
        ])
        self.assertEqual(self.consultar(), self.telefono)
        filtro = self.cognito.list_users.call_args.kwargs["Filter"]
        self.assertEqual(json.loads(filtro.removeprefix("sub = ")), self.sub)
        self.cognito.admin_get_user.assert_called_once_with(
            UserPoolId="pool-prueba", Username="cliente-prueba"
        )

    def test_actor_sub_no_se_normaliza(self):
        self.assertEqual(estado.obtener_actor_autenticado(evento(sub=" opaco ")),
                         " opaco ")

    def test_sub_invalido_no_consulta(self):
        for sub in (None, "", "   ", 42, "x" * 257):
            with self.subTest(sub=sub), self.assertRaises(ValueError):
                estado.obtener_telefono_verificado(sub, self.context)
        self.client.assert_not_called()

    def test_paginacion_con_pagina_vacia(self):
        self.cognito.list_users.side_effect = [
            {"Users": [], "PaginationToken": "siguiente"},
            {"Users": [self.usuario]},
        ]
        self.assertEqual(self.consultar(), self.telefono)
        self.assertEqual(self.cognito.list_users.call_args.kwargs["PaginationToken"],
                         "siguiente")

    def test_limite_paginacion_hace_rollback(self):
        self.cognito.list_users.return_value = {
            "Users": [], "PaginationToken": "repetido",
        }
        self.ejecutar_handler(503)
        self.assertEqual(self.cognito.list_users.call_count, 5)
        self.cognito.admin_get_user.assert_not_called()

    def test_identidad_ambigua_entre_paginas(self):
        self.cognito.list_users.side_effect = [
            {"Users": [self.usuario], "PaginationToken": "siguiente"},
            {"Users": [self.usuario]},
        ]
        self.ejecutar_handler(409)
        self.cognito.admin_get_user.assert_not_called()

    def test_usuario_no_encontrado(self):
        self.cognito.list_users.return_value = {"Users": []}
        self.ejecutar_handler(409)
        self.cognito.admin_get_user.assert_not_called()

    def test_identidad_incorrecta_list_users(self):
        self.usuario["Attributes"][0]["Value"] = "otro-cliente"
        self.ejecutar_handler(409)
        self.cognito.admin_get_user.assert_not_called()

    def test_identidad_incorrecta_admin_get_user(self):
        self.actual["UserAttributes"][0]["Value"] = "otro-cliente"
        self.ejecutar_handler(409)

    def test_username_incorrecto_admin_get_user(self):
        self.actual["Username"] = "otro-username"
        self.ejecutar_handler(409)

    def test_usuario_deshabilitado_o_sin_enabled(self):
        for enabled in (False, None, "true"):
            with self.subTest(enabled=enabled):
                self.actual["Enabled"] = enabled
                self.ejecutar_handler(409)

    def test_telefono_no_verificado_aunque_list_users_diga_true(self):
        self.usuario["Attributes"] = copy.deepcopy(self.actual["UserAttributes"])
        for verificado in ("false", None, True, "TRUE"):
            with self.subTest(verificado=verificado):
                self.actual["UserAttributes"][2]["Value"] = verificado
                self.ejecutar_handler(409)

    def test_telefono_invalido_o_ausente(self):
        for telefono in (None, "", "12025550123", "+0123", "+1", "+" + "1" * 16):
            with self.subTest(telefono=telefono):
                self.actual["UserAttributes"][1]["Value"] = telefono
                self.ejecutar_handler(409)

    def test_error_conexion_list_users(self):
        self.cognito.list_users.side_effect = ConnectionError("detalle privado")
        self.ejecutar_handler(503)
        self.cognito.admin_get_user.assert_not_called()

    def test_error_admin_get_user(self):
        self.cognito.admin_get_user.side_effect = TimeoutError("detalle privado")
        self.ejecutar_handler(503)

    def test_error_creacion_cliente(self):
        self.client.side_effect = RuntimeError("credenciales no disponibles")
        self.ejecutar_handler(503)

    def test_presupuesto_insuficiente_antes_de_admin_get_user(self):
        self.context.get_remaining_time_in_millis.side_effect = [10000, 4000]
        self.ejecutar_handler(503)
        self.cognito.admin_get_user.assert_not_called()

    def test_pool_sin_configurar(self):
        with patch.dict(estado.os.environ, {"COGNITO_USER_POOL_ID": ""}):
            self.ejecutar_handler(503)
        self.client.assert_not_called()

    def test_timeout_y_reintentos_sdk_acotados(self):
        with patch.object(estado, "Config") as config:
            self.consultar()
        config.assert_called_once_with(
            connect_timeout=1, read_timeout=2,
            retries={"mode": "standard", "total_max_attempts": 1},
        )

    def test_exito_consulta_propietario_bd_y_publica_despues_commit(self):
        self.ejecutar_handler(202)
        filtro = self.cognito.list_users.call_args.kwargs["Filter"]
        self.assertEqual(json.loads(filtro.removeprefix("sub = ")), self.sub)


if __name__ == "__main__":
    unittest.main()
