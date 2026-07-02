# Despliegue org-wide (para IT)

`managed-settings.json` de esta carpeta instala automáticamente el marketplace `heura` y
activa el plugin `heura-erp` en todos los equipos, sin que el usuario tenga que hacer nada.
Los *managed settings* tienen prioridad sobre la configuración del usuario y no se pueden
desactivar localmente.

## Ficheros a desplegar

| Fichero | Propósito |
|---------|-----------|
| `managed-settings.json` | Instala el marketplace y activa el plugin `heura-erp` |
| `managed-mcp.json` | Registra los servidores MCP (SAP y M365) en todos los equipos |
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

- **Windows (Intune):** usar `intune-deploy-system.ps1` (contexto SYSTEM, "Run as logged on
  user = No") para `managed-settings.json`/`managed-mcp.json`/fuentes, e
  `intune-deploy-user.ps1` (contexto de usuario) para el login M365. Program Files requiere
  permisos de administrador, por eso van en scripts separados con distinto contexto.
- **macOS (Jamf / MDM):** desplegar a `/Library/Application Support/ClaudeCode/`.
- **Linux (Ansible / script):** copiar a `/etc/claude-code/`.

## Verificación

Tras el despliegue, en un equipo cualquiera el usuario debería ver el plugin `heura-erp`
ya instalado y activo (las skills `sap-heura` y `odoo-heura` disponibles) sin haber ejecutado
ningún comando.

## Nota

Si NO quieres forzarlo y prefieres instalación voluntaria, no despliegues este fichero; cada
usuario instala con:

```
/plugin marketplace add ITHeuraFoods/Claude
/plugin install heura-erp@heura
```
