# ServiTech — MVP en AWS

ServiTech permite registrar y consultar servicios técnicos. Terraform administra
la infraestructura del MVP. La demostración requiere un INSERT real en PostgreSQL
y un SELECT del mismo registro por el ID devuelto; una respuesta simulada no basta.

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

El JavaScript servido por CloudFront llama directamente a API Gateway. Las
Lambdas acceden a PostgreSQL dentro de la VPC; la base de datos no es pública.

## Estado y dependencias de integración

- Los recursos de CloudFront, S3, API Gateway, las dos Lambdas y PostgreSQL están
  definidos en el código. Esto no confirma que estén desplegados.
- La inspección inicial detectó que faltan `build/registrar_servicio.zip` y
  `build/consultar_servicio.zip`. Sin ellos, `terraform validate` falla en
  `terraform/lambdas.tf`, en las llamadas a `filebase64sha256`.
- `frontend/app.js` contiene `API_URL_PENDIENTE`. El responsable del frontend debe
  integrar la URL real del output `api_url`, incluido `/dev`, y coordinar su
  publicación. Hasta entonces no se puede completar la prueba desde navegador.
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
| Región de los recursos | `us-east-1` |
| Región de IAM Identity Center | `us-east-2` |
| Workspace compartido | `dev` |
| Rama de monitoreo | `feat/monitoring-mvp` |

Desde la raíz del repositorio, iniciar sesión y comprobar la cuenta:

```powershell
aws sso login --profile servitech
aws sts get-caller-identity --profile servitech --query Account --output text
```

La cuenta debe ser `694188424284`. IAM Identity Center utiliza `us-east-2` para
SSO; el despliegue permanece en `us-east-1`.

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
| `aws_region` | Región configurada; por defecto `us-east-1` |
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

1. En un entorno nuevo, aprovisionar primero la red y la instancia privada
   Multi-AZ con la configuración de la fase 1, anterior a los recursos y
   variables del proxy. Usar el backend y workspace previstos para el
   entorno. Esperar a que RDS esté disponible y conservar ese mismo estado
   para incorporar la fase 2.
2. Instalar el esquema y aprovisionar `servitech_app` desde una ruta
   administrativa privada siguiendo el procedimiento de la sección SQL.
3. Crear en Secrets Manager un secreto dedicado en la misma cuenta y región.
   Su versión `AWSCURRENT` debe contener las claves JSON `username` y
   `password`, con `servitech_app` y la contraseña vigente del rol. Coordinar
   la rotación de ambas credenciales. Pasar solo el ARN completo mediante
   `TF_VAR_database_app_secret_arn`. Si el secreto usa una clave KMS propia, proporcionar su ARN por
   `TF_VAR_database_app_secret_kms_key_arn` y autorizar el rol del proxy en la
   política de clave. Mantener los valores del secreto fuera de Terraform.
4. Con el rol SQL y el secreto ya disponibles, incorporar la fase 2 al mismo
   entorno para aprovisionar el rol IAM y el proxy sobre la instancia existente.
   Confirmar que el rol de despliegue puede crear los recursos de proxy e IAM
   y que tiene `iam:PassRole` para el rol dedicado. Verificar la región, versión
   de PostgreSQL, IDs de zona compatibles con RDS Proxy e IP libres en las
   subredes. Conservar la base predeterminada `postgres` que requiere el proxy.
   Tras un despliegue autorizado, verificar que el destino esté disponible.

`database_app_secret_arn` es una variable obligatoria. Los workflows
`deploy-dev.yml` y `destroy-dev.yml` actualmente solo inyectan la región como
variable de Terraform. Cuando ejecuten la configuración de esta fase, sus
planes con `-input=false` fallarán hasta que el entorno de ambos jobs reciba
`TF_VAR_database_app_secret_arn` con el ARN real. Si se usa una clave propia,
proporcionar también su ARN al desplegar. `terraform validate` comprueba la
configuración sin exigir el valor de la variable.

