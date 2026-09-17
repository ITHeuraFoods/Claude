# Despliegue org-wide (para IT)

`managed-settings.json` de esta carpeta instala automáticamente el marketplace `heura` y
activa el plugin `heura-erp` en todos los equipos, sin que el usuario tenga que hacer nada.
Los *managed settings* tienen prioridad sobre la configuración del usuario y no se pueden
desactivar localmente.

## Ficheros a desplegar

| Fichero | Propósito |
|---------|-----------|
| `managed-settings.json` | Instala el marketplace y activa el plugin `heura-erp` |
| `intune-deploy-system.ps1` | Script SYSTEM: `managed-settings.json`, `C:\heura-mcp\graph_login_remote.py` y fuentes |
| `intune-deploy-user.ps1` | Script de usuario: acceso directo de login, dependencias de Python, refresco del marketplace y alta de MCP nuevos |
| `intune-wrapper-user.ps1` | Envoltorio local del anterior. **Gitignored: lleva el secreto de registro** |
| `diagnostico-mcp.ps1` | Diagnóstico de «no me aparecen los MCP». Solo lee, no cambia nada |
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

## Diagnóstico de toda la flota (Intune Platform script)

Sin licencia de Remediations, un platform script solo devuelve a Intune éxito o fallo por equipo.
`intune-diag-user.ps1` aprovecha las dos vías:

- **Exit 1 si hay algo que arreglar** → en Intune (Devices → Scripts → el script → Device status)
  la lista de equipos «Failed» es la lista de equipos con problemas. No cambia nada en el equipo.
- **Envía su línea de estado al hub** (`POST http://mcp.heurafoods.com:3003/diag`, con el secreto de
  registro) cuando lo alcanza. El hub la guarda en `/var/lib/heura-mcp/diag/equipos.tsv`; la última
  línea de cada equipo es la que vale:

  ```bash
  ssh srv-mcp "sudo sort -t\$'\t' -k2,2 -k1,1 /var/lib/heura-mcp/diag/equipos.tsv | awk -F'\t' '{u[\$2]=\$0} END{for(k in u) print u[k]}' | sort -k4"
  ```
- También deja la línea en `%LOCALAPPDATA%\HeuraIT\claude-diag.log` del equipo.

Formato: `EQUIPO usuario | plugin=1.5.1 mcp-con-token=3/3 hub-alcanzable=3/3 | OK` o
`... | KO: sin-login-m365 plugin-cache-vieja(1.4.0<1.5.1)`.

Despliegue: como el script de usuario, con un wrapper local que lleva el secreto (gitignored):
`intune-wrapper-diag.ps1` → Platform scripts, «Run this script using the logged on credentials» = **Yes**,
64 bits = **Yes**. Los platform scripts se ejecutan **una vez** por equipo (y reintentan los fallidos 3
veces): para repetir el diagnóstico hay que volver a subir el script con algún cambio.

`intune-detect-mcp.ps1` es la misma detección en formato Remediations, por si algún día hay licencia.

Códigos KO: `sin-managed-settings`, `policy-sin-heura-erp`, `marketplace-no-clonado`,
`plugin-no-instalado`, `plugin-cache-vieja(instalada<marketplace)`, `claude-nunca-abierto`,
`sin-login-m365` (no ha ejecutado el acceso directo), `faltan-mcp(...)`, `sin-acceso-directo`,
`sin-python`, `python-roto`, `python-sin-msal`. `hub-alcanzable` es informativo: sin VPN da 0/3.

## Verificación

En un equipo cualquiera, el usuario debería ver el plugin `heura-erp` instalado y activo
(skills `sap-heura`, `odoo-heura` y `m365-heura`) sin haber ejecutado ningún comando.

Para que además funcionen los MCP hace falta que la persona haya ejecutado **una vez** el
acceso directo «Conectar M365 con Claude» del escritorio: es lo que obtiene su token. Quien
ya lo hizo no tiene que repetirlo cuando se añade un MCP nuevo — el script de usuario copia
su token a la entrada nueva.

```powershell
Test-NetConnection mcp.heurafoods.com -Port 3001   # SAP
Test-NetConnection mcp.heurafoods.com -Port 3002   # M365
Test-NetConnection mcp.heurafoods.com -Port 3004   # Odoo
```

**El hub solo se alcanza desde la red de Heura o con la SSL-VPN conectada.** Si fallan los
tres, es la VPN. Si falla solo uno, es el hub: avisar a IT.

## Troubleshooting en un equipo

Comprobar en este orden:

1. `C:\ProgramData\HeuraIT\claude-deploy-system.log` — resultado del script SYSTEM.
2. `%LOCALAPPDATA%\HeuraIT\claude-deploy-user.log` — resultado del script de usuario.
3. Existe `C:\Program Files\ClaudeCode\managed-settings.json` — si no, el script SYSTEM no
   ha corrido o falló (ver log 1).
4. Existe `C:\heura-mcp\graph_login_remote.py` — necesario para el login M365.
5. `~/.claude.json` tiene los servidores **con token**. Es el fichero que Claude Code lee de
   verdad para los MCP de ámbito usuario; un bloque `mcpServers` en `~/.claude/settings.json`
   se queda inerte.
6. `Test-NetConnection mcp.heurafoods.com -Port 3002` — con VPN o en la oficina.
7. Python 3.12 en `C:\Program Files\Python312` con `msal` y `requests`. Si falta
   `Lib\os.py`, la instalación está rota y el síntoma engaña: `ModuleNotFoundError: No
   module named 'encodings'`, que no tiene nada que ver con las dependencias. Se arregla con
   Aplicaciones → Python 3.12 → Modificar → Repair.
8. En Claude Code: `/plugin` para ver si `heura-erp@heura` está instalado.
9. La versión instalada es la del marketplace: `version` de `heura-erp@heura` en
   `~/.claude/plugins/installed_plugins.json` frente a `plugins/heura-erp/.claude-plugin/plugin.json`
   del clon. Claude Code carga el plugin desde `~/.claude/plugins/cache/heura/heura-erp/<versión>/`,
   no desde el clon: refrescar el clon (lo que hace el script de usuario) no sirve de nada si la
   versión no ha subido. Arreglo: `/plugin update heura-erp@heura` y cerrar/abrir Claude.

**Atajo: `deploy/diagnostico-mcp.ps1` comprueba los nueve puntos de golpe** y dice qué hacer,
en orden. Solo lee:

```powershell
irm https://raw.githubusercontent.com/ITHeuraFoods/Claude/main/deploy/diagnostico-mcp.ps1 | iex
```

Tras cualquier arreglo hay que **cerrar Claude del todo y volver a abrirlo**: la
configuración de MCP se lee al arrancar.

## Nota

Si NO quieres forzarlo y prefieres instalación voluntaria, no despliegues este fichero; cada
usuario instala con:

```
/plugin marketplace add ITHeuraFoods/Claude
/plugin install heura-erp@heura
```
