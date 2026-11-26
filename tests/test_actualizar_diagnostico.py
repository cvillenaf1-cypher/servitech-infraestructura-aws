
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda" / "shared"))

sys.modules.setdefault("boto3", types.ModuleType("boto3"))
sys.modules.setdefault("psycopg2", types.ModuleType("psycopg2"))

ruta = (
    Path(__file__).resolve().parents[1]
    / "lambda"
    / "actualizar_diagnostico"
    / "lambda_function.py"
)

spec = importlib.util.spec_from_file_location(
    "diagnostico_prueba", ruta
)
modulo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(modulo)


def evento(sub=None, grupos=None):
    datos = {
        "pathParameters": {"id": "0"},
        "body": {"diagnostico": "Prueba"},
    }

    if sub is not None:
        datos["requestContext"] = {
            "authorizer": {
                "claims": {
                    "sub": sub,
                    "cognito:groups": grupos or [],
                }
            }
        }

    return datos


class TestActualizarDiagnostico(unittest.TestCase):

    def test_sin_autenticacion(self):
        with patch.object(
            modulo,
            "get_connection",
            side_effect=AssertionError("No debe usar la BD"),
        ):
            resultado = modulo.lambda_handler(evento(), None)

        self.assertEqual(resultado["statusCode"], 401)

    def test_cliente_sin_permisos(self):
        with patch.object(
            modulo,
            "get_connection",
            side_effect=AssertionError("No debe usar la BD"),
        ):
            resultado = modulo.lambda_handler(
                evento("cliente-123", ["Cliente"]), None
            )

        self.assertEqual(resultado["statusCode"], 403)

    def test_tecnico_autorizado(self):
        with patch.object(
            modulo,
            "get_connection",
            side_effect=AssertionError("ID inválido no debe usar BD"),
        ):
            resultado = modulo.lambda_handler(
                evento("tecnico-123", ["Técnico"]), None
            )

        # Superó la autorización y llegó a validar el ID.
        self.assertEqual(resultado["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
