resource "aws_api_gateway_rest_api" "servitech" {
  name        = "${local.name_prefix}-api"
  description = "API REST del MVP de ServiTech"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_authorizer" "cognito" {
  name                           = "${local.name_prefix}-cognito"
  rest_api_id                    = aws_api_gateway_rest_api.servitech.id
  type                           = "COGNITO_USER_POOLS"
  provider_arns                  = [aws_cognito_user_pool.servitech.arn]
  identity_source                = "method.request.header.Authorization"
  identity_validation_expression = "^${aws_cognito_user_pool_client.portal.id}$"
}

resource "aws_api_gateway_resource" "servicios" {
  rest_api_id = aws_api_gateway_rest_api.servitech.id
  parent_id   = aws_api_gateway_rest_api.servitech.root_resource_id
  path_part   = "servicios"
}

resource "aws_api_gateway_resource" "servicio_id" {
  rest_api_id = aws_api_gateway_rest_api.servitech.id
  parent_id   = aws_api_gateway_resource.servicios.id
  path_part   = "{id}"
}

resource "aws_api_gateway_method" "registrar_servicio" {
  rest_api_id   = aws_api_gateway_rest_api.servitech.id
  resource_id   = aws_api_gateway_resource.servicios.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "registrar_servicio" {
  rest_api_id             = aws_api_gateway_rest_api.servitech.id
  resource_id             = aws_api_gateway_resource.servicios.id
  http_method             = aws_api_gateway_method.registrar_servicio.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.registrar_servicio.invoke_arn
}

resource "aws_api_gateway_method" "consultar_servicio" {
  rest_api_id   = aws_api_gateway_rest_api.servitech.id
  resource_id   = aws_api_gateway_resource.servicio_id.id
  http_method   = "GET"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "consultar_servicio" {
  rest_api_id             = aws_api_gateway_rest_api.servitech.id
  resource_id             = aws_api_gateway_resource.servicio_id.id
  http_method             = aws_api_gateway_method.consultar_servicio.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.consultar_servicio.invoke_arn
}

resource "aws_lambda_permission" "api_registrar" {
  statement_id  = "AllowApiGatewayRegistrarServicio"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.registrar_servicio.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.servitech.execution_arn}/dev/POST/servicios"
}

resource "aws_lambda_permission" "api_consultar" {
  statement_id  = "AllowApiGatewayConsultarServicio"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.consultar_servicio.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.servitech.execution_arn}/dev/GET/servicios/*"
}

# Las rutas existentes se conservan; solo se añaden los tres subrecursos.
locals {
  api_service_actions = {
    diagnostico = {
      method     = "PATCH"
      invoke_arn = aws_lambda_function.actualizar_diagnostico.invoke_arn
      name       = aws_lambda_function.actualizar_diagnostico.function_name
    }
    estado = {
      method     = "PATCH"
      invoke_arn = aws_lambda_function.actualizar_estado.invoke_arn
      name       = aws_lambda_function.actualizar_estado.function_name
    }
    evidencias = {
      method     = "POST"
      invoke_arn = aws_lambda_function.gestionar_evidencias.invoke_arn
      name       = aws_lambda_function.gestionar_evidencias.function_name
    }
  }

  api_cors_resources = merge({
    servicios   = aws_api_gateway_resource.servicios.id
    servicio_id = aws_api_gateway_resource.servicio_id.id
  }, { for key, value in aws_api_gateway_resource.service_action : key => value.id })
}

resource "aws_api_gateway_resource" "service_action" {
  for_each    = local.api_service_actions
  rest_api_id = aws_api_gateway_rest_api.servitech.id
  parent_id   = aws_api_gateway_resource.servicio_id.id
  path_part   = each.key
}

resource "aws_api_gateway_method" "service_action" {
  for_each      = local.api_service_actions
  rest_api_id   = aws_api_gateway_rest_api.servitech.id
  resource_id   = aws_api_gateway_resource.service_action[each.key].id
  http_method   = each.value.method
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "service_action" {
  for_each                = local.api_service_actions
  rest_api_id             = aws_api_gateway_rest_api.servitech.id
  resource_id             = aws_api_gateway_resource.service_action[each.key].id
  http_method             = aws_api_gateway_method.service_action[each.key].http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = each.value.invoke_arn
}

resource "aws_lambda_permission" "api_service_action" {
  for_each      = local.api_service_actions
  statement_id  = "AllowApiGateway-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = each.value.name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.servitech.execution_arn}/dev/${each.value.method}/servicios/*/${each.key}"
}

