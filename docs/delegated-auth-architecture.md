# Arquitectura de Autenticación Delegada por Usuario

**Estado:** Requisito obligatorio antes del despliegue org-wide del MCP Hub  
**Prioridad:** Prerequisito de Fase 1  
**Responsable técnico:** IT / Basis SAP

---

## El problema: sesión compartida (estado actual)

El plugin actual usa una sesión compartida: `sap_login.ps1` guarda un token de una cuenta
de servicio que todos los usuarios del plugin comparten. Esto significa que **cualquier
usuario que use la IA puede ver datos con los permisos de esa cuenta**, independientemente
de sus propios roles en SAP.

```
Usuario A (solo Compras) ──┐
                            ├──▶ MCP Hub ──▶ SAP como "svc_claude" ──▶ ve TODO
Usuario B (solo Finanzas) ─┘
```

Esto es inaceptable para un despliegue a toda la organización.

---

## La solución: Principal Propagation (identidad delegada)

Cada llamada al MCP Hub viaja firmada con la identidad real del usuario. SAP aplica sus
propios roles y autorizaciones — exactamente igual que si el usuario entrara por SAP GUI o
Fiori.

```
Usuario A ──▶ Azure AD (JWT) ──▶ MCP Hub ──▶ SAP IAS ──▶ SAP como "AUSUARIO_A" ──▶ ve solo Compras
Usuario B ──▶ Azure AD (JWT) ──▶ MCP Hub ──▶ SAP IAS ──▶ SAP como "BFINANZAS"  ──▶ ve solo Finanzas
```

---

## Flujo técnico paso a paso

### 1 — Usuario se autentica en la Web App
El frontend usa **MSAL.js** (Microsoft Authentication Library) para iniciar el flujo
OAuth 2.0 PKCE contra Azure AD. El usuario se autentica con su cuenta corporativa
(@heurafoods.com). Azure AD devuelve:

- `access_token` — JWT firmado, scope: API de la web app de Heura
- `id_token` — identidad del usuario (UPN, grupos AD)

### 2 — Frontend envía el JWT al backend
Cada petición al backend incluye el token en la cabecera HTTP:
```
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9...
```

### 3 — Backend valida el JWT
El backend (Azure App Service) verifica la firma del token contra las claves públicas de
Azure AD (JWKS endpoint). Si el token no es válido o ha expirado → 401 Unauthorized.

Extrae del token:
- `oid` (Object ID del usuario en Azure AD)
- `upn` (user principal name: jsanchez@heurafoods.com)
- `groups` (grupos AD del usuario → determina qué herramientas MCP puede usar)

### 4 — Token Exchange: Azure AD JWT → SAP OAuth token

El backend realiza un **OAuth 2.0 Token Exchange** (RFC 8693) contra SAP IAS:

```http
POST https://<tenant>.accounts.ondemand.com/oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=urn:ietf:params:oauth:grant-type:token-exchange
&subject_token=<jwt_azure_ad>
&subject_token_type=urn:ietf:params:oauth:token-type:jwt
&requested_token_type=urn:ietf:params:oauth:token-type:saml2
&resource=<SAP_S4_system_alias>
&client_id=<heura_app_client_id>
&client_secret=<desde_key_vault>
```

SAP IAS valida que el JWT viene de Azure AD (IdP de confianza configurado) y emite un
token OAuth válido para el sistema SAP de destino, mapeando el UPN de Azure AD al usuario
SAP correspondiente.

### 5 — MCP Hub llama a SAP OData con el token SAP

```http
GET /sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder?$top=5
Authorization: Bearer <sap_oauth_token>
```

SAP ejecuta la consulta **como el usuario real** y aplica todos sus objetos de autorización
(roles, perfiles, `S_TABU_*`, etc.). El resultado está filtrado igual que en SAP GUI.

### 6 — El token SAP se cachea en memoria (no en disco)

Para evitar hacer el Token Exchange en cada petición (lento), el backend cachea el token
SAP en memoria asociado al `oid` del usuario Azure AD. Los tokens SAP tienen TTL corto
(1 hora típicamente) — se renuevan automáticamente cuando expiran.

