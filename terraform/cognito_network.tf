# Consulta privada de identidad y teléfono del propietario desde Lambda 4.
resource "aws_security_group" "cognito_endpoint" {
  name        = "${local.name_prefix}-cognito-endpoint-sg"
  description = "Endpoint privado de Cognito para ActualizarEstado"
  vpc_id      = aws_vpc.main.id
  egress      = []
}

resource "aws_vpc_security_group_ingress_rule" "cognito_from_lambda4" {
  description                  = "HTTPS solo desde el SG exclusivo de Lambda 4"
  security_group_id            = aws_security_group.cognito_endpoint.id
  referenced_security_group_id = aws_security_group.lambda4_publisher.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_security_group_egress_rule" "lambda4_to_cognito" {
  description                  = "HTTPS desde Lambda 4 al endpoint de Cognito"
  security_group_id            = aws_security_group.lambda4_publisher.id
  referenced_security_group_id = aws_security_group.cognito_endpoint.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_endpoint" "cognito_idp" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.cognito-idp"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [aws_subnet.private_app_a.id, aws_subnet.private_app_b.id]
  security_group_ids  = [aws_security_group.cognito_endpoint.id]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = aws_iam_role.lambda4_exec.arn }
      Action    = ["cognito-idp:ListUsers", "cognito-idp:AdminGetUser"]
      Resource  = aws_cognito_user_pool.servitech.arn
    }]
  })

  tags = {
    Name = "${local.name_prefix}-cognito-idp-endpoint"
  }
}
