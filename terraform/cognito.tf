# Identidad de Página 3. Sin dominio ni OAuth: login mediante SDK/SRP.
# La conectividad PrivateLink y los consumidores se integran en otra fase.
resource "aws_cognito_user_pool" "servitech" {
  name                = "${local.name_prefix}-usuarios"
  deletion_protection = "ACTIVE"
  user_pool_tier      = "LITE"

  # Username administrativo para login; sub es la identidad de aplicación.
  username_configuration {
    case_sensitive = false
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  # No marcar email/teléfono como verificados ni habilitar SMS sin sus requisitos.
  auto_verified_attributes = []

  account_recovery_setting {
    recovery_mechanism {
      name     = "admin_only"
      priority = 1
    }
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 3
  }

  # TOTP no depende de SMS. Su enrolamiento requiere soporte en el futuro cliente.
  mfa_configuration = "OPTIONAL"

  software_token_mfa_configuration {
    enabled = true
  }

  # Se conservan los atributos estándar opcionales, sin redefinir su esquema.
  # El esquema propuesto de custom:sede_id se documenta en README.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_cognito_user_pool_client" "portal" {
  name         = "${local.name_prefix}-portal"
  user_pool_id = aws_cognito_user_pool.servitech.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = false
  supported_identity_providers         = ["COGNITO"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  auth_session_validity                = 3

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  id_token_validity      = 15
  access_token_validity  = 15
  refresh_token_validity = 1

  token_validity_units {
    id_token      = "minutes"
    access_token  = "minutes"
    refresh_token = "days"
  }

  # La rotación requiere cambiar el flujo de refresh del SDK.
  refresh_token_rotation {
    feature = "DISABLED"
  }

  read_attributes = [
    "sub",
    "name",
    "email",
    "email_verified",
    "phone_number",
    "phone_number_verified",
  ]

  # Lista explícita: no dar escritura predeterminada a atributos futuros.
  write_attributes = ["name"]
}

resource "aws_cognito_user_group" "roles" {
  for_each = {
    "Cliente"       = "Cliente de ServiTech; acceso sujeto a propiedad del servicio."
    "Técnico"       = "Personal técnico; acceso sujeto a rol y sede autorizada."
    "Administrador" = "Administración de aplicación; sin acceso global implícito."
  }

  user_pool_id = aws_cognito_user_pool.servitech.id
  name         = each.key
  description  = each.value
}
