# Despliegue org-wide (para IT)

`managed-settings.json` de esta carpeta instala automáticamente el marketplace `heura` y
activa el plugin `heura-erp` en todos los equipos, sin que el usuario tenga que hacer nada.
Los *managed settings* tienen prioridad sobre la configuración del usuario y no se pueden
desactivar localmente.

## Ficheros a desplegar

| Fichero | Propósito |
|---------|-----------|
| `managed-settings.json` | Instala el marketplace y activa el plugin `heura-erp` |
| `install-fonts.ps1` | Instala las fuentes corporativas Heura y Pixel Grafiti |
| `fonts/Heura.ttf` | Fuente custom brand (headings) — **añadir manualmente** |
| `fonts/Pixel-Grafiti.ttf` | Fuente decorativa custom — **añadir manualmente** |

> **Antes de desplegar las fuentes**: pide los archivos `.ttf` al equipo de diseño.
> Los `.woff` de heurafoods.com no son instalables como fuentes de sistema en Windows.
> Colócalos en `deploy/fonts/` y haz push al repo.

## Ubicación destino por sistema operativo

| SO | Ruta destino |
|----|--------------|
| Windows | `C:\Program Files\ClaudeCode\` |
| macOS | `/Library/Application Support/ClaudeCode/` |
| Linux | `/etc/claude-code/` |

> En Windows, la ruta legacy `C:\ProgramData\ClaudeCode\` ya no está soportada desde Claude Code v2.1.75.

## Cómo desplegar

- **Windows (Intune):** dos *Platform scripts* (Devices → Scripts and remediations):
  1. `intune-deploy-system.ps1` — "Run this script using the logged on credentials" = **No**
     (SYSTEM). Instala `managed-settings.json`, `C:\heura-mcp\graph_login_remote.py` y fuentes.
  2. `intune-wrapper-user.ps1` — "Run this script using the logged on credentials" = **Yes**.
     Es un wrapper local (gitignored, contiene el secreto de registro) que descarga y ejecuta
     `intune-deploy-user.ps1` del repo para crear el acceso directo de login M365.

  Program Files requiere permisos de administrador, por eso van en scripts separados con
  distinto contexto. Los scripts se auto-relanzan en 64 bits y devuelven código de salida
  real, así Intune reintenta si algo falla. **Ojo:** los platform scripts solo se re-ejecutan
  si cambia su contenido en Intune — tras corregir un script hay que volver a subirlo.
- **macOS (Jamf / MDM):** desplegar a `/Library/Application Support/ClaudeCode/`.
- **Linux (Ansible / script):** copiar a `/etc/claude-code/`.

## Verificación

Tras el despliegue, en un equipo cualquiera el usuario debería ver el plugin `heura-erp`
ya instalado y activo (las skills `sap-heura` y `odoo-heura` disponibles) sin haber ejecutado
ningún comando.

## Troubleshooting en un equipo

Comprobar en este orden:

1. `C:\ProgramData\HeuraIT\claude-deploy-system.log` — resultado del script SYSTEM.
2. `%LOCALAPPDATA%\HeuraIT\claude-deploy-user.log` — resultado del script de usuario.
3. Existe `C:\Program Files\ClaudeCode\managed-settings.json` — si no, el script SYSTEM no
   ha corrido o falló (ver log 1).
4. Existe `C:\heura-mcp\graph_login_remote.py` — necesario para el login M365.
5. `Test-NetConnection 172.6.2.2 -Port 3002` — el MCP hub se alcanza por IP fija, tanto en
   la LAN de oficina como por SSL-VPN (ver `docs/fortinet-vpn-mcp-access.md`). El hostname
   `laptop-itadm` NO resuelve en los laptops (solo vía Tailscale del equipo de IT); por eso
   el `.mcp.json` del plugin usa la IP.
6. En Claude Code: `/plugin` para ver si `heura-erp@heura` está instalado y `/mcp` para el
   estado de `graph-heura-remote` y `sap-heura-remote`.

## Nota

Si NO quieres forzarlo y prefieres instalación voluntaria, no despliegues este fichero; cada
usuario instala con:

```
/plugin marketplace add ITHeuraFoods/Claude
/plugin install heura-erp@heura
```
