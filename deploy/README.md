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
| Windows | `C:\ProgramData\ClaudeCode\` |
| macOS | `/Library/Application Support/ClaudeCode/` |
| Linux | `/etc/claude-code/` |

## Cómo desplegar

- **Windows (Intune / GPO):** repartir el fichero a `C:\ProgramData\ClaudeCode\`. Crear la
  carpeta si no existe. Requiere permisos de administrador local (lo aplica la política, no
  el usuario).
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
