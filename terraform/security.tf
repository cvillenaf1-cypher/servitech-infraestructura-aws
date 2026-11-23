# ============================================================
# SECURITY GROUP - LAMBDAS DEL MVP
# ============================================================

resource "aws_security_group" "lambda" {
  name        = "${local.name_prefix}-lambda-sg"
  description = "Security Group para las funciones Lambda del MVP"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-lambda-sg"
  }
}

moved {
  from = aws_vpc_security_group_egress_rule.lambda_all
  to   = aws_vpc_security_group_egress_rule.lambda_to_rds
}

resource "aws_vpc_security_group_egress_rule" "lambda_to_rds" {
  description                  = "PostgreSQL desde las Lambdas del MVP"
  security_group_id            = aws_security_group.lambda.id
  referenced_security_group_id = aws_security_group.rds.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432

  # Habilita la lectura del secreto antes de restringir la salida anterior.
  depends_on = [aws_vpc_security_group_egress_rule.lambda_to_secrets]

  # Si el cambio de tipo de destino exige reemplazo, conservar la regla vieja
  # hasta crear la nueva. Ver la transición desde el MVP en el contrato de red.
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_egress_rule" "lambda_to_secrets" {
  description                  = "HTTPS al endpoint privado de Secrets Manager"
  security_group_id            = aws_security_group.lambda.id
  referenced_security_group_id = aws_security_group.secrets_endpoint.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

# ============================================================
# SECURITY GROUP - POSTGRESQL
# ============================================================

resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds-sg"
  description = "Security Group para PostgreSQL del MVP"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-rds-sg"
  }
}

# Acceso directo del MVP; se conserva durante la transición a RDS Proxy.
resource "aws_vpc_security_group_ingress_rule" "rds_from_lambda" {
  description = "Permite PostgreSQL desde Lambda hacia RDS"

  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = aws_security_group.lambda.id

  from_port   = 5432
  to_port     = 5432
  ip_protocol = "tcp"
}
# ============================================================
# SECURITY GROUP - VPC ENDPOINT SECRETS MANAGER
# ============================================================

resource "aws_security_group" "secrets_endpoint" {
  name        = "${local.name_prefix}-secrets-endpoint-sg"
  description = "Security Group para el VPC Endpoint de Secrets Manager"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-secrets-endpoint-sg"
  }
}

# El endpoint acepta HTTPS solamente desde las Lambdas.
resource "aws_vpc_security_group_ingress_rule" "secrets_from_lambda" {
  description       = "Permite HTTPS desde Lambda hacia Secrets Manager"
  security_group_id = aws_security_group.secrets_endpoint.id

  referenced_security_group_id = aws_security_group.lambda.id

  from_port   = 443
  to_port     = 443
  ip_protocol = "tcp"
}

# Lambda 4: el responsable de ActualizarEstado asociará este SG al publicador.
# IAM queda pendiente de su rol propio y del ARN del bus que defina el equipo de eventos.
resource "aws_security_group" "lambda4_publisher" {
  name        = "${local.name_prefix}-lambda4-publisher-sg"
  description = "Publicador de cambios de estado hacia EventBridge"
  vpc_id      = aws_vpc.main.id
  egress      = []

  lifecycle {
    ignore_changes = [egress] # La salida la administra publisher_to_eventbridge.
  }
}

resource "aws_security_group" "eventbridge_endpoint" {
  name        = "${local.name_prefix}-eventbridge-endpoint-sg"
  description = "Endpoint privado de EventBridge"
  vpc_id      = aws_vpc.main.id
  egress      = []
}

resource "aws_vpc_security_group_egress_rule" "publisher_to_eventbridge" {
  description                  = "HTTPS desde Lambda 4 al endpoint de EventBridge"
  security_group_id            = aws_security_group.lambda4_publisher.id
  referenced_security_group_id = aws_security_group.eventbridge_endpoint.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_security_group_ingress_rule" "eventbridge_from_publisher" {
  description                  = "HTTPS solo desde el SG publicador de Lambda 4"
  security_group_id            = aws_security_group.eventbridge_endpoint.id
  referenced_security_group_id = aws_security_group.lambda4_publisher.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
