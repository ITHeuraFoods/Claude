# MCP Hub — despliegue del MCP de M365

Aprovisionamiento del servidor que aloja `graph-heura-remote`, el MCP de Microsoft 365.
Sustituye al montaje que corría en `laptop-itadm`.

Contenido de esta carpeta:

| Fichero | Qué es |
|---------|--------|
| `cloud-init.yaml` | Arranque de la VM: paquetes, usuarios, Caddy, venv, unidad systemd |
| `requirements.txt` | Dependencias **fijadas** con las que se validó el servidor |
| `systemd/heura-graph-mcp.service` | Unidad del servicio, con endurecimiento |
| `Caddyfile` | Reverse proxy y TLS automático |

---

## 0 · Elección de proveedor

Nada del diseño es específico de un proveedor: es una VM Linux con `systemd`, Caddy y
configuración por variables de entorno. `cloud-init.yaml` vale igual en los tres. Lo que
cambia es el firewall, el sitio donde vive el secreto y la factura.

| | **Hetzner** | **AWS** | **Azure** |
|---|---|---|---|
| Máquina equivalente | CX22 (2 vCPU / 4 GB) | t4g.small (2 vCPU ARM / 2 GB) | B2ats v2 |
| Coste orientativo | ~5 €/mes | ~20-30 €/mes | ~20-35 €/mes |
| Región más cercana | Falkenstein / Núremberg (DE) | **eu-south-2 (Zaragoza)** | **Spain Central** |
| Firewall | Cloud Firewall | Security Group | NSG |
| Secreto del cliente | fichero + `LoadCredential` | Secrets Manager | **Key Vault + managed identity** |
| VPN a SAP (Fase 4) | strongSwan a mano en la VM | **Site-to-Site gestionada** | **VPN Gateway gestionada** |

Tres cosas a tener en cuenta al decidir:

- **Hetzner es 4-6x más barato** y de sobra para esta carga: son servicios de E/S, no de
  CPU. Si el criterio es coste y simplicidad, es la opción.
- **AWS y Azure tienen región en España.** Hetzner no. Da igual para M365 (Graph es SaaS
  y se sale a internet en cualquier caso), pero **sí importa en la Fase 4**, cuando el hub
  tenga que hablar con SAP en `10.3.2.48` a través de un túnel: desde Alemania se añaden
  25-35 ms a cada consulta OData. Y en las dos la VPN site-to-site es servicio gestionado,
  frente a operar strongSwan en la VM.
- **Azure es la opción más coherente con lo que ya teníamos escrito.** El
  `delegated-auth-architecture.md` del repo privado ya asume Azure App Service y Key Vault
  para este backend. Siendo un tenant M365/Entra, Azure permite además guardar el client
  secret en Key Vault con managed identity, sin credenciales que rotar a mano — que es el
  único punto de este despliegue que sigue siendo manual.

**Recomendación:** si esto es la Fase 2 y SAP vendrá detrás, ir directamente a Azure
(Spain Central) ahorra migrar dos veces y elimina el manejo manual del secreto. Si se
quiere validar rápido y barato, Hetzner y ya se decide en la Fase 4. En ambos casos los
ficheros de esta carpeta son los mismos.

---

## 1 · App Registration en Entra ID

Sin esto el servicio no arranca. Azure Portal → Microsoft Entra ID → App registrations →
New registration:

| Campo | Valor |
|-------|-------|
| Name | `Heura MCP Hub (M365)` |
| Supported account types | Accounts in this organizational directory only |
| Redirect URI | **Web** → `https://mcp.heurafoods.com/auth/callback` |

Después, dentro de la aplicación:

1. **Certificates & secrets → New client secret** (24 meses). Copia el *Value* — solo se
   muestra una vez. Va al paso 4; apúntalo también en el gestor de contraseñas de IT con
   la fecha de caducidad, porque cuando expire el servicio deja de poder renovar tokens.