```
key:   oid:f47ac10b-58cc-4372-a567-0e02b2c3d479
value: { sap_token: "...", expires_at: 1750000000 }
TTL:   55 minutos (5 min de margen)
```

---

## Configuración requerida en SAP (Basis)

### A — Activar OAuth 2.0 en SAP S/4HANA

Transacción: `/n/IWFND/V4_ADMIN` o `SOAUTH2`

1. Activar el servicio OAuth 2.0 en `SICF`:
   `sap/bc/sec/oauth2/token`
2. Crear un OAuth 2.0 Client en `SOAUTH2`:
   - Client ID: `heura-claude-mcp`
   - Allowed Grant Types: `urn:ietf:params:oauth:grant-type:token-exchange`
   - Trusted IdP: SAP IAS tenant de Heura

### B — Configurar SAP IAS como Identity Provider federado con Azure AD

En el portal de SAP IAS (`https://<tenant>.accounts.ondemand.com/admin`):

1. **Identity Providers → Corporate Identity Providers → Add**
   - Tipo: Microsoft Azure Active Directory
   - Metadata URL: `https://login.microsoftonline.com/<tenant_id>/federationmetadata/2007-06/federationmetadata.xml`

2. **Applications → Create Application**
   - Tipo: SAP BTP / SAP S/4HANA
   - Subject Name Identifier: `User UUID` mapeado a Azure AD `oid`
   - Default Authenticating IdP: Azure AD (el configurado en paso 1)

3. **Conditional Authentication**
   - Forzar que usuarios del dominio `@heurafoods.com` autentiquen siempre via Azure AD

### C — Mapeo de usuarios Azure AD → SAP

El sistema necesita saber que `jsanchez@heurafoods.com` (Azure AD) es el usuario `JSANCHEZ`
en SAP. Hay dos opciones:

| Opción | Cómo | Cuándo usar |
|--------|------|-------------|
| **UPN como SAP username** | Configurar SAP IAS para mapear el UPN directamente | Si los usernames SAP coinciden con el prefijo del email |
| **Atributo personalizado** | Añadir campo `sapUsername` al perfil de usuario en Azure AD | Si los usernames SAP son distintos del email |

En Heura, verificar si `JSANCHEZ` = `jsanchez` (prefijo UPN). Si es así, la opción 1 es
inmediata.

---

## Configuración requerida en Azure AD

### Registro de aplicación — Heura AI Backend

En Azure Portal → Azure Active Directory → App Registrations → New Registration:

```
Nombre:           Heura AI Assistant Backend
Redirect URIs:    https://ai.heurafoods.com/auth/callback
                  https://localhost:3000/auth/callback (dev)
Supported types:  Accounts in this organizational directory only
```

**API Permissions necesarios:**
```
Microsoft Graph:
  - User.Read (delegado) — leer perfil del usuario autenticado
  - People.Read (delegado) — buscar compañeros en M365
  - Mail.Send (delegado) — enviar email como el usuario
  - Calendars.Read (delegado) — leer calendario
  - Files.Read.All (delegado) — leer SharePoint/OneDrive

Custom API (la propia web app):
  - access_as_user (scope propio para el token exchange)
```

**Client Secret:** generado y almacenado en Azure Key Vault. Rotación cada 12 meses.

---

## Odoo: API key por usuario

Odoo no soporta OAuth 2.0 delegado nativo. La solución es:

1. Cada usuario de Heura genera su API key en Odoo (Settings → Technical → API Keys)
2. IT la almacena en Azure Key Vault con el Key Vault secret name: `odoo-apikey-{oid_azure_ad}`
3. El MCP Hub, al recibir una petición, recupera la API key del usuario desde Key Vault
   y la usa para las llamadas JSON-RPC

```
Key Vault secret: odoo-apikey-f47ac10b-58cc-4372-a567-0e02b2c3d479
Value:            a1b2c3d4e5f6...  (API key Odoo del usuario)
```

**Automatización recomendada:** script de onboarding que al crear un usuario en Odoo
genera automáticamente su API key y la guarda en Key Vault.

