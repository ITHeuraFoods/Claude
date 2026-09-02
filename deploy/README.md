# Despliegue org-wide (para IT)

`managed-settings.json` de esta carpeta instala automáticamente el marketplace `heura` y
activa el plugin `heura-erp` en todos los equipos, sin que el usuario tenga que hacer nada.
Los *managed settings* tienen prioridad sobre la configuración del usuario y no se pueden
desactivar localmente.

## Ficheros a desplegar

| Fichero | Propósito |
|---------|-----------|
| `managed-settings.json` | Instala el marketplace y activa el plugin `heura-erp` |
| `intune-deploy-system.ps1` | Script SYSTEM: despliega lo anterior y limpia el login M365 antiguo |
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

- **Windows (Intune):** un único *Platform script* (Devices → Scripts and remediations):
  `intune-deploy-system.ps1` — "Run this script using the logged on credentials" = **No**
  (SYSTEM). Instala `managed-settings.json` y las fuentes, y limpia el montaje antiguo del
  login M365 (`C:\heura-mcp\` y el acceso directo del escritorio).

  Antes hacían falta dos scripts, porque el de usuario creaba un acceso directo con el
  secreto de registro incrustado en sus argumentos. El login de M365 ya se hace en el
  navegador contra el hub, así que ese script y su wrapper local se han eliminado: si
  siguen dados de alta en Intune, quítalos.

  El script se auto-relanza en 64 bits y devuelve código de salida real, así Intune
  reintenta si algo falla. **Ojo:** los platform scripts solo se re-ejecutan si cambia su
  contenido en Intune — tras corregir un script hay que volver a subirlo.
- **macOS (Jamf / MDM):** desplegar a `/Library/Application Support/ClaudeCode/`.
- **Linux (Ansible / script):** copiar a `/etc/claude-code/`.

## Verificación

Tras el despliegue, en un equipo cualquiera el usuario debería ver el plugin `heura-erp`
ya instalado y activo (las skills `sap-heura` y `odoo-heura` disponibles) sin haber ejecutado
ningún comando.

## Troubleshooting en un equipo

Comprobar en este orden:

1. `C:\ProgramData\HeuraIT\claude-deploy-system.log` — resultado del script SYSTEM.
2. Existe `C:\Program Files\ClaudeCode\managed-settings.json` — si no, el script SYSTEM no
   ha corrido o falló (ver log 1).
3. En Claude Code: `/plugin` para ver si `heura-erp@heura` está instalado y `/mcp` para el
   estado de `graph-heura-remote` y `sap-heura-remote`.

**Si falla M365 (`graph-heura-remote`):**

4. `curl.exe https://mcp.heurafoods.com/health` — estado del hub. No requiere VPN.
5. `echo %HEURA_MCP_TOKEN%` — si está vacío, el usuario no se ha dado de alta: tiene que
   abrir `https://mcp.heurafoods.com/auth/login`, ejecutar el `setx` que le devuelve la
   página y reiniciar Claude Code.
6. Si `/mcp` da 401 con el token puesto, el bearer caducó (90 días) o se revocó: mismo
   procedimiento del punto 5. Diagnóstico en el servidor con `--list-sessions`
   (ver `infra/README.md`).

**Si falla SAP (`sap-heura-remote`):** sigue en `laptop-itadm` y sigue necesitando VPN.

7. `Test-NetConnection 172.6.2.2 -Port 3001` — el MCP de SAP se alcanza por IP fija, tanto
   en la LAN de oficina como por SSL-VPN (ver `fortinet-vpn-mcp-access.md` en el repo
   privado `ITHeuraFoods/Claude-docs`). El hostname `laptop-itadm` NO resuelve en los
   laptops (solo vía Tailscale del equipo de IT); por eso el `.mcp.json` usa la IP.

## Nota

Si NO quieres forzarlo y prefieres instalación voluntaria, no despliegues este fichero; cada
usuario instala con:

```
/plugin marketplace add ITHeuraFoods/Claude
/plugin install heura-erp@heura
```