resource "aws_api_gateway_gateway_response" "cors_errors" {
  for_each      = toset(["DEFAULT_4XX", "DEFAULT_5XX"])
  rest_api_id   = aws_api_gateway_rest_api.servitech.id
  response_type = each.value
  response_parameters = {
    "gatewayresponse.header.Access-Control-Allow-Origin"  = "'*'"
    "gatewayresponse.header.Access-Control-Allow-Headers" = "'Content-Type,Authorization'"
    "gatewayresponse.header.Access-Control-Allow-Methods" = "'GET,POST,PATCH,OPTIONS'"
  }
}

resource "aws_api_gateway_method" "options" {
  for_each = local.api_cors_resources

  rest_api_id   = aws_api_gateway_rest_api.servitech.id
  resource_id   = each.value
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "options" {
  for_each = local.api_cors_resources

  rest_api_id = aws_api_gateway_rest_api.servitech.id
  resource_id = each.value
  http_method = aws_api_gateway_method.options[each.key].http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = jsonencode({ statusCode = 200 })
  }
}

resource "aws_api_gateway_method_response" "options" {
  for_each = local.api_cors_resources

  rest_api_id = aws_api_gateway_rest_api.servitech.id
  resource_id = each.value
  http_method = aws_api_gateway_method.options[each.key].http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = true
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
  }
}

resource "aws_api_gateway_integration_response" "options" {
  for_each = local.api_cors_resources

  rest_api_id = aws_api_gateway_rest_api.servitech.id
  resource_id = each.value
  http_method = aws_api_gateway_method.options[each.key].http_method
  status_code = aws_api_gateway_method_response.options[each.key].status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,Authorization'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,POST,PATCH,OPTIONS'"
  }

  response_templates = {
    "application/json" = "{}"
  }

  depends_on = [aws_api_gateway_integration.options]
}

resource "aws_api_gateway_deployment" "servitech" {
  rest_api_id = aws_api_gateway_rest_api.servitech.id

  # Incluye la configuracion, no solo los IDs, para detectar cambios in situ.
  triggers = {
    redeployment = sha1(jsonencode({
      autorizador            = aws_api_gateway_authorizer.cognito
      acciones_recursos      = aws_api_gateway_resource.service_action
      acciones_metodos       = aws_api_gateway_method.service_action
      acciones_integraciones = aws_api_gateway_integration.service_action
      errores_cors           = aws_api_gateway_gateway_response.cors_errors
      recursos = [
        aws_api_gateway_resource.servicios,
        aws_api_gateway_resource.servicio_id
      ]
      metodos = [
        aws_api_gateway_method.registrar_servicio,
        aws_api_gateway_method.consultar_servicio
      ]
      integraciones = [
        aws_api_gateway_integration.registrar_servicio,
        aws_api_gateway_integration.consultar_servicio
      ]
      options_metodos                = aws_api_gateway_method.options
      options_integraciones          = aws_api_gateway_integration.options
      options_respuestas             = aws_api_gateway_method_response.options
      options_respuestas_integracion = aws_api_gateway_integration_response.options
    }))
  }

  depends_on = [
    aws_api_gateway_integration.registrar_servicio,
    aws_api_gateway_integration.consultar_servicio,
    aws_api_gateway_integration.options,
    aws_api_gateway_method_response.options,
    aws_api_gateway_integration_response.options,
    aws_lambda_permission.api_registrar,
    aws_lambda_permission.api_consultar,
    aws_api_gateway_integration.service_action,
    aws_lambda_permission.api_service_action,
    aws_api_gateway_gateway_response.cors_errors
  ]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "dev" {
  rest_api_id          = aws_api_gateway_rest_api.servitech.id
  deployment_id        = aws_api_gateway_deployment.servitech.id
  stage_name           = "dev"
  xray_tracing_enabled = true
}
