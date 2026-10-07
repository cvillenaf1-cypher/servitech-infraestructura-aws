# ServiTech - Infraestructura AWS

Proyecto de Infraestructura como Código para la plataforma ServiTech.

## Integrantes

- Cristhian Villena Flores
- Diego Gordillo Saona
- Jesus Quinde Rojas
- Jhonatan Rios Iparraguirre
- Joel Leon Poveda

## Objetivo

Diseñar e implementar una arquitectura en AWS para la plataforma ServiTech, utilizando Terraform como herramienta de Infraestructura como Código.

La solución contempla autenticación de usuarios, exposición de APIs, procesamiento mediante funciones Lambda, almacenamiento de evidencias, base de datos relacional, eventos, notificaciones, monitoreo y respaldos.

## Servicios AWS propuestos

- Amazon Route 53
- Amazon CloudFront
- AWS WAF
- Amazon S3
- Amazon Cognito
- Amazon API Gateway
- AWS Lambda
- Amazon RDS Proxy
- Amazon RDS for PostgreSQL
- Amazon EventBridge
- AWS AppSync
- Amazon SNS
- Amazon CloudWatch
- AWS Backup
- Amazon VPC

## Arquitectura propuesta

La arquitectura contempla tres tipos de usuarios:

- Cliente
- Técnico
- Administrador

El flujo principal considera acceso mediante Route 53 y CloudFront, autenticación con Amazon Cognito, acceso a servicios mediante API Gateway y procesamiento con funciones AWS Lambda.

La información se almacena en Amazon RDS for PostgreSQL y las evidencias se almacenan en Amazon S3.

También se utilizan EventBridge, AppSync y SNS para eventos, actualizaciones en tiempo real y notificaciones.

## Funciones Lambda

- Registrar Servicio
- Consultar Servicio
- Actualizar Diagnóstico
- Actualizar Estado
- Gestionar Evidencias
- Publicar Tiempo Real
- Enviar Notificación

## Distribución del trabajo

| Integrante | Rama | Responsabilidad |
|---|---|---|
| Cristhian Villena Flores | `feat/frontend-edge` | Route 53, CloudFront, AWS WAF y S3 del frontend |
| Diego Gordillo Saona | `feat/network-database` | VPC, subredes, Security Groups, RDS Proxy y RDS PostgreSQL |
| Jesus Quinde Rojas | `feat/iam-auth` | IAM, Amazon Cognito y grupos de usuarios |
| Jhonatan Rios Iparraguirre | `feat/backend-api` | API Gateway, Lambdas principales y S3 de evidencias |
| Joel Leon Poveda | `feat/events-monitoring` | EventBridge, AppSync, SNS, CloudWatch, AWS Backup y Lambdas de eventos |

## Infraestructura como Código

La infraestructura será definida y administrada mediante Terraform.