2. **API permissions → Add a permission → Microsoft Graph → Delegated permissions**, y
   añade exactamente estos:
   `Mail.Send`, `Mail.ReadWrite`, `Calendars.ReadWrite`, `Files.ReadWrite.All`,
   `Chat.ReadWrite`, `ChannelMessage.Send`, `Tasks.ReadWrite`, `User.Read`.
3. **Grant admin consent for Heura Foods.** Recomendado: sin esto cada usuario ve una
   pantalla de consentimiento en su primer login, y `Chat.ReadWrite` y
   `ChannelMessage.Send` la exigen de todas formas.
4. Copia el **Application (client) ID** de la página Overview → va a `cloud-init.yaml`.

> Es un App Registration **nuevo**, no el que usaba `graph_login_remote.py`. Eso implica
> que todo el mundo se loguea de cero, y es justamente lo que permite consolidar los
> scopes en un solo juego (ver la cabecera de `scripts/graph_mcp_server.py`).

---

## 2 · DNS

Registro `A` (y `AAAA` si la VM tiene IPv6) de `mcp.heurafoods.com` a la IP pública.
Créalo **antes** de arrancar Caddy: el certificado de Let's Encrypt se emite validando
ese nombre, y si no resuelve, Caddy entra en reintentos con backoff.

Esto es lo que retira definitivamente la IP fija `172.6.2.2` del `.mcp.json`.

---

## 3 · Crear la VM

Coge `cloud-init.yaml`, sustituye los tres marcadores (`MCP_HOSTNAME`, `ENTRA_CLIENT_ID`,
`ADMIN_SSH_KEY`) y pégalo en el campo de datos de usuario del proveedor: *Cloud config*
en Hetzner, *User data* en AWS, *custom_data* en Azure. Imagen: Debian 12 o Ubuntu 24.04.

**Firewall** — según lo decidido, el 443 va abierto a internet, que es lo que quita el
requisito de VPN a los usuarios:

| Puerto | Origen | Motivo |
|--------|--------|--------|
| 443/tcp | `0.0.0.0/0`, `::/0` | El hub |
| 80/tcp | `0.0.0.0/0`, `::/0` | Solo el reto ACME de Let's Encrypt |
| 22/tcp | **red de IT / Tailscale únicamente** | Administración |

Nada de SSH abierto al mundo en la máquina que guarda los refresh tokens de M365. Lo
suyo es instalar Tailscale en la VM y cerrar el 22 del todo en el firewall del proveedor.

El servicio escucha en `127.0.0.1:3002`, no en `0.0.0.0`: el único proceso que acepta
conexiones de fuera es Caddy. Esto es lo contrario de lo que hacía el montaje anterior
en el portátil, donde los tres puertos escuchaban en `0.0.0.0` sin TLS.

---

## 4 · El secreto y el arranque

`cloud-init` deja el servicio instalado y habilitado pero **sin arrancar**, porque sin el
client secret aborta. Por SSH:

```bash
sudo install -m 600 -o root -g root /dev/null /etc/heura-mcp/entra-client-secret
sudo tee /etc/heura-mcp/entra-client-secret >/dev/null   # pega el secreto, Ctrl-D
sudo systemctl start heura-graph-mcp
```

El secreto no va en `cloud-init.yaml` (queda legible en los metadatos de la instancia) ni
en `graph.env` (acabaría en `/proc/<pid>/environ`). systemd lo entrega por
`LoadCredential=` a un tmpfs que solo lee este servicio, y el servidor lo lee por
`HEURA_ENTRA_CLIENT_SECRET_FILE`.

---

## 5 · Verificación

```bash
curl -s https://mcp.heurafoods.com/health
# {"status":"ok","service":"graph-heura","sessions":0,"state_writable":true}

# El endpoint MCP tiene que rechazar a quien no presente bearer:
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://mcp.heurafoods.com/graph/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# 401   ← si sale 200, PARA: el servicio está sin autenticación
```