---

## M365 / Graph API: ya resuelto por diseño

El conector M365 usa OAuth 2.0 delegado nativo de Azure AD. El `access_token` obtenido
en el paso 1 del flujo principal (con los scopes de Graph API) se usa directamente para
las llamadas a Microsoft Graph. No requiere configuración adicional.

Graph siempre responde con los datos que el usuario real tiene permiso de ver (buzón
propio, archivos compartidos con él, directorio corporativo, etc.).

---

## Estructura de Key Vault

```
heura-ai-keyvault/
├── secrets/
│   ├── azure-ad-client-secret          ← Client secret del App Registration
│   ├── sap-ias-client-id               ← OAuth client ID en SAP IAS
│   ├── sap-ias-client-secret           ← OAuth client secret en SAP IAS
│   ├── sap-ias-token-endpoint          ← URL del token endpoint de SAP IAS
│   ├── odoo-apikey-{oid_1}             ← API key Odoo de usuario 1
│   ├── odoo-apikey-{oid_2}             ← API key Odoo de usuario 2
│   └── ...
```

**NUNCA en Key Vault:**
- Contraseñas de usuario SAP individuales
- Tokens de sesión persistidos (solo en memoria del backend, TTL corto)

---

## Control de acceso por herramienta MCP (autorización a nivel de AI)

Además de los permisos a nivel de sistema (SAP roles, Odoo ACL), el backend aplica
una capa de autorización que decide qué herramientas MCP puede invocar Claude según
el grupo Azure AD del usuario:

```json
{
  "GRP-AI-COMPRAS": ["sap://purchase-orders", "sap://goods-receipts", "odoo://purchase"],
  "GRP-AI-FINANZAS": ["sap://journal-entries", "sap://supplier-invoices", "odoo://accounting"],
  "GRP-AI-COMERCIAL": ["sap://sales-orders", "odoo://sales", "m365://send-email"],
  "GRP-AI-ADMIN":    ["*"]
}
```

Esto es una capa adicional de defensa — aunque un usuario tuviera roles SAP amplios,
el backend solo expone a Claude las herramientas que corresponden a su grupo AD.

---

## Impacto en el plan de infraestructura

| Componente | Cambio requerido | Esfuerzo estimado |
|------------|-----------------|-------------------|
| SAP IAS configuración | Basis: federar con Azure AD, crear application | 3-5 días Basis |
| SAP SOAUTH2 | Basis: activar OAuth, crear client | 1 día Basis |
| Mapeo usuarios SAP ↔ Azure AD | IT: verificar/ajustar UPN mapping | 1-2 días IT |
| App Registration Azure AD | IT: crear, configurar scopes, permisos Graph | 1 día IT |
| Backend: Token Exchange logic | Dev: implementar RFC 8693 flow | 5-7 días dev |
| Backend: autorización por grupo | Dev: leer grupos AD, aplicar policy MCP | 2-3 días dev |
| Key Vault: estructura secretos | IT: crear secretos, RBAC | 1 día IT |
| Odoo: API keys por usuario | IT + usuarios: generar y almacenar | 1 día IT + comunicación |
| Testing end-to-end | Dev + Basis: validar con usuarios piloto | 3-5 días |

**Total estimado: ~3-4 semanas (paralelo Basis + Dev)**

Este trabajo debe completarse **antes** de desplegar el MCP Hub a toda la organización.
Puede desarrollarse en paralelo con la construcción del MCP Hub.

---

## Testing y validación

Antes del go-live, validar con al menos 3 usuarios de distintos perfiles:

1. **Usuario Compras** — verificar que solo ve pedidos de compra, no asientos FI
2. **Usuario Finanzas** — verificar que ve asientos contables pero no puede leer datos de RRHH
3. **Usuario Admin** — verificar acceso completo

Para cada usuario, comparar:
- Lo que ve en **SAP GUI** con su usuario real
- Lo que devuelve la **IA** para la misma consulta

Deben ser idénticos. Si hay diferencia, hay un bug en el token mapping.
