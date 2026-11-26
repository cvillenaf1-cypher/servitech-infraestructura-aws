data "aws_route53_zone" "frontend" {
  count   = var.frontend_domain == null ? 0 : 1
  zone_id = var.frontend_domain.zone_id
}

resource "aws_acm_certificate" "frontend" {
  count             = var.frontend_domain == null ? 0 : 1
  provider          = aws.us_east_1
  domain_name       = var.frontend_domain.name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
    precondition {
      condition = !data.aws_route53_zone.frontend[0].private_zone && (
        var.frontend_domain.name == trimsuffix(data.aws_route53_zone.frontend[0].name, ".") ||
        endswith(var.frontend_domain.name, ".${trimsuffix(data.aws_route53_zone.frontend[0].name, ".")}")
      )
      error_message = "El dominio debe pertenecer a la zona pública Route 53 indicada."
    }
  }
}

resource "aws_route53_record" "frontend_certificate" {
  count   = var.frontend_domain == null ? 0 : 1
  zone_id = data.aws_route53_zone.frontend[0].zone_id
  name    = tolist(aws_acm_certificate.frontend[0].domain_validation_options)[0].resource_record_name
  type    = tolist(aws_acm_certificate.frontend[0].domain_validation_options)[0].resource_record_type
  records = [tolist(aws_acm_certificate.frontend[0].domain_validation_options)[0].resource_record_value]
  ttl     = 60
}

resource "aws_acm_certificate_validation" "frontend" {
  count                   = var.frontend_domain == null ? 0 : 1
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.frontend[0].arn
  validation_record_fqdns = [aws_route53_record.frontend_certificate[0].fqdn]
}

resource "aws_route53_record" "frontend" {
  for_each = var.frontend_domain == null ? toset([]) : toset(["A", "AAAA"])
  zone_id  = data.aws_route53_zone.frontend[0].zone_id
  name     = var.frontend_domain.name
  type     = each.value

  alias {
    name                   = aws_cloudfront_distribution.frontend.domain_name
    zone_id                = aws_cloudfront_distribution.frontend.hosted_zone_id
    evaluate_target_health = false
  }
}
