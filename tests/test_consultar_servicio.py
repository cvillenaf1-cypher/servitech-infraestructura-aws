import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

# Evita necesitar AWS o PostgreSQL para estas pruebas.
sys.modules.setdefault("boto3", types.ModuleType("boto3"))
sys.modules.setdefault("psycopg2", types.ModuleType("psycopg2"))

ruta = (
    Path(__file__).resolve().parents[1]
    / "lambda"
    / "consultar_servicio"
    / "lambda_function.py"
)

spec = importlib.util.spec_from_file_location("consultar_prueba", ruta)
modulo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(modulo)


class CursorFalso:
    def __init__(self, resultado):
        self.resultado = resultado
        self.consulta = ""
        self.parametros = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, consulta, parametros):
        self.consulta = consulta
        self.parametros = parametros

    def fetchone(self):
        return self.resultado


class ConexionFalsa:
    def __init__(self, resultado):
        self.cursor_falso = CursorFalso(resultado)

    def cursor(self):
        return self.cursor_falso

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def evento(sub=None):
    datos = {"pathParameters": {"id": "10"}}

    if sub is not None:
        datos["requestContext"] = {
            "authorizer": {"claims": {"sub": sub}}
        }

    return datos


class TestConsultarServicio(unittest.TestCase):

    def test_sin_autenticacion(self):
        with patch.object(
            modulo,
            "get_connection",
            side_effect=AssertionError("No debe consultar la BD"),
        ):
            resultado = modulo.lambda_handler(evento(), None)

        self.assertEqual(resultado["statusCode"], 401)

    def test_filtro_por_propietario(self):
        conexion = ConexionFalsa(None)

        with patch.object(
            modulo, "get_connection", return_value=conexion
        ):
            resultado = modulo.lambda_handler(
                evento("cliente-123"), None
            )

        self.assertEqual(resultado["statusCode"], 404)
        self.assertIn(
            "cliente_sub", conexion.cursor_falso.consulta
        )
        self.assertEqual(
            conexion.cursor_falso.parametros,
            (10, "cliente-123"),
        )

    def test_consulta_autorizada(self):
        servicio = (
            10,
            "Ana",
            "Laptop",
            "Pantalla dañada",
            datetime(2026, 11, 24),
        )

        conexion = ConexionFalsa(servicio)

        with patch.object(
            modulo, "get_connection", return_value=conexion
        ):
            resultado = modulo.lambda_handler(
                evento("cliente-123"), None
            )

        self.assertEqual(resultado["statusCode"], 200)
        datos = json.loads(resultado["body"])
        self.assertEqual(datos["id"], 10)


if __name__ == "__main__":
    unittest.main()
