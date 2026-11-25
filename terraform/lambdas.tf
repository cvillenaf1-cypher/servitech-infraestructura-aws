resource "aws_iam_role" "lambda_exec" {
  name = "${local.name_prefix}-lambda-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_vpc_access" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}


resource "aws_iam_role_policy" "lambda_proxy_connect" {
  name = "${local.name_prefix}-lambda-proxy-connect"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "rds-db:connect"
      Resource = replace(
        aws_db_proxy.postgres.arn,
        "/^arn:([^:]+):rds:([^:]+):([^:]+):db-proxy:(prx-[^:]+)$/",
        "arn:$1:rds-db:$2:$3:dbuser:$4/${local.database_app_username}"
      )
    }]
  })
}

resource "aws_lambda_function" "registrar_servicio" {
  function_name = "${local.name_prefix}-registrar-servicio"
  role          = aws_iam_role.lambda_exec.arn
  runtime       = "python3.12"
  architectures = ["x86_64"]
  handler       = "lambda_function.lambda_handler"
  memory_size   = 256
  timeout       = 15

  filename         = "${path.module}/../build/registrar_servicio.zip"
  source_code_hash = filebase64sha256("${path.module}/../build/registrar_servicio.zip")

  environment {
    variables = {
      DB_HOST = aws_db_proxy.postgres.endpoint
      DB_PORT = tostring(aws_db_instance.postgres.port)
      DB_NAME = aws_db_instance.postgres.db_name
      DB_USER = local.database_app_username
    }
  }

  vpc_config {
    subnet_ids = [
      aws_subnet.private_app_a.id,
      aws_subnet.private_app_b.id
    ]

    security_group_ids = [aws_security_group.rds_proxy_client.id]
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_vpc_access,
    aws_iam_role_policy.lambda_proxy_connect
  ]
}

resource "aws_lambda_function" "consultar_servicio" {
  function_name = "${local.name_prefix}-consultar-servicio"
  role          = aws_iam_role.lambda_exec.arn
  runtime       = "python3.12"
  architectures = ["x86_64"]
  handler       = "lambda_function.lambda_handler"
  memory_size   = 256
  timeout       = 15

  filename         = "${path.module}/../build/consultar_servicio.zip"
  source_code_hash = filebase64sha256("${path.module}/../build/consultar_servicio.zip")

  environment {
    variables = {
      DB_HOST = aws_db_proxy.postgres.endpoint
      DB_PORT = tostring(aws_db_instance.postgres.port)
      DB_NAME = aws_db_instance.postgres.db_name
      DB_USER = local.database_app_username
    }
  }

  vpc_config {
    subnet_ids = [
      aws_subnet.private_app_a.id,
      aws_subnet.private_app_b.id
    ]

    security_group_ids = [aws_security_group.rds_proxy_client.id]
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_vpc_access,
    aws_iam_role_policy.lambda_proxy_connect
  ]
}


resource "aws_lambda_function" "actualizar_diagnostico" {
  function_name = "${local.name_prefix}-actualizar-diagnostico"
  role          = aws_iam_role.lambda_exec.arn
  runtime       = "python3.12"
  architectures = ["x86_64"]
  handler       = "lambda_function.lambda_handler"
  memory_size   = 256
  timeout       = 15

  filename         = "${path.module}/../build/actualizar_diagnostico.zip"
  source_code_hash = filebase64sha256("${path.module}/../build/actualizar_diagnostico.zip")

  environment {
    variables = {
      DB_HOST = aws_db_proxy.postgres.endpoint
      DB_PORT = tostring(aws_db_instance.postgres.port)
      DB_NAME = aws_db_instance.postgres.db_name
      DB_USER = local.database_app_username
    }
  }

  vpc_config {
    subnet_ids = [
      aws_subnet.private_app_a.id,
      aws_subnet.private_app_b.id
    ]

    security_group_ids = [
      aws_security_group.rds_proxy_client.id
    ]
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_vpc_access,
    aws_iam_role_policy.lambda_proxy_connect
  ]
}



# Rol exclusivo de ActualizarEstado
resource "aws_iam_role" "lambda4_exec" {
  name = "${local.name_prefix}-lambda4-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda4_vpc_access" {
  role       = aws_iam_role.lambda4_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# Permite conectar Lambda 4 al RDS Proxy con IAM
resource "aws_iam_role_policy" "lambda4_proxy_connect" {
  name = "${local.name_prefix}-lambda4-proxy-connect"
  role = aws_iam_role.lambda4_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "rds-db:connect"
      Resource = replace(
        aws_db_proxy.postgres.arn,
        "/^arn:([^:]+):rds:([^:]+):([^:]+):db-proxy:(prx-[^:]+)$/",
        "arn:$1:rds-db:$2:$3:dbuser:$4/${local.database_app_username}"
      )
    }]
  })
}

