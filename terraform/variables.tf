variable "aws_region" {
  description = "Region principal donde se desplegara ServiTech"
  type        = string
  default     = "us-east-2"
}

variable "aws_profile" {
  description = "Perfil AWS opcional; null permite usar AWS_PROFILE o credenciales temporales de OIDC"
  type        = string
  default     = null
}

variable "project_name" {
  description = "Nombre del proyecto"
  type        = string
  default     = "servitech"
}

variable "database_app_secret_arn" {
  description = "ARN completo del secreto existente de servitech_app en Secrets Manager."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^arn:[^:]+:secretsmanager:[^:]+:[0-9]{12}:secret:[^:]+-[A-Za-z0-9]{6}$", var.database_app_secret_arn))
    error_message = "Indica el ARN completo del secreto, incluido el sufijo de Secrets Manager."
  }
}

variable "database_app_secret_kms_key_arn" {
  description = "ARN de la clave KMS administrada por el cliente que cifra el secreto, si corresponde."
  type        = string
  default     = null

  validation {
    condition     = var.database_app_secret_kms_key_arn == null || can(regex("^arn:[^:]+:kms:[^:]+:[0-9]{12}:key/[^:/]+$", var.database_app_secret_kms_key_arn))
    error_message = "Indica el ARN de una clave KMS o usa null para aws/secretsmanager."
  }
}

variable "lambda4_event_bus_arn" {
  description = "ARN del bus EventBridge que integrara Jhonatan."
  type        = string
  default     = null
}

variable "frontend_domain" {
  description = "Dominio del portal y ID de una zona pública Route 53 existente. null conserva el dominio HTTPS de CloudFront."
  type = object({
    name    = string
    zone_id = string
  })
  default = null

  validation {
    condition = var.frontend_domain == null ? true : (
      can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.frontend_domain.name)) &&
      can(regex("^Z[A-Z0-9]+$", var.frontend_domain.zone_id))
    )
    error_message = "Indica un FQDN en minúsculas sin protocolo ni punto final y el ID de la zona Route 53, o null."
  }
}
