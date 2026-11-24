locals {
  database_app_username = "servitech_app"
}

resource "aws_db_proxy" "postgres" {
  name                   = "${local.name_prefix}-postgres-proxy"
  engine_family          = "POSTGRESQL"
  default_auth_scheme    = "NONE"
  require_tls            = true
  idle_client_timeout    = 300
  role_arn               = aws_iam_role.rds_proxy.arn
  vpc_security_group_ids = [aws_security_group.rds_proxy.id]
  vpc_subnet_ids         = aws_db_subnet_group.servitech.subnet_ids

  auth {
    auth_scheme = "SECRETS"
    iam_auth    = "REQUIRED"
    secret_arn  = var.database_app_secret_arn
  }

  depends_on = [aws_iam_role_policy.rds_proxy_secret_access]

  lifecycle {
    precondition {
      condition     = var.database_app_secret_arn != aws_db_instance.postgres.master_user_secret[0].secret_arn
      error_message = "RDS Proxy requiere un secreto dedicado a servitech_app."
    }
  }
}

resource "aws_db_proxy_default_target_group" "postgres" {
  db_proxy_name = aws_db_proxy.postgres.name

  connection_pool_config {
    max_connections_percent      = 80
    max_idle_connections_percent = 40
    connection_borrow_timeout    = 5
  }

  lifecycle {
    replace_triggered_by = [aws_db_proxy.postgres.id]
  }
}

resource "aws_db_proxy_target" "postgres" {
  db_proxy_name          = aws_db_proxy.postgres.name
  target_group_name      = aws_db_proxy_default_target_group.postgres.name
  db_instance_identifier = aws_db_instance.postgres.identifier

  depends_on = [
    aws_vpc_security_group_egress_rule.proxy_to_rds,
    aws_vpc_security_group_ingress_rule.rds_from_proxy
  ]

  lifecycle {
    replace_triggered_by = [aws_db_proxy.postgres.id]
  }
}