Ese 401 es la comprobación más importante del despliegue. Es exactamente el agujero que
tenía la versión anterior, donde cualquiera que alcanzase el puerto 3002 podía enviar
correo en nombre de otro.

Configura además un chequeo externo sobre `/health` con aviso a Teams. Hoy no hay ninguno:
nadie se enteraba de que el hub estaba caído hasta que un usuario se quejaba.

---

## 6 · Onboarding de un usuario

1. Abre `https://mcp.heurafoods.com/auth/login` en el navegador.
2. Login M365 normal.
3. La página de vuelta da un token y el comando para guardarlo:
   `setx HEURA_MCP_TOKEN <token>` en Windows.
4. Reiniciar Claude Code.

Se muestra una sola vez. Si se pierde o se filtra, se vuelve a hacer login: emitir un
bearer nuevo invalida el anterior del mismo usuario.

---

## 7 · Operación

```bash
# Log de auditoría (una línea JSON por evento)
journalctl -u heura-graph-mcp -f
journalctl -u heura-graph-mcp --since today | jq 'select(.event=="tool")'

# Censo de sesiones
sudo -u heura-mcp /opt/heura-mcp/venv/bin/python \
  /opt/heura-mcp/scripts/graph_mcp_server.py --list-sessions

# Cortar el acceso de alguien (baja, portátil robado): borra su bearer y su caché
sudo -u heura-mcp /opt/heura-mcp/venv/bin/python \
  /opt/heura-mcp/scripts/graph_mcp_server.py --revoke persona@heurafoods.com

# Actualizar el código
sudo git -C /opt/heura-mcp pull
sudo /opt/heura-mcp/venv/bin/pip install -r /opt/heura-mcp/infra/requirements.txt
sudo systemctl restart heura-graph-mcp
```

Reiniciar el servicio **no** corta a los clientes conectados: el servidor va con
`stateless_http`, así que no hay sesión MCP en memoria que se invalide.

Copias de seguridad: snapshot diario de la VM. El único estado es `/var/lib/heura-mcp`;
si se pierde, nadie pierde datos — todo el mundo tiene que volver a hacer login.

---

## 8 · Lo que sigue siendo mejorable

Honestamente, y para que no se venda como resuelto lo que no lo está:

- **Cifrado en reposo.** Los ficheros van `0600` dentro de un directorio `0700` y el
  servicio corre con un usuario dedicado y `ProtectSystem=strict`. Pero el disco de la VM
  no está cifrado: quien acceda al disco o a un snapshot lee los refresh tokens. Se
  arregla montando `/var/lib/heura-mcp` en un volumen LUKS, o en Azure con
  discos cifrados. No se ha hecho cifrado a nivel de aplicación a propósito: mueve el
  problema a dónde guardar la clave, y la Fase 3 elimina el almacén entero.
- **El bearer se copia a mano.** Es la friccion que quedaría resuelta con OAuth nativo de
  MCP, pero Entra ID no soporta Dynamic Client Registration y el comportamiento de Claude
  Code en ese caso no está verificado. No merece bloquear la migración por esto.
- **Fase 3 — identidad delegada.** El punto de extensión ya está aislado: sustituir la
  clase `HeuraTokenVerifier` por una que valide un JWT de Entra contra el JWKS del tenant
  y saque el usuario de `upn`/`oid` no toca ni una tool. Eso elimina los bearers propios y
  el almacén de cachés MSAL, y es prerequisito del MCP de SAP. Ver
  `delegated-auth-architecture.md` en `ITHeuraFoods/Claude-docs`.
- **Una sola instancia.** Suficiente para la carga actual. `stateless_http` ya permite
  replicar sin afinidad de sesión, pero `bearers.json` en disco local tendría que pasar a
  un almacén compartido antes de poner dos.
