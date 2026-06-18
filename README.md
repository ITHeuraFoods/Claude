# Heura — Marketplace de plugins para Claude Code

Marketplace interno de Heura Foods. Contiene los plugins de Claude Code que usa la organización.

## Plugins disponibles

| Plugin | Descripción |
|--------|-------------|
| `heura-erp` | Consultas en lenguaje natural a SAP S/4HANA y Odoo + dashboards. Incluye las normas de negocio internas. |

## Instalación (usuario individual)

```
/plugin marketplace add ITHeuraFoods/Claude
/plugin install heura-erp@heura
```

Para actualizar cuando se publiquen cambios:

```
/plugin update heura-erp@heura
```

## Despliegue a toda la organización (administrador)

Para que el marketplace y el plugin se instalen automáticamente en todos los equipos sin
acción del usuario, añade esto a los *managed settings* de la organización
(en Windows: `C:\ProgramData\ClaudeCode\managed-settings.json`):

```json
{
  "extraKnownMarketplaces": {
    "heura": {
      "source": {
        "source": "github",
        "repo": "ITHeuraFoods/Claude"
      }
    }
  },
  "enabledPlugins": {
    "heura-erp@heura": true
  }
}
```

## Cómo añadir o cambiar una norma de negocio

Las normas de comportamiento viven dentro de cada skill, en su `SKILL.md`
(p. ej. `plugins/heura-erp/skills/sap-heura/SKILL.md`, sección **Normas de negocio**).

1. Edita el `SKILL.md` correspondiente.
2. Sube la versión en `plugins/heura-erp/.claude-plugin/plugin.json` y en
   `.claude-plugin/marketplace.json`.
3. `git commit` + `git push`.

Los usuarios reciben el cambio con `/plugin update` (o automáticamente si está desplegado
vía managed settings).
