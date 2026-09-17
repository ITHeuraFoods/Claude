# Heura — Marketplace de plugins para Claude Code

Marketplace interno de Heura Foods. Contiene los plugins de Claude Code que usa la organización.

## Plugins disponibles

| Plugin | Descripción |
|--------|-------------|
| `heura-erp` | Consultas en lenguaje natural a SAP S/4HANA, Odoo y M365 + dashboards. Incluye las normas de negocio internas. |
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

## Cómo accede el plugin a SAP, M365 y Odoo

Los tres ERP se consultan a través de servidores **MCP centralizados** que corren en el hub
de Heura, no ejecutando scripts en el equipo de cada persona.

| MCP | Sistema | Identidad |
|---|---|---|
| `sap-heura-remote` | SAP S/4HANA (PS4) | Cuenta de servicio |
| `graph-heura-remote` | M365: correo, calendario, Teams, OneDrive, To Do | **La de cada persona** |
| `odoo-heura-remote` | Odoo | Cuenta compartida única. Solo lectura |

Cada llamada exige un token bearer que identifica a quien pregunta, y queda registrada. El
token lo emite el hub tras un login real contra Entra: es lo que hace el acceso directo
**«Conectar M365 con Claude»** del escritorio, que solo hay que ejecutar una vez.

Ese acceso directo escribe los tres servidores, **con el token**, en el `~/.claude.json` de la
persona. El plugin **no declara servidores MCP**: una entrada sin token siempre recibe 401 del
hub y Claude Code la muestra como «Dynamic Client Registration rejected (HTTP 401)», ruido que
hace creer que SAP o M365 están caídos. Hasta la 1.4.0 el plugin llevaba un `.mcp.json` con
esas entradas; se retiró en la 1.5.0.

**El hub solo es alcanzable desde la red de Heura o con la SSL-VPN conectada.** Si los MCP
no aparecen, lo primero es comprobar la VPN; después, el diagnóstico de `deploy/`.

Documentación técnica en el repo privado
[`ITHeuraFoods/Claude-docs`](https://github.com/ITHeuraFoods/Claude-docs) (acceso: IT).

### Pendiente: identidad por usuario en SAP

Hoy SAP se consulta con una cuenta de servicio, así que los permisos que aplica son los de
esa cuenta, no los roles de cada persona. Es trabajo de mejora conocido, no un bloqueante
del despliegue. En Odoo no aplica: solo existe una cuenta. Ver
`delegated-auth-architecture.md` en el repo privado.

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
   **Obligatorio para cualquier cambio dentro del plugin**, no solo para normas: Claude Code carga el
   plugin desde su caché `~/.claude/plugins/cache/heura/<plugin>/<versión>/` y ni `autoUpdate` ni
   `/plugin update` la refrescan si la versión no cambia. La 1.4.0 estuvo del 05-08 al 17-09 con
   tres cambios de `.mcp.json` y de skill que nadie recibió.
3. `git commit` + `git push`.

Los usuarios reciben el cambio con `/plugin update` (o automáticamente si está desplegado
vía managed settings).
