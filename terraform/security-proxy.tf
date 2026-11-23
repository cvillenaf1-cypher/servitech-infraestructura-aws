# Contrato de red de Página 3. Solo se preparan los SG; Jesús y Gordillo
# asociarán los recursos en sus entregas. Lambda 4 usará además su SG publicador.
resource "aws_security_group" "rds_proxy_client" {
  name        = "${local.name_prefix}-rds-proxy-client-sg"
  description = "Clientes Lambda del futuro RDS Proxy"
  vpc_id      = aws_vpc.main.id
  egress      = []

  lifecycle {
    ignore_changes = [egress] # La salida la administra client_to_proxy.
  }
}

resource "aws_security_group" "rds_proxy" {
  name        = "${local.name_prefix}-rds-proxy-sg"
  description = "RDS Proxy entre las Lambdas y PostgreSQL"
  vpc_id      = aws_vpc.main.id
  egress      = []

  lifecycle {
    ignore_changes = [egress] # La salida la administra proxy_to_rds.
  }
}

resource "aws_vpc_security_group_egress_rule" "client_to_proxy" {
  description                  = "PostgreSQL de clientes Lambda al proxy"
  security_group_id            = aws_security_group.rds_proxy_client.id
  referenced_security_group_id = aws_security_group.rds_proxy.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "proxy_from_client" {
  description                  = "PostgreSQL desde clientes Lambda"
  security_group_id            = aws_security_group.rds_proxy.id
  referenced_security_group_id = aws_security_group.rds_proxy_client.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_egress_rule" "proxy_to_rds" {
  description                  = "PostgreSQL del proxy a la instancia"
  security_group_id            = aws_security_group.rds_proxy.id
  referenced_security_group_id = aws_security_group.rds.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_proxy" {
  description                  = "PostgreSQL desde el SG del proxy"
  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = aws_security_group.rds_proxy.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
