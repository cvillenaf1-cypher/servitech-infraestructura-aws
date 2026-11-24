data "aws_partition" "current" {}

resource "aws_iam_role" "rds_proxy" {
  name = "${local.name_prefix}-rds-proxy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "rds_proxy_secret_access" {
  name = "${local.name_prefix}-rds-proxy-secret"
  role = aws_iam_role.rds_proxy.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [{
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = var.database_app_secret_arn
      }],
      var.database_app_secret_kms_key_arn == null ? [] : [{
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = var.database_app_secret_kms_key_arn
        Condition = {
          StringEquals = {
            "kms:ViaService"                  = "secretsmanager.${var.aws_region}.${data.aws_partition.current.dns_suffix}"
            "kms:EncryptionContext:SecretARN" = var.database_app_secret_arn
          }
        }
      }]
    )
  })
}
