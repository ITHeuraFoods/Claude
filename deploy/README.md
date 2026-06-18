# Despliegue org-wide (para IT)

`managed-settings.json` de esta carpeta instala automáticamente el marketplace `heura` y
activa el plugin `heura-erp` en todos los equipos, sin que el usuario tenga que hacer nada.
Los *managed settings* tienen prioridad sobre la configuración del usuario y no se pueden
desactivar localmente.

## Ubicación destino por sistema operativo

| SO | Ruta destino |
|----|--------------|
| Windows | `C:\ProgramData\ClaudeCode\managed-settings.json` |
| macOS | `/Library/Application Support/ClaudeCode/managed-settings.json` |
| Linux | `/etc/claude-code/managed-settings.json` |

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
