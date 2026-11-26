
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda" / "shared"))

sys.modules.setdefault("boto3", types.ModuleType("boto3"))
sys.modules.setdefault("psycopg2", types.ModuleType("psycopg2"))

try:
    from botocore.config import Config
except ImportError:
    botocore = types.ModuleType("botocore")
    config = types.ModuleType("botocore.config")
    config.Config = lambda **kwargs: None
    sys.modules["botocore"] = botocore
    sys.modules["botocore.config"] = config


def cargar_modulo(nombre, carpeta):
    ruta = (
        Path(__file__).resolve().parents[1]
        / "lambda"
        / carpeta
        / "lambda_function.py"
    )
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


estado = cargar_modulo("estado_prueba", "actualizar_estado")
evidencias = cargar_modulo(
    "evidencias_prueba", "gestionar_evidencias"
)


def evento(sub="usuario-123", grupos=None):
    return {
        "pathParameters": {"id": "10"},
        "body": json.dumps({
            "accion": "subir",
            "tipo": "image/png",
            "estado": "En reparación",
        }),
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": sub,
                    "cognito:groups": grupos or [],
                }
            }
        },
    }


class TestEstado(unittest.TestCase):

    def test_cliente_no_puede_actualizar(self):
        with patch.object(
            estado,
            "get_connection",
            side_effect=AssertionError("No usar la BD"),
        ):
            resultado = estado.lambda_handler(
                evento(grupos=["Cliente"]), None
            )

        self.assertEqual(resultado["statusCode"], 403)

    def test_tecnico_tiene_rol(self):
        self.assertTrue(
            estado.verificar_rol_estado(
                evento(grupos=["Técnico"])
            )
        )

    def test_usuario_sin_rol(self):
        self.assertFalse(
            estado.verificar_rol_estado(
                evento(grupos=["Cliente"])
            )
        )


class TestEvidencias(unittest.TestCase):

    def test_sin_autenticacion(self):
        solicitud = {
            "pathParameters": {"id": "10"},
            "body": json.dumps({
                "accion": "subir",
                "tipo": "image/png",
            }),
        }

        resultado = evidencias.lambda_handler(
            solicitud, None
        )

        self.assertEqual(resultado["statusCode"], 401)

    def test_cliente_ajeno(self):
        with patch.object(
            evidencias,
            "verificar_acceso",
            return_value=403,
        ):
            resultado = evidencias.lambda_handler(
                evento(grupos=["Cliente"]), None
            )

        self.assertEqual(resultado["statusCode"], 403)

    def test_bloquea_clave_ajena(self):
        s3 = Mock()

        with self.assertRaises(ValueError):
            evidencias.generar_url_descarga(
                s3,
                "bucket-prueba",
                10,
                {
                    "clave": (
                        "servicios/20/"
                        + "a" * 32
                        + ".jpg"
                    )
                },
                300,
            )

        s3.generate_presigned_url.assert_not_called()

    def test_url_subida(self):
        s3 = Mock()
        s3.generate_presigned_url.return_value = (
            "https://example.com/presigned"
        )

        resultado = evidencias.generar_url_subida(
            s3,
            "bucket-prueba",
            10,
            {"tipo": "image/png"},
            300,
        )

        self.assertEqual(resultado["metodo"], "PUT")
        self.assertTrue(
            resultado["clave"].startswith("servicios/10/")
        )
        self.assertEqual(
            resultado["headers"]["Content-Type"],
            "image/png",
        )


if __name__ == "__main__":
    unittest.main()