# Lambda 4: ActualizarEstado
resource "aws_lambda_function" "actualizar_estado" {
  function_name = "${local.name_prefix}-actualizar-estado"
  role          = aws_iam_role.lambda4_exec.arn
  runtime       = "python3.12"
  architectures = ["x86_64"]
  handler       = "lambda_function.lambda_handler"
  memory_size   = 256
  timeout       = 15

  filename         = "${path.module}/../build/actualizar_estado.zip"
  source_code_hash = filebase64sha256("${path.module}/../build/actualizar_estado.zip")

  environment {
    variables = {
      DB_HOST              = aws_db_proxy.postgres.endpoint
      DB_PORT              = tostring(aws_db_instance.postgres.port)
      DB_NAME              = aws_db_instance.postgres.db_name
      DB_USER              = local.database_app_username
      EVENT_BUS_ARN        = var.lambda4_event_bus_arn == null ? "" : var.lambda4_event_bus_arn
      COGNITO_USER_POOL_ID = var.lambda4_cognito_user_pool_arn == null ? "" : split("/", var.lambda4_cognito_user_pool_arn)[1]
    }
  }

  vpc_config {
    subnet_ids = [
      aws_subnet.private_app_a.id,
      aws_subnet.private_app_b.id
    ]

    security_group_ids = [
      aws_security_group.rds_proxy_client.id,
      aws_security_group.lambda4_publisher.id
    ]
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda4_vpc_access,
    aws_iam_role_policy.lambda4_proxy_connect
  ]
}


resource "aws_iam_role" "lambda5_exec" {
  name = "${local.name_prefix}-lambda5-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda5_vpc_access" {
  role       = aws_iam_role.lambda5_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "lambda5_proxy_connect" {
  name = "${local.name_prefix}-lambda5-proxy-connect"
  role = aws_iam_role.lambda5_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "rds-db:connect"
      Resource = replace(
        aws_db_proxy.postgres.arn,
        "/^arn:([^:]+):rds:([^:]+):([^:]+):db-proxy:(prx-[^:]+)$/",
        "arn:$1:rds-db:$2:$3:dbuser:$4/${local.database_app_username}"
      )
    }]
  })
}

resource "aws_iam_role_policy" "lambda5_s3_access" {
  name = "${local.name_prefix}-lambda5-s3-evidencias"
  role = aws_iam_role.lambda5_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:PutObject",
        "s3:GetObject"
      ]
      Resource = "${aws_s3_bucket.evidencias.arn}/servicios/*"
    }]
  })
}

resource "aws_lambda_function" "gestionar_evidencias" {
  function_name = "${local.name_prefix}-gestionar-evidencias"
  role          = aws_iam_role.lambda5_exec.arn
  runtime       = "python3.12"
  architectures = ["x86_64"]
  handler       = "lambda_function.lambda_handler"
  memory_size   = 256
  timeout       = 15

  filename         = "${path.module}/../build/gestionar_evidencias.zip"
  source_code_hash = filebase64sha256("${path.module}/../build/gestionar_evidencias.zip")

  environment {
    variables = {
      DB_HOST           = aws_db_proxy.postgres.endpoint
      DB_PORT           = tostring(aws_db_instance.postgres.port)
      DB_NAME           = aws_db_instance.postgres.db_name
      DB_USER           = local.database_app_username
      EVIDENCIAS_BUCKET = aws_s3_bucket.evidencias.bucket
    }
  }

  vpc_config {
    subnet_ids = [
      aws_subnet.private_app_a.id,
      aws_subnet.private_app_b.id
    ]

    security_group_ids = [
      aws_security_group.rds_proxy_client.id
    ]
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda5_vpc_access,
    aws_iam_role_policy.lambda5_proxy_connect,
    aws_iam_role_policy.lambda5_s3_access
  ]
}


resource "aws_iam_role_policy" "lambda4_eventbridge_publish" {
  count = var.lambda4_event_bus_arn == null ? 0 : 1

  name = "${local.name_prefix}-lambda4-eventbridge-publish"
  role = aws_iam_role.lambda4_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "events:PutEvents"
      Resource = var.lambda4_event_bus_arn
    }]
  })
}


resource "aws_iam_role_policy" "lambda4_cognito_lookup" {
  count = var.lambda4_cognito_user_pool_arn == null ? 0 : 1

  name = "${local.name_prefix}-lambda4-cognito-read"
  role = aws_iam_role.lambda4_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "cognito-idp:ListUsers"
      Resource = var.lambda4_cognito_user_pool_arn
    }]
  })
}
