# Acceso al MCP Hub vía SSL-VPN (FortiGate)

**Estado:** Configurado y verificado (2026-07-02)
**Firewall:** FW-ES-HHQ-02 (FortiGate, gestionado vía FortiGate Cloud)
**Responsable técnico:** IT

---

## Objetivo

Permitir que los clientes SSL-VPN de Heura (conexión desde casa/fuera de oficina)
accedan al servidor MCP que conecta Claude con SAP y M365, alojado en `laptop-itadm`.

## Servidor MCP

| Campo      | Valor                                      |
|------------|---------------------------------------------|
| Hostname   | laptop-itadm                                |
| IP interna | `172.6.2.2`                                 |
| Interfaz   | `WIFI_HEURA (port3)`                        |
| Puertos    | 3001 (SAP), 3002 (Graph/M365), 3003 (register endpoint) |

## Configuración aplicada en el FortiGate

### 1. Objetos de firewall

- **Address** `MCP-Server-host`: subnet `172.6.2.2/32`, interface `any`
- **Address** `SSLVPN-Pool-Manual`: IP Range `10.212.134.2-10.212.134.250` (rango del pool SSL-VPN)
- **Service** `MCP-Ports`: TCP `3001-3003`

### 2. Split tunneling

`VPN → SSL-VPN Settings` → portal → **Split Tunneling** habilitado → `Routing Address`
incluye `172.6.2.2/32` (objeto `MCP-Server-host`). Sin esto, el tráfico hacia el MCP
ni siquiera entra por el túnel.

### 3. Política de firewall `MCP IA`

| Campo               | Valor                                  |
|---------------------|------------------------------------------|
| Incoming Interface  | `SSL-VPN tunnel interface (ssl.root)`     |
| Outgoing Interface  | `WIFI_HEURA (port3)`                      |
| Source (address)    | `SSLVPN_TUNNEL_ADDR1` / `SSLVPN-Pool-Manual` |
| Source (user/group) | `saml_azure` (ver nota abajo)             |
| Destination         | `MCP-Server-host`                         |
| Service             | `MCP-Ports`                               |
| Action              | ACCEPT                                    |
| NAT                 | Desactivado                               |

**Nota importante — grupo de usuario:** toda política con Incoming Interface = `ssl.root`
exige un user/group en Source (no se puede omitir). El grupo `SSL-VPN-HEURA` contiene
solo usuarios **locales** (ej. `enaitz.semperena`), que no coinciden con la identidad real
de una sesión autenticada por SSO/SAML de Azure (ej. `enaitz.s@heurafoods.com`,
`Authentication Server: azure`). Usar `SSL-VPN-HEURA` como grupo de origen provoca que el
tráfico se deniegue (`implicit_deny`) aunque el resto de la política sea correcta.

El grupo correcto para sesiones SSO es **`saml_azure`** (Firewall group con Remote Group
apuntando al servidor SAML de Azure). Cualquier política nueva que dependa de sesiones
SSL-VPN de Heura debe usar `saml_azure`, no `SSL-VPN-HEURA`.

### 4. Firewall de Windows en `laptop-itadm`

Regla de entrada permitiendo el tráfico VPN hacia los puertos del MCP:

```powershell
New-NetFirewallRule -DisplayName "MCP-Ports-VPN" -Direction Inbound -Protocol TCP `
  -LocalPort 3001-3003 -RemoteAddress 10.212.134.0/24 -Action Allow
```

Los servicios deben escuchar en `0.0.0.0`, no en `127.0.0.1`, para aceptar conexiones
desde fuera del propio host (verificado con `netstat -ano`).

## Verificación

Desde fuera de la red de Heura, con la VPN conectada:

```powershell
Test-NetConnection 172.6.2.2 -Port 3001
Test-NetConnection 172.6.2.2 -Port 3002
Test-NetConnection 172.6.2.2 -Port 3003
```

`TcpTestSucceeded : True` en los tres confirma acceso correcto.

## Diagnóstico usado

- **Policy Match Tool** (GUI, junto a "Create new" en Firewall Policy): simula un paquete
  contra las políticas existentes. Limitación: no valida pertenencia a grupos de usuario,
  así que puede mostrar `implicit_deny` incluso cuando el tráfico real sí lo cumpliría.
- **Log & Report → Forward Traffic**: filtrar por `dstip` y `dstport` para ver la entrada
  real del intento de conexión, incluyendo el campo `User` y `Authentication Server` —
  clave para diagnosticar el problema de grupo SAML vs. usuario local.
