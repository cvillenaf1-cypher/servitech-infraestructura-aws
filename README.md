# ServiTech — MVP en AWS

ServiTech permite registrar y consultar servicios técnicos. Terraform administra
la infraestructura del MVP. La demostración requiere un INSERT real en PostgreSQL
y un SELECT del mismo registro por el ID devuelto; una respuesta simulada no basta.

## Identidad, autorización y API

La referencia es exclusivamente la Página 3 del diagrama oficial, junto con
las contribuciones existentes y el [PR #1 de Checkov](https://github.com/cvillenaf1-cypher/servitech-infraestructura-aws/pull/1).
No se incorpora el diagrama al repositorio. La región predeterminada es
`us-east-2`; la región efectiva todavía depende de la configuración de despliegue.
Se conserva el stage `dev`, el backend y el workspace.

### Cognito y sedes

- User Pool con alta administrativa, grupos exactos `Cliente`, `Técnico` y
  `Administrador`, sin roles IAM asociados. App Client público sin secreto,
  login SDK/SRP, sin dominio de User Pool ni OAuth. TOTP opcional; contraseñas
  de 12 caracteres con complejidad y vigencia temporal de 3 días.
- ID/access tokens: 15 minutos; refresh: 1 día. El App Client solo escribe
  `name`; no puede cambiar contacto, indicadores de verificación ni permisos.
  Outputs: `cognito_user_pool_id`, `cognito_user_pool_arn`, `cognito_app_client_id`.
- Identidad estable: `sub` opaco, sin normalizar. No se crea `custom:sede_id`.
  La migración aditiva 003 crea `sedes` y `usuario_sede_rol`, con PK compuesta
  `(usuario_sub, sede_id, rol)`, FK a `sedes` e índice `(sede_id, rol)`.
  Admite múltiples roles y sedes; ambos registros quedan inactivos por defecto.
- `servitech_app` solo lee las nuevas tablas. El script de permisos revoca
  concesiones directas y por columna a la app/PUBLIC y rechaza escritura
  heredada o propiedad administrativa. Las asignaciones se gestionan con una
  identidad administrativa separada; no se crean usuarios ni sedes ficticias.
  Revisar también funciones externas SECURITY DEFINER y cambios futuros de IAM/SQL.
- Las migraciones 001/002 y los históricos permanecen intactos. No se añade FK
  desde `servicios` ni se rellenan propietarios o sedes automáticamente.

| Operación | Cliente | Técnico / Administrador |
| --- | --- | --- |
| Registrar | Para sí mismo, indicando `sede_id` catalogada y activa | Solo si también tiene el grupo Cliente, siempre para sí mismo |
| Consultar / subir o descargar evidencia | Servicio propio en sede válida y activa; sin asignación operativa | Grupo Cognito y asignación activa del mismo rol en la sede activa |
| Diagnóstico / estado | Denegado por el rol Cliente | Grupo Cognito y asignación activa del mismo rol en la sede activa |
| Administrar asignaciones o cambiar propietario/sede | No disponible en la API | No disponible en la API |

No hay acceso global del Administrador ni propagación de privilegios entre sedes.
Los servicios sin propietario válido o sede activa se deniegan, incluido el
histórico incompleto. La regularización requiere intervención administrativa.

### Módulo y flujos

`lambda/shared/servitech_authz.py` se empaqueta en las cinco Lambda. Lee solo
`requestContext.authorizer.claims`, conserva `sub` y admite grupos como CSV o
lista de strings exactos. Rechaza `Tecnico`, grupos desconocidos y cadenas con
comillas/corchetes. El [ejemplo REST de AWS](https://aws.amazon.com/blogs/mobile/new-real-time-multi-group-app-with-aws-amplify-graphql-build-a-twitter-community-clone/)
usa CSV; el [token Cognito](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-id-token.html)
contiene una lista. Confirmar el formato del evento real durante el despliegue.
El módulo confía en API Gateway/IAM: no verifica firmas JWT ni acepta identidad
proporcionada por body o cabeceras arbitrarias. No exponer invocación directa
sin IAM; nunca reenviar claims del navegador sin pasar por el autorizador.

Los filtros parametrizados de propiedad/rol/sede forman parte del SELECT,
INSERT o UPDATE. Se deniega por defecto y no se cachean permisos. Una consulta
sin fila autorizada devuelve 404, sin distinguir ausencia de falta de acceso;
claims inválidos devuelven 401/403 y fallos de infraestructura 500/503.
La autorización usa la vista de permisos de la sentencia SQL; una revocación
concurrente no cancela una operación ya iniciada ni una URL prefirmada emitida.
No se añaden protocolos de bloqueos asesores ni mecanismos administrativos nuevos.

`ActualizarEstado` conserva el bloqueo de servicio y la transacción
estado + historial + outbox. Recomprueba el filtro en el UPDATE y consulta al
propietario en Cognito mediante el endpoint privado existente: `ListUsers`
resuelve el username y `AdminGetUser` valida sub, cuenta habilitada, teléfono
E.164 y `phone_number_verified=true`. Una comprobación fallida revierte todo;
solo se publica después del commit. No se modifica el despacho del outbox.
El endpoint/IAM siguen limitados al rol Lambda 4, pool y operaciones de lectura.

`GestionarEvidencias` invoca sincrónicamente a `ConsultarServicio` con IAM limitado
a su ARN y exige una respuesta válida para el servicio antes de firmar una URL.
Según Página 3, Lambda 5 queda fuera de la VPC: ya no consulta PostgreSQL ni
necesita permisos RDS/ENI; conserva acceso limitado a `servicios/*` de S3.
No se añade NAT ni endpoint. Las URL duran 300 segundos, preservan tipos
JPG/PNG/PDF y claves por servicio. S3 mantiene su CORS restringido al frontend.

### API y validación

| Método | Ruta | Lambda |
| --- | --- | --- |
| POST | `/servicios` | RegistrarServicio |
| GET | `/servicios/{id}` | ConsultarServicio |
| PATCH | `/servicios/{id}/diagnostico` | ActualizarDiagnostico |
| PATCH | `/servicios/{id}/estado` | ActualizarEstado |
| POST | `/servicios/{id}/evidencias` | GestionarEvidencias |

Las cinco rutas usan el autorizador Cognito del pool existente y un **ID token**
del App Client configurado en `Authorization`; el autorizador comprueba `aud`.
OPTIONS es público. Preflight, errores de Gateway y respuestas Lambda permiten
`Authorization`, `Content-Type` y los métodos usados. Se conserva origen `*`
sin cookies; acotarlo al origen aprobado al completar el frontend.
Se reutilizan API, recursos y stage. Se incorporan las correcciones aplicables
CKV_AWS_237 (ciclo de vida REST API) y CKV_AWS_73 (X-Ray del stage) del PR #1,
sin fusionar ni copiar cambios ajenos a este alcance.

Validación local: `python -B -m unittest discover -s tests -v`, pruebas SQL
explícitas en `tests/integration/check_authz_postgres.py`, empaquetado mediante
`scripts/build_lambdas.ps1` o `scripts/build_lambdas_ci.sh`, `terraform fmt -check`,
`terraform validate` y `git diff --check`. Ambos empaquetadores incluyen el módulo
en la raíz de los cinco ZIP y limpian solo sus directorios temporales.
No ejecutar ambos simultáneamente. ZIP, results.xml e informes no se incluyen en Git.

El portal inicia sesión por SRP, admite contraseña temporal y TOTP ya enrolado,
y envía el ID token a `/api/*` en el mismo origen. Los tokens solo viven en memoria;
recargar exige iniciar sesión. El alta, recuperación y enrolamiento MFA siguen
siendo administrativos. SDK `amazon-cognito-identity-js` 6.3.22 vendorizado desde
su paquete oficial npm, con integridad SHA-512 verificada y licencias incluidas.

CloudFront conserva S3 privado/OAC y añade API Gateway sin caché, reenviando
`Authorization` sin el Host del visitante. `/api/servicios` llega a `/dev/servicios`.
`frontend_domain = null` conserva HTTPS con el dominio de CloudFront. Para usar
dominio propio, configurar `frontend_domain` con `name` (FQDN real) y `zone_id`
(zona pública existente y delegada): Terraform valida ACM en `us-east-1` por DNS
y crea alias A/AAAA. No se registra un dominio ni se crea otra zona. Si ya existen
certificado o registros equivalentes, coordinar su importación antes de aplicar.
El bucket frontend tiene versionado habilitado, recuperado del PR #1 de Checkov.

Pendientes de despliegue: aplicar las migraciones con autorización; cargar sedes,
usuarios y asignaciones reales; definir dominio/zona si se requieren; comprobar
login, región, permisos AWS, conectividad, CORS y eventos reales.
El flujo real de verificación telefónica/SMS sigue pendiente; no se simula.
Las protecciones `prevent_destroy` y `deletion_protection=ACTIVE` bloquean
`destroy-dev.yml`: el procedimiento controlado de DEV se resolverá por separado.
El requisito de logs sigue siendo 14 días; las retenciones heredadas de 7 días
y el resto del monitoreo se coordinan con Jhonatan. No se modifica ese trabajo.

## Arquitectura

```text
Navegador ──HTTPS──> CloudFront ──> S3 privado (HTML, CSS y JavaScript)
    │
    └──HTTPS──> API Gateway /dev
                    ├── POST /servicios ──> Lambda RegistrarServicio ──> PostgreSQL
                    └── GET /servicios/{id} ──> Lambda ConsultarServicio ──> PostgreSQL
                                                │
                                                └── CloudWatch Logs (7 días)
```

El esquema anterior resume el MVP inicial. Ahora el navegador llama a `/api/*`
en CloudFront, que reenvía a API Gateway `/dev`. Las Lambda de datos acceden
a PostgreSQL dentro de la VPC; la base de datos no es pública.

## Estado y dependencias de integración

- Los recursos de CloudFront, S3, API Gateway, las dos Lambdas y PostgreSQL están
  definidos en el código. Esto no confirma que estén desplegados.
- La inspección inicial detectó que faltan `build/registrar_servicio.zip` y
  `build/consultar_servicio.zip`. Sin ellos, `terraform validate` falla en
  `terraform/lambdas.tf`, en las llamadas a `filebase64sha256`.
- Terraform publica `config.js` con los IDs públicos de Cognito. El frontend
  accede mediante `frontend_api_url`; no contiene secretos ni una URL API manual.
- Los grupos de logs y los outputs de esta rama deben incluirse en un despliegue
  coordinado. Si los grupos ya existen en AWS y no están en el estado compartido,
  el equipo debe coordinar su importación antes de aplicar; no borrarlos para
  resolver el conflicto.

## Requisitos y acceso

- Git.
- AWS CLI con el perfil SSO `servitech` configurado.
- Terraform compatible con la configuración del repositorio y el bloqueo S3
  `use_lockfile` del backend existente.
- Python con `venv` y acceso al índice de paquetes para ejecutar el empaquetador
  existente `scripts/build_lambdas.ps1`.
- PowerShell para los comandos de esta guía y el script de prueba.

| Configuración | Valor |
| --- | --- |
| Perfil AWS | `servitech` |
| Cuenta AWS | `694188424284` |
| Región predeterminada del código | `us-east-2`; despliegue efectivo pendiente de verificar |
| Región de IAM Identity Center | `us-east-2` |
| Workspace compartido | `dev` |
| Rama de monitoreo | `feat/monitoring-mvp` |

Desde la raíz del repositorio, iniciar sesión y comprobar la cuenta:

```powershell
aws sso login --profile servitech
aws sts get-caller-identity --profile servitech --query Account --output text
```

La cuenta debe ser `694188424284`. IAM Identity Center utiliza `us-east-2` para
SSO; la región principal acordada y predeterminada del código es `us-east-2`.
Esto no confirma la región efectiva de los recursos desplegados.

## Preparación y validación

El responsable de las Lambdas debe generar los paquetes reales con el script
existente, desde la raíz del repositorio:

```powershell
.\scripts\build_lambdas.ps1
```

El script empaqueta las dependencias Linux de Python 3.12 para ambas funciones.
Los ZIP de `build/` son artefactos locales ignorados por Git. No usar archivos
vacíos ni cambiar `lambdas.tf` para ocultar el error de validación.

Después, entrar en la carpeta de Terraform:

```powershell
Set-Location .\terraform
terraform init -reconfigure
terraform workspace select dev
terraform workspace show
```

Utilizar el backend S3 compartido ya definido en `backend.tf` y el workspace
existente `dev`. No crear otro backend, workspace ni estado local.

Formatear únicamente los archivos Terraform de esta responsabilidad y comprobar
el formato del conjunto sin modificar archivos de otros integrantes:

```powershell
terraform fmt monitoring.tf outputs.tf
terraform fmt -check
terraform validate
terraform plan -input=false
```

Revisar el plan completo: el estado remoto es compartido y el plan puede incluir
cambios de otros integrantes. Detenerse ante eliminaciones, reemplazos o cambios
inesperados y coordinarlos con el equipo. Los errores de dependencias ajenas deben
reportarse a su responsable, sin crear recursos sustitutos.

## Despliegue coordinado

**`terraform apply` requiere aprobación explícita y coordinación del equipo:**
afecta el estado remoto compartido. Ejecutar solamente después de resolver las
dependencias y revisar el plan en la cuenta y el workspace correctos:

```powershell
terraform apply
```

El bloqueo del backend no sustituye la coordinación entre integrantes.

## Outputs y acceso al frontend

Desde `terraform/`, después del despliegue coordinado:

```powershell
terraform output
terraform output -raw frontend_url
terraform output -raw api_url
terraform output -raw database_endpoint
terraform output -raw frontend_bucket
terraform output -raw aws_region
terraform output -raw environment
```

| Output | Contenido |
| --- | --- |
| `frontend_url` | URL HTTPS de CloudFront |
| `api_url` | URL base real de API Gateway, incluido `/dev` |
| `database_endpoint` | Host y puerto de PostgreSQL, accesibles desde la VPC |
| `frontend_bucket` | Nombre del bucket S3 privado |
| `aws_region` | Región configurada; por defecto `us-east-2` |
| `environment` | Workspace actual; debe ser `dev` |

Estos outputs no incluyen contraseñas, tokens, credenciales ni el ARN del secreto.
Los outputs se leen del estado: antes de aplicar estos cambios pueden no existir.

Para abrir el frontend:

```powershell
$frontendUrl = terraform output -raw frontend_url
if ($LASTEXITCODE -ne 0) { throw 'No se pudo obtener frontend_url.' }
Start-Process $frontendUrl
```

Usar CloudFront para acceder al sitio; el bucket S3 es privado. Si aparece el
aviso de API sin configurar, completar la dependencia de frontend indicada arriba.

## Contrato de RDS Proxy

RDS Proxy usa las dos subredes privadas de datos, el SG `aws_security_group.rds_proxy`
y la instancia Multi-AZ `aws_db_instance.postgres`. El proxy exige IAM y TLS a
los clientes. Para abrir sesiones en PostgreSQL usa el secreto de `servitech_app`.
Las dos Lambda del MVP conservan su ruta directa durante la transición.

### Preparación para el despliegue

1. Para un entorno nuevo, generar la contraseña fuera de Terraform y
   preregistrar el secreto dedicado en Secrets Manager, en la misma cuenta
   y región. Su versión `AWSCURRENT` contiene `username` igual a
   `servitech_app` y `password` con esa credencial. El secreto puede existir
   antes que el usuario PostgreSQL. Entregar solo su ARN mediante
   `TF_VAR_database_app_secret_arn`. Si usa una clave KMS propia, entregar
   también `TF_VAR_database_app_secret_kms_key_arn` y coordinar la política
   de clave para el rol del proxy.
2. Con el código actual, los paquetes Lambda y el backend y workspace
   previstos, preparar un primer plan manual de arranque limitado a RDS y
   sus dependencias con `terraform plan -input=false -target=aws_db_instance.postgres`.
   Usar ese alcance solo para este arranque excepcional. Revisar y autorizar
   el plan antes de ejecutarlo. Esperar a que la instancia privada Multi-AZ
   esté disponible y conservar el mismo estado para el plan completo.
3. Instalar el esquema y aprovisionar `servitech_app` desde una ruta
   administrativa privada siguiendo la sección SQL. Asignarle mediante
   el prompt interactivo la misma contraseña del secreto ya registrado.
   Confirmar que el rol puede iniciar sesión antes de crear el proxy.
4. Preparar y revisar un plan completo, sin `-target`, con el mismo código,
   backend, workspace y ARN de secreto. Confirmar `iam:PassRole` para el
   rol dedicado, la versión de PostgreSQL, los IDs de zona compatibles
   con RDS Proxy y las IP libres. Conservar la base predeterminada
   `postgres`. Tras un despliegue autorizado, verificar la salud del
   destino y probar una conexión IAM con verificación TLS.

`database_app_secret_arn` es una variable obligatoria. Los workflows
`deploy-dev.yml` y `destroy-dev.yml` actualmente solo inyectan la región como
variable de Terraform. Cuando ejecuten la configuración de esta fase, sus
planes con `-input=false` fallarán hasta que el entorno de ambos jobs reciba
`TF_VAR_database_app_secret_arn` con el ARN real. Para una actualización
posterior de CI, configurar el ARN como variable del entorno de GitHub
`dev` y mapearla al mismo `TF_VAR_` en ambos jobs. Mapear el ARN KMS cuando
corresponda y conservar el secreto y su configuración hasta que se retire
el proxy. El primer arranque requiere la pausa manual del paso 3 antes de
habilitar el despliegue automático. `terraform validate` comprueba la
configuración sin exigir el valor de la variable. Confirmar el workspace
efectivo antes de operar, porque los workflows declaran `default` y la
guía histórica del MVP usa `dev`.

El pool empieza con un máximo del 80 % de `max_connections` para dejar margen
al acceso directo del MVP y a la administración. Mantiene hasta un 40 % de
`max_connections` en conexiones ociosas para reutilizarlas. La espera para
obtener una conexión es de 5 s para dejar margen dentro del timeout de 15 s del
MVP. El proxy cierra clientes inactivos tras 300 s. Ajustar estos valores
después de medir el uso y la latencia de préstamo en el entorno real.

### Gordillo · conexión de las Lambda 1–4

- Usar las subredes privadas de aplicación y
  `aws_security_group.rds_proxy_client.id` (output
  `database_proxy_client_security_group_id`). Para Lambda 4, añadir
  `aws_security_group.lambda4_publisher.id` para el endpoint de EventBridge.
- Configurar `DB_HOST` con `database_proxy_endpoint`
  (`aws_db_proxy.postgres.endpoint`), `DB_PORT` con `database_port` (5432),
  `DB_NAME` con `database_name` (`servitech`) y `DB_USER` con
  `database_app_username` (`servitech_app`). Configurar `DB_SSLROOTCERT` con
  la ruta al PEM de raíces de Amazon Trust Services disponible en el paquete.
- Generar el token IAM con el SDK para cada conexión física nueva usando el
  hostname real del proxy, puerto, usuario y región efectiva (`AWS_REGION`).
  Pasar el token como contraseña al driver y usar `sslmode=verify-full` con
  `sslrootcert` apuntando al PEM. Mantener los tokens fuera de los logs.
- Autorizar `rds-db:connect` en cada rol consumidor usando como recurso
  exclusivo `database_proxy_connect_arn`. Ese ARN usa el ID `prx-...` y
  `servitech_app`. Los outputs `database_proxy_arn` y `database_instance_arn`
  identifican los recursos de infraestructura.
- Antes de migrar las dos Lambda existentes, preparar el esquema y retirar
  su DDL de arranque. Verificar registro y consulta por el proxy antes de
  retirar, en una fase posterior, las reglas directas del MVP y su permiso
  de lectura del secreto maestro.

## Esquema PostgreSQL e historial

En una instalación nueva, el rol de migraciones ejecuta `psql -X -v
ON_ERROR_STOP=1 -f sql/schema.sql` sobre la base `servitech`. Este punto de
entrada de psql crea la tabla base e incluye las tres migraciones. Si el MVP ya creó
`public.servicios`, ejecutar `psql -X -v ON_ERROR_STOP=1 -f
sql/migrations/001_servicios_historial.sql` si la fase 3 aún está pendiente,
y luego `psql -X -v ON_ERROR_STOP=1 -f sql/migrations/002_servicio_outbox.sql`
y `psql -X -v ON_ERROR_STOP=1 -f sql/migrations/003_sedes_asignaciones.sql`.
Si 001 y 002 ya están aplicadas, ejecutar únicamente 003. No se reescriben las
migraciones anteriores. Para aprovisionar `servitech_app` con el script actualizado,
las tres migraciones deben estar aplicadas previamente.
Cada migración aplica sus cambios en una transacción y se puede volver a
ejecutar sobre el mismo esquema. Si `servitech_app` ya existe, la identidad
autorizada debe ejecutar `psql -X -v ON_ERROR_STOP=1 -f sql/grant_servicio_outbox.sql`
después de la migración 002 para otorgar los permisos adicionales. La migración
003 incluye `sql/grant_sedes_lectura.sql` y comprueba los permisos de las nuevas
tablas; ante una excepción, no se confirma ninguno de sus cambios. Las versiones
anteriores de esquema y datos permanecen intactas.
Coordinar la ventana porque `ALTER TABLE` puede bloquear temporalmente el
acceso y la creación de índices puede tardar según el volumen.

| Tabla | Contrato |
| --- | --- |
| `public.servicios` | Conserva `id` entero autogenerado, `cliente`, `equipo`, `descripcion` y `fecha_registro`. Añade `numero_serie` (texto), `fecha_recepcion` (timestamp con zona), `diagnostico` y `tratamiento` (texto), `presupuesto` (importe numérico finito y no negativo), `estado` (texto), `version` (entero de 64 bits, inicialmente 0), `cliente_sub` (identificador de propietario, `clienteSub` en el contrato de aplicación) y `sede_id` (identificador de sede). Los campos nuevos salvo `version` admiten NULL, de modo que los registros e INSERT del MVP siguen siendo válidos. |
| `public.servicio_estado_historial` | Una fila por versión de cambio de estado. Clave primaria `(servicio_id, version)`, que también indexa el historial por servicio y versión. `servicio_id` referencia a `servicios.id` y `version` es positiva. `estado_anterior` admite NULL para un servicio sin estado previo. `estado_nuevo` es obligatorio. `actor_sub` admite NULL y `cambiado_en` se genera en la base. |

`RegistrarServicio` debe enviar los datos de recepción y propiedad que tenga
verificados. `ConsultarServicio` puede filtrar por `cliente_sub` y `sede_id`
mediante los índices previstos y debe aplicar las reglas de acceso del equipo
con la identidad autenticada. Un campo de propiedad o sede nulo requiere
resolución antes de usarlo como evidencia de acceso. Quedan por definir el
catálogo y las transiciones de estados, la moneda del presupuesto, el
contenido real del catálogo de sedes. La fuente de roles es Cognito y su alcance
por sede se registra en PostgreSQL y ya se comprueba en las Lambda. El Cliente
accede a sus propios servicios en una sede activa sin asignación operativa.
El SQL no inventa esos valores.

`ActualizarDiagnostico` utiliza `diagnostico`, `tratamiento` y `presupuesto`.
`ActualizarEstado` debe leer y bloquear la fila del servicio con `SELECT ...
FOR UPDATE` dentro de una transacción, comparar la versión esperada y, si
coincide, incrementar `version`, actualizar `estado` e insertar en el historial
la versión resultante y los estados anterior y nuevo. Si falla cualquiera
de las escrituras, debe revertir ambas. Por ahora, `version` se usa como
contador de cambios de estado.

### Aprovisionar el usuario y el secreto

1. Usar una sesión administrativa autorizada con conectividad privada hacia
   el endpoint directo de RDS, desde un equipo con acceso privado a la VPC
   o desde un cliente de administración autorizado dentro de ella. Antes de
   operar, coordinar una ruta privada y acceso TCP 5432 desde ese cliente.
   Las reglas actuales solo permiten los SG del MVP y del proxy hacia RDS.
   Verificar el certificado y el hostname de RDS con `sslmode=verify-full` y el bundle
   de CA de RDS. Ejecutar primero el esquema con la identidad de migración.
2. Con una identidad autorizada para administrar roles y otorgar privilegios
   en `servitech`, ejecutar una vez `psql -X -v ON_ERROR_STOP=1 -f
   sql/provision_servitech_app.sql`. El rol se crea con `NOLOGIN`, sin
   `rds_iam`, con permisos de lectura y escritura acotados a las operaciones
   previstas y sin privilegios de propietario ni de DDL persistente. Si el
   script detecta `CREATE` efectivo heredado de `PUBLIC` en la base o el
   esquema, el administrador debe revisar esos permisos antes de repetirlo.
3. Generar la contraseña en un gestor seguro. Asignarla mediante el prompt
   interactivo `\password servitech_app` de psql. Si el secreto ya se registró
   para el arranque, usar su contraseña vigente. Guardar la misma credencial
   en el secreto dedicado al aprovisionar uno por primera vez.
   Mantener la contraseña fuera de SQL, archivos y argumentos de comandos.
   Habilitar el acceso con `ALTER ROLE servitech_app LOGIN;` una vez que el
   secreto esté listo. Comprobar que la versión vigente del secreto coincide
   con el rol SQL antes de habilitar el proxy.
4. Para mantener los privilegios del nuevo usuario, Gordillo deberá retirar
   el `CREATE TABLE IF NOT EXISTS` de ambas Lambda cuando migren al proxy.
   Durante esta fase, las Lambda actuales continúan usando el camino MVP.

## Outbox de EstadoActualizado

La Página 3 enumera literalmente `eventId`, `servicioId`, `clienteSub`,
`estado`, «versión» y «teléfono verificado del destinatario (E.164)».
El contrato JSON usa `version` según el requisito de esta fase y
`telefonoVerificado` como clave técnica para el teléfono, que el diagrama
describe sin asignarle un nombre de campo.

| Campo en el detalle JSON | Columna de `public.servicio_outbox` | Tipo JSON |
| --- | --- | --- |
| `eventId` | `event_id` | Cadena UUID generada por PostgreSQL |
| `servicioId` | `servicio_id` | Entero |
| `clienteSub` | `cliente_sub` | Cadena |
| `estado` | `estado` | Cadena |
| `version` | `version` | Entero |
| `telefonoVerificado` | `telefono_verificado_e164` | Cadena E.164 |

Plantilla JSON del detalle de `EstadoActualizado`. Los marcadores deben
reemplazarse por valores de la fila persistida. Los dos marcadores numéricos
se sustituyen por enteros JSON.

```json
{
  "eventId": "<UUID registrado>",
  "servicioId": "<ID entero del servicio>",
  "clienteSub": "<sub del cliente>",
  "estado": "<estado registrado>",
  "version": "<versión entera registrada>",
  "telefonoVerificado": "<teléfono realmente verificado en E.164>"
}
```

### Gordillo · escritura y publicación

1. En la transacción de `ActualizarEstado`, bloquear el servicio y comprobar
   la versión esperada. Actualizar el estado y la versión, insertar el historial
   e insertar el outbox con la misma pareja `(servicio_id, version)`. Derivar
   `servicio_id`, `version` y `estado` de la fila de historial creada y
   `cliente_sub` de la fila de servicio bloqueada, en vez de aceptar esos
   valores por separado en la petición. La FK garantiza la pareja
   servicio-versión. La correspondencia de estado y propietario depende de
   esta escritura. Obtener el teléfono desde la fuente autorizada. El SQL
   valida el formato E.164. Si faltan los datos requeridos o falla alguna
   escritura, revertir la transacción completa.
2. Tras el `COMMIT`, cualquier publicador inmediato debe usar el mismo
   mecanismo de reserva que los reintentos. Usar `PutEvents` únicamente
   después de confirmar también la transacción de reserva, con la sesión
   PostgreSQL fuera de transacción.

### Jhonatan · AWS Backup, despacho y reintentos

- Para seleccionar RDS en AWS Backup, usar el output `database_instance_arn`
  (`aws_db_instance.postgres.arn`). El identificador es
  `aws_db_instance.postgres.identifier`, de forma
  `${local.name_prefix}-postgres`, y figura al final de ese ARN tras
  `:db:`. Validar la clave KMS y la configuración de cuentas antes de
  implementar la copia centralizada.
- La Página 3 prevé que EventBridge Scheduler invoque la Lambda 4 cada
  minuto mediante IAM para despachar pendientes. Coordinar con Gordillo
  una entrada de despacho que use el mismo mecanismo de reserva que la
  publicación inmediata. El rol de Scheduler deberá poder invocar esa
  función. El contrato JSON está en la tabla anterior.

Reservar un lote pequeño en una transacción corta. `$1` es el tamaño
positivo del lote y `$2` es una duración positiva de reserva, suficiente
para el plazo de envío y confirmación del lote. Para publicación inmediata
se puede agregar un filtro por `event_id` a la selección. La reserva consume
un intento aunque el proceso termine antes del envío.

```sql
WITH pendientes AS (
    SELECT event_id
    FROM public.servicio_outbox
    WHERE publicado_en IS NULL AND disponible_desde <= statement_timestamp()
    ORDER BY disponible_desde, creado_en, event_id
    LIMIT $1
    FOR UPDATE SKIP LOCKED
)
UPDATE public.servicio_outbox AS o
SET intentos = o.intentos + 1,
    disponible_desde = statement_timestamp() + $2::interval
FROM pendientes
WHERE o.event_id = pendientes.event_id
RETURNING o.*;
```

- Confirmar la reserva y luego enviar. Revisar el resultado de cada entrada
  de `PutEvents`: al aceptar una, fijar `publicado_en`; ante error, fijar
  `disponible_desde` con la demora de reintento. Acotar la demora e incorporar
  variación aleatoria para evitar reintentos simultáneos. En ambos casos
  actualizar solo si coinciden `event_id`, el `intentos` devuelto por la
  reserva y `publicado_en IS NULL`. Cero filas actualizadas indica que la
  reserva ya no corresponde al trabajador.
- Al vencer una reserva sin confirmar, la fila vuelve a estar disponible.
  Si el envío fue aceptado y el trabajador cayó antes de marcarlo, puede
  reenviarse. Reutilizar el mismo `eventId` en todos los intentos y deduplicar
  efectos en los consumidores con ese identificador persistido. EventBridge
  no garantiza entrega exactamente una vez.
- El rol `servitech_app` puede leer el outbox, insertar el detalle y
  actualizar solo los metadatos de despacho. El UUID, el detalle y la
  fecha de creación quedan fuera de sus permisos de actualización.

## Prueba de registro y consulta

Cada ejecución del script crea un registro real de prueba. Desde la raíz:

```powershell
.\scripts\test_mvp.ps1
```

El script obtiene `api_url` del estado existente en `terraform/`. También acepta
la URL real, incluido el stage, como parámetro:

```powershell
$apiUrl = terraform -chdir=terraform output -raw api_url
if ($LASTEXITCODE -ne 0) { throw 'No se pudo obtener api_url.' }
.\scripts\test_mvp.ps1 -ApiUrl $apiUrl
```

Si Windows bloquea los archivos `.ps1`, se puede habilitar su ejecución solamente
para este proceso, sin cambiar la política persistente del equipo:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_mvp.ps1
```

Realiza `POST /servicios` con este contenido y exige HTTP 201:

```json
{
  "cliente": "Juan Perez",
  "equipo": "Laptop",
  "descripcion": "No enciende"
}
```

Lee el `id` real del JSON devuelto y llama a `GET /servicios/{id}`. Exige HTTP
200 y compara el ID y los tres campos con los datos enviados. Muestra el registro
recuperado. Un timeout de POST puede ocurrir después de guardar: comprobar lo
sucedido antes de repetir la prueba para evitar duplicados.

También comprueba estos casos:

| Caso | Solicitud | HTTP esperado |
| --- | --- | --- |
| POST válido | Los tres campos de texto no vacíos | 201 |
| POST inválido | `{}` | 400 |
| GET existente | ID devuelto por el POST | 200 |
| GET inexistente | ID positivo que no exista en la base | 404 |

Para el último caso, el script usa `2147483647` por defecto. Si ese ID existe,
elegir otro ID positivo confirmado como inexistente mediante el parámetro
`-MissingServiceId`. El script falla si recibe 200 y no declara ese caso aprobado.

La prueba HTTP verifica el comportamiento de la API. Para acreditar persistencia,
revisar junto al responsable de PostgreSQL el registro del ID creado en la tabla
`servicios`; las Lambdas integradas ejecutan INSERT/SELECT reales.

## Prueba desde navegador y CORS

Con la URL real de API integrada en el frontend y publicada:

1. Abrir `frontend_url`, iniciar sesión y abrir las herramientas del desarrollador.
2. Registrar un servicio en una sede activa y guardar el ID devuelto.
3. Consultar ese ID y comprobar que los datos coincidan.
4. Verificar POST/GET por `/api/*` con `Authorization`, sin caché de respuestas
   privadas; para evidencias comprobar el CORS de S3 desde el dominio del portal.

PowerShell no aplica las restricciones CORS del navegador: aprobar el script no
sustituye esta comprobación.

## CloudWatch Logs

En la consola AWS, seleccionar la cuenta del proyecto y `us-east-2`, abrir
CloudWatch → Logs → Log groups y buscar, con los nombres predeterminados actuales:

- `/aws/lambda/servitech-dev-registrar-servicio`
- `/aws/lambda/servitech-dev-consultar-servicio`

Cada grupo tiene retención de 7 días. Después de la prueba, revisar los streams y
las marcas de tiempo de ambas invocaciones. También se pueden seguir desde CLI:

```powershell
aws logs tail /aws/lambda/servitech-dev-registrar-servicio --since 10m --follow --profile servitech --region us-east-2
```

Terminar con `Ctrl+C` y repetir para la consulta:

```powershell
aws logs tail /aws/lambda/servitech-dev-consultar-servicio --since 10m --follow --profile servitech --region us-east-2
```

Las Lambdas actuales registran mensajes genéricos de error. No agregar al log
eventos completos, contraseñas, valores de secretos, tokens ni credenciales.
La retención no oculta información sensible: el código debe evitar emitirla.

## Criterios de aceptación

- [ ] Formato Terraform correcto y `terraform validate` aprobado con los ZIP reales.
- [ ] Plan completo revisado e infraestructura desplegada de forma coordinada.
- [ ] CloudFront abre el frontend con la URL de API real integrada.
- [ ] POST devuelve 201 y el ID generado por un INSERT real en PostgreSQL.
- [ ] GET de ese ID devuelve 200 y los mismos datos guardados.
- [ ] POST inválido devuelve 400 y GET inexistente devuelve 404.
- [ ] El navegador completa el flujo sin errores CORS.
- [ ] CloudWatch registra las ejecuciones de ambas Lambdas, con retención de 7 días.
- [ ] No hay credenciales expuestas en outputs, respuestas ni logs.

Un `terraform apply` exitoso por sí solo no completa el MVP.

## Retirada coordinada

**`terraform destroy` requiere aprobación explícita y coordinación de todo el
equipo:** elimina infraestructura del workspace compartido. No ejecutarlo para
limpiar solamente el trabajo individual. Antes, revisar la cuenta, el workspace,
el alcance del plan y la conservación de los datos de PostgreSQL.

Desde `terraform/`, únicamente cuando el equipo lo autorice:

```powershell
terraform workspace show
terraform plan -destroy
terraform destroy
```

La configuración actual exige una instantánea final de PostgreSQL y el bucket
del frontend contiene objetos; revisar con sus responsables cualquier impedimento
de retirada, sin cambiar infraestructura ajena ni borrar recursos manualmente.
