resource "aws_s3_bucket" "evidencias" {
  bucket_prefix = "${local.name_prefix}-evidencias-"

  tags = {
    Name = "${local.name_prefix}-evidencias"
  }
}

resource "aws_s3_bucket_public_access_block" "evidencias" {
  bucket = aws_s3_bucket.evidencias.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "evidencias" {
  bucket = aws_s3_bucket.evidencias.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "evidencias" {
  bucket = aws_s3_bucket.evidencias.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidencias" {
  bucket = aws_s3_bucket.evidencias.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "evidencias_https" {
  bucket = aws_s3_bucket.evidencias.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.evidencias.arn,
        "${aws_s3_bucket.evidencias.arn}/*"
      ]
      Condition = {
        Bool = {
          "aws:SecureTransport" = "false"
        }
      }
    }]
  })

  depends_on = [
    aws_s3_bucket_public_access_block.evidencias
  ]
}

resource "aws_s3_bucket_cors_configuration" "evidencias" {
  bucket = aws_s3_bucket.evidencias.id

  cors_rule {
    allowed_headers = ["Content-Type"]
    allowed_methods = ["GET", "PUT"]
    allowed_origins = [
      "https://${aws_cloudfront_distribution.frontend.domain_name}"
    ]
    expose_headers  = ["ETag"]
    max_age_seconds = 300
  }
}