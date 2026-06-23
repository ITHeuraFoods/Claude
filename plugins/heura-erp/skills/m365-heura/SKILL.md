---
name: m365-heura
description: Interactúa con Microsoft 365 de Heura en nombre del usuario. Úsala cuando el usuario quiera enviar emails, crear o consultar eventos de calendario, subir ficheros a OneDrive/SharePoint, o enviar mensajes en Teams. Gestiona el login M365 automáticamente si no hay sesión activa.
---

# M365 Heura — Email, Calendario, OneDrive y Teams

Esta skill conecta con Microsoft Graph API a través del MCP `graph-heura-remote` y actúa
con la identidad real del usuario (OAuth 2.0 delegado).

## Normas de seguridad (aplícalas SIEMPRE)

- **NUNCA envíes un email, mensaje de Teams o crees un evento sin confirmación explícita del usuario.**
  Muestra siempre un resumen de lo que vas a hacer y espera un "sí" o "confirma" antes de ejecutar.
- **NUNCA escribas en un fichero de OneDrive sin confirmación.**
- Si el usuario no ha especificado su email M365, pregúntalo antes de continuar.

## Paso 0 — Identificar al usuario y verificar sesión M365

Antes de cualquier acción necesitas el email M365 del usuario (ej: `ana@heurafoods.com`).
Si no lo has mencionado en esta sesión, pregúntalo.

### Verificación de sesión — OBLIGATORIA antes de cualquier acción

Una vez tengas el email, **llama siempre primero** a `list_calendar_events(user_email, days=0)` como probe silencioso para verificar que la sesión es válida. No muestres el resultado al usuario.

- **Si devuelve resultado (lista vacía o con eventos)** → sesión activa, procede con la acción solicitada.
- **Si devuelve error "No hay sesión M365" / "sesión M365 activa" / "Token caducado"** → ejecuta el login (ver abajo) y luego procede directamente con la acción solicitada.
- **Si el MCP `graph-heura-remote` no está disponible o los tools no aparecen** → ejecuta el login (ver abajo), luego `/mcp restart graph-heura-remote`, y procede.

### Login automático

Sin explicar el problema ni pedir nada al usuario, ejecuta via Bash:
```powershell
python C:\heura-mcp\graph_login_remote.py
```
Espera a que el proceso termine (el usuario hará login en el navegador). Cuando imprima "Sesión M365 registrada", continúa.

Si `C:\heura-mcp\graph_login_remote.py` no existe, indica al usuario que ejecute `intune_deploy_heura_m365.ps1` como Administrador.

## Herramientas disponibles (vía MCP graph-heura-remote)

### Correo
- `send_email(user_email, to, subject, body, body_type, cc)` — envía email en nombre del usuario
  - `body_type`: "HTML" (default) o "Text"
  - `cc`: opcional, separados por coma

### Calendario
- `list_calendar_events(user_email, days)` — lista próximos eventos (default: 7 días)
- `create_calendar_event(user_email, subject, start, end, body, attendees, location)`
  - `start` / `end`: formato ISO 8601 hora Madrid, ej: `2026-06-25T10:00:00`
  - `attendees`: emails separados por coma (opcional)

### OneDrive
- `upload_file_to_onedrive(user_email, filename, content, folder_path)`
  - `folder_path`: ruta dentro de OneDrive, ej: `Documentos/Informes` (vacío = raíz)
  - `content`: texto plano o HTML

### Teams
- `send_teams_channel_message(user_email, team_id, channel_id, message)` — post en canal
- `send_teams_chat_message(user_email, chat_id, message)` — mensaje en chat 1:1 o grupal
  - `team_id` / `channel_id` / `chat_id`: GUIDs obtenibles desde la URL de Teams

## Flujo estándar

1. Confirmar email del usuario
2. Entender la acción solicitada
3. **Mostrar resumen** de lo que se va a hacer (destinatarios, asunto, fechas...)
4. Esperar confirmación explícita del usuario
5. Ejecutar con el tool correspondiente
6. Confirmar resultado

## Ejemplos de uso

**Email:**
> "Envía un email a compras@heurafoods.com diciéndoles que el pedido 4500002621 está aprobado"

**Calendario:**
> "Crea una reunión con ana@heurafoods.com el viernes a las 10h para revisar el cierre mensual"

**Teams:**
> "Manda un mensaje al canal General del equipo de Finanzas diciendo que el informe está listo"
