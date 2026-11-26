import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda" / "shared"))
import servitech_authz as auth


def event(sub="sub/opaco", groups="Cliente"):
    return {"requestContext": {"authorizer": {"claims": {"sub": sub, "cognito:groups": groups}}}}


def cursor(row=(1,)):
    result = Mock()
    result.fetchone.return_value = row
    result.connection.autocommit = False
    return result


class TestIdentity(unittest.TestCase):
    def test_sub_opaco_se_conserva_exactamente(self):
        for value in ("sub/no-uuid", " sub con espacios ", "O'Reilly\\雪"):
            with self.subTest(value=value):
                self.assertEqual(auth.identity_from_rest_event(event(value)).sub, value)

    def test_sub_invalido(self):
        for value in (None, "", " \t", 1, True, [], {}, "sub\x00otro"):
            with self.subTest(value=value), self.assertRaises(auth.AuthenticationError):
                auth.identity_from_rest_event(event(value))

    def test_estructuras_ausentes_o_invalidas(self):
        for value in (None, [], {}, {"requestContext": []}, {"requestContext": {"authorizer": "x"}},
                      {"requestContext": {"authorizer": {"claims": []}}}):
            with self.subTest(value=value), self.assertRaises(auth.AuthenticationError):
                auth.identity_from_rest_event(value)

    def test_no_acepta_body_cabeceras_o_claims_http_v2(self):
        forged = {"body": event(), "headers": {"sub": "sub/opaco", "cognito:groups": "Administrador"},
                  "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "sub/opaco"}}}}}
        with self.assertRaises(auth.AuthenticationError):
            auth.identity_from_rest_event(forged)

    def test_claims_prevalecen_sin_leer_body_o_headers(self):
        value = event()
        value.update(body={"sub": "atacante"}, headers={"cognito:groups": "Administrador"})
        identity = auth.identity_from_rest_event(value)
        self.assertEqual(identity.groups, frozenset((auth.CLIENTE,)))
        self.assertEqual(identity.sub, "sub/opaco")

    def test_csv_rest_y_lista_claim_validos(self):
        for value in ("Cliente,Técnico,Administrador", ["Cliente", "Técnico", "Administrador"]):
            with self.subTest(value=value):
                self.assertEqual(auth.parse_groups(value), auth.GROUPS)

    def test_grupo_individual(self):
        for role in auth.GROUPS:
            self.assertEqual(auth.parse_groups(role), frozenset((role,)))

    def test_formatos_invalidos_no_se_reparan(self):
        for value in ("", "Tecnico", "cliente", "AdministradorGlobal", "Cliente, Técnico",
                      '["Cliente"]', "[Cliente]", "'Administrador'", "Cliente,", "Cliente,Cliente",
                      ["Cliente", "Tecnico"], ["Cliente", "Cliente"], [1], [None], [["Cliente"]],
                      True, 1, {}, ("Cliente",), "Técnico\n", "Cliente,Desconocido"):
            with self.subTest(value=value), self.assertRaises(auth.AuthorizationDenied):
                auth.parse_groups(value)

    def test_sin_grupo_no_concede_acceso(self):
        for value in (None, []):
            identity = auth.identity_from_rest_event(event(groups=value))
            with self.assertRaises(auth.AuthorizationDenied):
                auth.service_access_predicate(identity, allow_owner=True, staff_roles=auth.STAFF_ROLES)

    def test_identity_no_permite_grupos_mutables_o_desconocidos(self):
        for groups in (["Cliente"], "Cliente", frozenset(("Tecnico",))):
            with self.subTest(groups=groups), self.assertRaises(auth.AuthorizationDenied):
                auth.Identity("sub", groups)

    def test_propiedad_es_igualdad_exacta(self):
        identity = auth.identity_from_rest_event(event(" sub "))
        self.assertTrue(auth.is_owner(identity, " sub "))
        for owner in ("sub", "ajeno", None, "", 1):
            self.assertFalse(auth.is_owner(identity, owner))

    def test_rol_exacto_sin_jerarquia(self):
        identity = auth.identity_from_rest_event(event(groups="Administrador"))
        self.assertTrue(auth.has_role(identity, auth.ADMINISTRADOR))
        self.assertFalse(auth.has_role(identity, auth.TECNICO))
        with self.assertRaises(ValueError):
            auth.has_role(identity, "Tecnico")


class TestSqlAuthorization(unittest.TestCase):
    def setUp(self):
        self.client = auth.identity_from_rest_event(event())
        self.staff = auth.identity_from_rest_event(event(groups="Técnico,Administrador"))

    def test_politica_por_defecto_deniega_incluso_administrador(self):
        with self.assertRaises(auth.AuthorizationDenied):
            auth.service_access_predicate(self.staff)

    def test_cliente_no_necesita_asignacion_operativa(self):
        predicate = auth.service_access_predicate(self.client, allow_owner=True)
        self.assertNotIn("usuario_sede_rol", predicate.sql)
        self.assertIn("auth_site.activa", predicate.sql)
        self.assertEqual(predicate.params, (self.client.sub,))

    def test_cliente_no_autoriza_operacion_solo_personal(self):
        with self.assertRaises(auth.AuthorizationDenied):
            auth.service_access_predicate(self.client, staff_roles=auth.STAFF_ROLES)

    def test_personal_sin_cliente_no_obtiene_rama_propiedad(self):
        with self.assertRaises(auth.AuthorizationDenied):
            auth.service_access_predicate(self.staff, allow_owner=True)

    def test_rol_solicitado_no_se_amplia(self):
        predicate = auth.service_access_predicate(self.staff, staff_roles=(auth.ADMINISTRADOR,))
        self.assertEqual(predicate.params, (self.staff.sub, auth.ADMINISTRADOR))
        self.assertNotIn(auth.TECNICO, predicate.params)
        self.assertIn("auth_assignment.sede_id = svc.sede_id", predicate.sql)
        self.assertIn("auth_assignment.activo", predicate.sql)

    def test_no_usa_asignacion_de_rol_ausente_en_token(self):
        tech = auth.identity_from_rest_event(event(groups="Técnico"))
        with self.assertRaises(auth.AuthorizationDenied):
            auth.service_access_predicate(tech, staff_roles=(auth.ADMINISTRADOR,))

    def test_valores_maliciosos_siempre_parametrizados(self):
        identity = auth.identity_from_rest_event(event("x' OR TRUE --", "Cliente,Administrador"))
        predicate = auth.service_access_predicate(identity, allow_owner=True, staff_roles=auth.STAFF_ROLES)
        self.assertNotIn(identity.sub, predicate.sql)
        self.assertEqual(predicate.params.count(identity.sub), 2)

    def test_historicos_incompletos_excluidos(self):
        predicate = auth.service_access_predicate(self.staff, staff_roles=auth.STAFF_ROLES)
        self.assertIn("svc.cliente_sub IS NOT NULL", predicate.sql)
        self.assertIn("svc.sede_id IS NOT NULL", predicate.sql)
        self.assertIn("svc.cliente_sub ~ '[^[:space:]]'", predicate.sql)

    def test_politica_interna_invalida_no_se_confunde_con_fallo_bd(self):
        for roles in (("Tecnico",), ("Cliente",), "Administrador"):
            with self.subTest(roles=roles), self.assertRaises(ValueError):
                auth.service_access_predicate(self.staff, staff_roles=roles)
        with self.assertRaises(ValueError):
            auth.service_access_predicate(self.client, allow_owner="true")

    def test_consulta_servicio_parametrizada(self):
        db = cursor()
        auth.require_service_access(db, self.client, 7, allow_owner=True)
        self.assertEqual(db.execute.call_args.args[1], (7, self.client.sub))
        db.connection.commit.assert_not_called()
        db.connection.rollback.assert_not_called()

    def test_fila_ausente_o_sin_permiso_deniega(self):
        with self.assertRaises(auth.AuthorizationDenied):
            auth.require_service_access(cursor(None), self.client, 7, allow_owner=True)

    def test_id_invalido_no_consulta_bd(self):
        db = cursor()
        for service_id in (True, 0, -1, "1", None):
            with self.subTest(service_id=service_id), self.assertRaises(auth.AuthorizationDenied):
                auth.require_service_access(db, self.client, service_id, allow_owner=True)
        db.execute.assert_not_called()

    def test_error_de_conexion_es_infraestructura(self):
        db = cursor()
        db.execute.side_effect = OSError("conexión caída")
        with self.assertRaises(auth.AuthorizationInfrastructureError) as raised:
            auth.require_service_access(db, self.client, 1, allow_owner=True)
        self.assertIsInstance(raised.exception.__cause__, OSError)
        db.connection.commit.assert_not_called()

    def test_error_al_leer_es_infraestructura(self):
        db = cursor()
        db.fetchone.side_effect = RuntimeError("cursor cerrado")
        with self.assertRaises(auth.AuthorizationInfrastructureError):
            auth.require_site_role(db, self.staff, "A", auth.ADMINISTRADOR)

    def test_rol_en_sede_es_parametrizado(self):
        db = cursor()
        site = "A' OR TRUE --"
        auth.require_site_role(db, self.staff, site, auth.ADMINISTRADOR)
        self.assertEqual(db.execute.call_args.args[1], (self.staff.sub, site, auth.ADMINISTRADOR))
        self.assertNotIn(site, db.execute.call_args.args[0])

    def test_sede_sin_asignacion_o_inactiva_deniega(self):
        with self.assertRaises(auth.AuthorizationDenied):
            auth.require_site_role(cursor(None), self.staff, "A", auth.ADMINISTRADOR)

    def test_sede_invalida_no_consulta(self):
        db = cursor()
        for site in (None, "", " ", 3):
            with self.subTest(site=site), self.assertRaises(auth.AuthorizationDenied):
                auth.require_site_role(db, self.staff, site, auth.ADMINISTRADOR)
        db.execute.assert_not_called()



if __name__ == "__main__":
    unittest.main()
