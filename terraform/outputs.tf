output "frontend_url" {
  description = "URL HTTPS del frontend servido por CloudFront."
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "api_url" {
  description = "URL base de API Gateway, incluido el stage dev."
  value       = aws_api_gateway_stage.dev.invoke_url
}

output "database_endpoint" {
  description = "Endpoint tecnico de PostgreSQL (host:puerto), accesible desde la VPC."
  value       = aws_db_instance.postgres.endpoint
}

output "frontend_bucket" {
  description = "Nombre del bucket S3 privado del frontend."
  value       = aws_s3_bucket.frontend.bucket
}

output "aws_region" {
  description = "Region AWS configurada para el despliegue."
  value       = var.aws_region
}

output "environment" {
  description = "Workspace actual de Terraform."
  value       = terraform.workspace
}

output "database_proxy_endpoint" {
  description = "Hostname privado del proxy PostgreSQL."
  value       = aws_db_proxy.postgres.endpoint
}

output "database_proxy_arn" {
  description = "ARN del proxy PostgreSQL."
  value       = aws_db_proxy.postgres.arn
}

output "database_port" {
  description = "Puerto PostgreSQL."
  value       = aws_db_instance.postgres.port
}

output "database_name" {
  description = "Nombre de la base PostgreSQL de aplicación."
  value       = aws_db_instance.postgres.db_name
}

output "database_app_username" {
  description = "Usuario PostgreSQL de aplicación."
  value       = local.database_app_username
}

output "database_proxy_client_security_group_id" {
  description = "ID del Security Group de las Lambda que consumen RDS Proxy."
  value       = aws_security_group.rds_proxy_client.id
}

output "database_proxy_connect_arn" {
  description = "Recurso exacto para rds-db:connect de los roles consumidores del proxy."
  value       = replace(aws_db_proxy.postgres.arn, "/^arn:([^:]+):rds:([^:]+):([^:]+):db-proxy:(prx-[^:]+)$/", "arn:$1:rds-db:$2:$3:dbuser:$4/${local.database_app_username}")
}

output "database_instance_arn" {
  description = "ARN de la instancia RDS PostgreSQL."
  value       = aws_db_instance.postgres.arn
}

output "cognito_user_pool_id" {
  description = "ID del User Pool para el SDK y ActualizarEstado."
  value       = aws_cognito_user_pool.servitech.id
}

output "cognito_user_pool_arn" {
  description = "ARN del User Pool para el futuro autorizador REST y permisos de lectura Cognito."
  value       = aws_cognito_user_pool.servitech.arn
}

output "cognito_app_client_id" {
  description = "ID público del App Client del portal; no tiene secreto."
  value       = aws_cognito_user_pool_client.portal.id
}
