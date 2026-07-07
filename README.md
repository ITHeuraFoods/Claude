# Heura — Marketplace de plugins para Claude Code

Marketplace interno de Heura Foods. Contiene los plugins de Claude Code que usa la organización.

## Plugins disponibles

| Plugin | Descripción |
|--------|-------------|
| `heura-erp` | Consultas en lenguaje natural a SAP S/4HANA y Odoo + dashboards. Incluye las normas de negocio internas. |
| `heura-brand` | Directrices de marca para presentaciones y documentos. Incluye `heura-brand-deck` (brand Heura 2026 en cualquier presentación `.pptx`) y `heura-brand-doc` (plantilla Word oficial de Heura para cualquier `.doc`/`.docx`). |

## Instalación (usuario individual)

```
/plugin marketplace add ITHeuraFoods/Claude
/plugin install heura-erp@heura heura-brand@heura
```

Para actualizar cuando se publiquen cambios:

```
/plugin update heura-erp@heura heura-brand@heura
```

## Prerequisito de seguridad — Autenticación delegada por usuario

> ⚠️ **OBLIGATORIO antes del despliegue org-wide.**

El MCP Hub debe autenticar cada llamada a SAP y Odoo con la identidad real del usuario,
no con una cuenta de servicio compartida. Sin esto, todos los usuarios de la IA verían
los datos con los permisos de la cuenta de servicio, ignorando los roles SAP/Odoo de
cada persona.

Ver documentación técnica completa: [`docs/delegated-auth-architecture.md`](docs/delegated-auth-architecture.md)

**Resumen de tareas (Basis + IT + Dev, ~3-4 semanas):**
- Basis: configurar SAP IAS federado con Azure AD + activar OAuth 2.0 en SAP (`SOAUTH2`)
- IT: registrar la aplicación en Azure AD con scopes Graph API
- Dev: implementar Token Exchange (RFC 8693) en el backend del MCP Hub
- IT: generar API keys Odoo por usuario y almacenarlas en Key Vault
- Dev+Basis: testing con usuarios piloto de distintos perfiles

---

## Despliegue a toda la organización (administrador)

Para que el marketplace y los plugins se instalen automáticamente en todos los equipos sin
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
    "heura-erp@heura": true,
    "heura-brand@heura": true
  }
}
```

## Cómo añadir o cambiar una norma de negocio

Las normas de comportamiento viven dentro de cada skill, en su `SKILL.md`
(p. ej. `plugins/heura-erp/skills/sap-heura/SKILL.md`, sección **Normas de negocio**;
o `plugins/heura-brand/skills/heura-brand-deck/SKILL.md` para normas de marca).

1. Edita el `SKILL.md` correspondiente.
2. Sube la versión en el `plugin.json` de su plugin (p. ej. `plugins/heura-brand/.claude-plugin/plugin.json`).
3. `git commit` + `git push`.

Los usuarios reciben el cambio con `/plugin update` (o automáticamente si está desplegado
vía managed settings).
