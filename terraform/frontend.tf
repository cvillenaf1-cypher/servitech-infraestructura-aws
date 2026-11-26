resource "aws_s3_bucket" "frontend" {
  bucket_prefix = "${local.name_prefix}-frontend-"

  tags = {
    Name = "${local.name_prefix}-frontend"
  }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Corrección de versionado del PR #1 de Checkov.
resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name_prefix}-frontend"
  description                       = "Acceso firmado al frontend privado de ServiTech"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_cloudfront_cache_policy" "api" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "api" {
  name = "Managed-AllViewerExceptHostHeader"
}

data "aws_cloudfront_response_headers_policy" "security" {
  name = "Managed-SecurityHeadersPolicy"
}

resource "aws_cloudfront_function" "api_path" {
  name    = "${local.name_prefix}-api-path"
  runtime = "cloudfront-js-2.0"
  comment = "Retira /api; el origen añade el stage dev existente"
  publish = true
  code    = file("${path.module}/../frontend/api-path.js")
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  comment             = "Frontend del MVP de ServiTech"
  web_acl_id          = aws_wafv2_web_acl.frontend.arn
  aliases             = var.frontend_domain == null ? [] : [var.frontend_domain.name]

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "frontend-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  origin {
    domain_name = split("/", aws_api_gateway_stage.dev.invoke_url)[2]
    origin_id   = "servitech-api"
    origin_path = "/${aws_api_gateway_stage.dev.stage_name}"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = "servitech-api"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.api.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.api.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security.id
    compress                   = true

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.api_path.arn
    }
  }

  # No guardar denegaciones o fallos de la API ni convertirlos en index.html.
  dynamic "custom_error_response" {
    for_each = toset([403, 404, 500, 502, 503, 504])
    content {
      error_code            = custom_error_response.value
      error_caching_min_ttl = 0
    }
  }

  default_cache_behavior {
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security.id
    target_origin_id           = "frontend-s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true

    # Archivos sin version en el nombre: revalidar en navegador y hasta 60 s en CDN.
    min_ttl     = 0
    default_ttl = 60
    max_ttl     = 300

    forwarded_values {
      query_string = false

      cookies {
        forward = "none"
      }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = var.frontend_domain == null
    acm_certificate_arn            = var.frontend_domain == null ? null : aws_acm_certificate_validation.frontend[0].certificate_arn
    ssl_support_method             = var.frontend_domain == null ? null : "sni-only"
    minimum_protocol_version       = var.frontend_domain == null ? "TLSv1" : "TLSv1.2_2021"
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowCloudFrontReadOnly"
      Effect = "Allow"
      Principal = {
        Service = "cloudfront.amazonaws.com"
      }
      Action   = "s3:GetObject"
      Resource = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn
        }
      }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

resource "aws_s3_object" "index" {
  bucket        = aws_s3_bucket.frontend.id
  key           = "index.html"
  source        = "${path.module}/../frontend/index.html"
  source_hash   = filemd5("${path.module}/../frontend/index.html")
  content_type  = "text/html; charset=utf-8"
  cache_control = "public, max-age=0, s-maxage=60, must-revalidate"

  depends_on = [aws_s3_bucket_versioning.frontend, aws_s3_bucket_server_side_encryption_configuration.frontend]
}

resource "aws_s3_object" "styles" {
  bucket        = aws_s3_bucket.frontend.id
  key           = "styles.css"
  source        = "${path.module}/../frontend/styles.css"
  source_hash   = filemd5("${path.module}/../frontend/styles.css")
  content_type  = "text/css; charset=utf-8"
  cache_control = "public, max-age=0, s-maxage=60, must-revalidate"

  depends_on = [aws_s3_bucket_versioning.frontend, aws_s3_bucket_server_side_encryption_configuration.frontend]
}

locals {
  frontend_app_js = file("${path.module}/../frontend/app.js")
  frontend_url    = "https://${var.frontend_domain == null ? aws_cloudfront_distribution.frontend.domain_name : var.frontend_domain.name}"
}

resource "aws_s3_object" "app" {
  bucket        = aws_s3_bucket.frontend.id
  key           = "app.js"
  content       = local.frontend_app_js
  source_hash   = md5(local.frontend_app_js)
  content_type  = "text/javascript; charset=utf-8"
  cache_control = "public, max-age=0, s-maxage=60, must-revalidate"

  depends_on = [aws_s3_bucket_versioning.frontend, aws_s3_bucket_server_side_encryption_configuration.frontend]
}

resource "aws_s3_object" "frontend_config" {
  bucket = aws_s3_bucket.frontend.id
  key    = "config.js"
  content = "window.SERVITECH_CONFIG = ${jsonencode({
    userPoolId = aws_cognito_user_pool.servitech.id
    clientId   = aws_cognito_user_pool_client.portal.id
  })};"
  content_type  = "text/javascript; charset=utf-8"
  cache_control = "no-store"
  depends_on    = [aws_s3_bucket_versioning.frontend, aws_s3_bucket_server_side_encryption_configuration.frontend]
}

resource "aws_s3_object" "frontend_auth" {
  for_each      = toset(["auth.js", "vendor/amazon-cognito-identity.min.js", "vendor/LICENSE.cognito.txt", "vendor/NOTICE.cognito.txt"])
  bucket        = aws_s3_bucket.frontend.id
  key           = each.value
  source        = "${path.module}/../frontend/${each.value}"
  source_hash   = filemd5("${path.module}/../frontend/${each.value}")
  content_type  = endswith(each.value, ".js") ? "text/javascript; charset=utf-8" : "text/plain; charset=utf-8"
  cache_control = "public, max-age=0, s-maxage=60, must-revalidate"
  depends_on    = [aws_s3_bucket_versioning.frontend, aws_s3_bucket_server_side_encryption_configuration.frontend]
}