El pool empieza con un máximo del 80 % de `max_connections` para dejar margen
al acceso directo del MVP y a la administración. Mantiene hasta un 40 % de
`max_connections` en conexiones ociosas para reutilizarlas. La espera para
obtener una conexión es de 5 s para dejar margen dentro del timeout de 15 s del
MVP. El proxy cierra clientes inactivos tras 300 s. Ajustar estos valores
después de medir el uso y la latencia de préstamo en el entorno real.

### Integración de las Lambda 1–4

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
entrada de psql crea la tabla base e incluye las dos migraciones. Si el MVP ya creó
`public.servicios`, ejecutar `psql -X -v ON_ERROR_STOP=1 -f
sql/migrations/001_servicios_historial.sql` si la fase 3 aún está pendiente,
y luego `psql -X -v ON_ERROR_STOP=1 -f sql/migrations/002_servicio_outbox.sql`.
Cada migración aplica sus cambios en una transacción y se puede volver a
ejecutar sobre el mismo esquema. Si `servitech_app` ya existe, la identidad
autorizada debe ejecutar `psql -X -v ON_ERROR_STOP=1 -f sql/grant_servicio_outbox.sql`
después de la migración 002 para otorgar los permisos adicionales.
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
catálogo de sedes y la fuente de roles. El SQL deja esos valores a la
integración de aplicación.

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
   o desde un cliente de administración autorizado dentro de ella. Verificar
   el certificado de RDS y su hostname con `sslmode=verify-full` y el bundle
   de CA de RDS. Ejecutar primero el esquema con la identidad de migración.
2. Con una identidad autorizada para administrar roles y otorgar privilegios
   en `servitech`, ejecutar una vez `psql -X -v ON_ERROR_STOP=1 -f
   sql/provision_servitech_app.sql`. El rol se crea con `NOLOGIN`, sin
   `rds_iam`, con permisos de lectura y escritura acotados a las operaciones
   previstas y sin privilegios de propietario ni de DDL persistente. Si el
   script detecta `CREATE` efectivo heredado de `PUBLIC` en la base o el
   esquema, el administrador debe revisar esos permisos antes de repetirlo.
3. Generar la contraseña en un gestor seguro. Asignarla mediante el prompt
   interactivo `\password servitech_app` de psql. Guardar la misma
   credencial en Secrets Manager en el secreto dedicado descrito arriba.
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
   e insertar el outbox con la misma pareja `(servicio_id, version)`. Construir
   el detalle con el nuevo estado, el propietario y el número verificado de
   la fuente autorizada. El SQL valida el formato E.164. Si faltan los datos
   requeridos o falla alguna escritura, revertir la transacción completa.
2. Tras el `COMMIT`, cualquier publicador inmediato debe usar el mismo
   mecanismo de reserva que los reintentos. Usar `PutEvents` únicamente
   después de confirmar también la transacción de reserva, con la sesión
   PostgreSQL fuera de transacción.

### Jhonatan · despacho y reintentos

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

1. Abrir `frontend_url` y las herramientas del desarrollador (Consola y Red).
2. Registrar un servicio con el formulario y guardar el ID devuelto.
3. Consultar ese ID y comprobar que los datos coincidan.
4. Verificar que el preflight `OPTIONS` y las solicitudes POST/GET funcionen
   entre el origen CloudFront y API Gateway, sin errores de CORS en la consola.

PowerShell no aplica las restricciones CORS del navegador: aprobar el script no
sustituye esta comprobación.

## CloudWatch Logs

En la consola AWS, seleccionar la cuenta del proyecto y `us-east-1`, abrir
CloudWatch → Logs → Log groups y buscar, con los nombres predeterminados actuales:

- `/aws/lambda/servitech-dev-registrar-servicio`
- `/aws/lambda/servitech-dev-consultar-servicio`

Cada grupo tiene retención de 7 días. Después de la prueba, revisar los streams y
las marcas de tiempo de ambas invocaciones. También se pueden seguir desde CLI:

```powershell
aws logs tail /aws/lambda/servitech-dev-registrar-servicio --since 10m --follow --profile servitech --region us-east-1
```

Terminar con `Ctrl+C` y repetir para la consulta:

```powershell
aws logs tail /aws/lambda/servitech-dev-consultar-servicio --since 10m --follow --profile servitech --region us-east-1
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
