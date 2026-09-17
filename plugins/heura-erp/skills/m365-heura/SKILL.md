---
name: m365-heura
description: Interactúa con Microsoft 365 de Heura en nombre del usuario. Úsala cuando el usuario quiera enviar emails, crear o consultar eventos de calendario, subir ficheros a OneDrive/SharePoint, enviar mensajes en Teams, o consultar sus tareas y listas de Microsoft To Do (tareas pendientes, to-dos, tasks). Gestiona el login M365 automáticamente si no hay sesión activa.
---

# M365 Heura — Email, Calendario, OneDrive, Teams y To Do

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

Sin explicar el problema ni pedir nada al usuario, ejecuta via Bash usando la ruta absoluta de Python (evita el secuestro del alias de la Microsoft Store):
```powershell
& "C:\Program Files\Python312\python.exe" C:\heura-mcp\graph_login_remote.py
```
Si esa ruta no existe, prueba con `python C:\heura-mcp\graph_login_remote.py` como fallback.

Espera a que el proceso termine (el usuario hará login en el navegador). Cuando imprima "Sesión M365 registrada", continúa.

Si `C:\heura-mcp\graph_login_remote.py` no existe, el despliegue de Intune (`intune-deploy-system.ps1`) aún no ha llegado a este equipo: indica al usuario que contacte con IT (it@heurafoods.com).

## Herramientas disponibles (vía MCP graph-heura-remote)

### Correo
- `send_email(user_email, to, subject, body, body_type, cc, attachments)` — envía un email NUEVO en nombre del usuario
  - `body_type`: "HTML" (default) o "Text"
  - `cc`: opcional, separados por coma
  - `attachments`: opcional, lista de objetos `{"share_url": "https://heurafoods.sharepoint.com/..."}` (enlace de
    SharePoint/OneDrive), `{"onedrive_path": "Documentos/Informes/informe.pdf"}` o
    `{"name": "informe.pdf", "content_base64": "..."}`. Máximo 3 MB por fichero y por correo.
- `reply_email(user_email, message_id, body, body_type, reply_all, to, cc, attachments)` — responde a un correo existente
  **sin romper el hilo** (mismo `conversationId`, `RE:` y mensaje citado debajo, como en Outlook)
  - `message_id`: id del correo original, obtenido con `list_emails`
  - `reply_all`: `true` para responder a todos; `to`/`cc` añaden destinatarios a los originales
  - **Si el usuario pide "responder", "contestar" o "seguir el hilo", usa siempre `reply_email`, nunca `send_email`.**
- `create_draft_email(...)` admite también `attachments`; `send_draft_email(user_email, draft_id)` lo envía.
- `list_emails(user_email, top, folder, only_with_attachments, search)` — lista correos para obtener su `id`
  - `folder`: `inbox` (default), `sentitems`, `drafts`...
  - `only_with_attachments`: `true` para ver solo correos con adjuntos
  - `search`: texto a buscar (asunto/remitente/cuerpo)
- `list_attachments(user_email, message_id)` — lista los adjuntos de un correo (nombre, tipo, tamaño)
- `get_attachment(user_email, message_id, attachment_id)` — descarga un adjunto (devuelve `content_base64`)

### Enviar un fichero adjunto

Orden de preferencia:
1. **Enlace de SharePoint u OneDrive** (lo normal en Heura): pide al usuario el enlace de «Copiar vínculo» y pásalo
   como `{"share_url": "<enlace>"}`. El hub lo descarga con la identidad del usuario, así que solo funciona con
   ficheros a los que él tiene acceso. Vale para bibliotecas de SharePoint, Teams y OneDrive de otros.
2. **Ruta en su OneDrive**: `{"onedrive_path": "Documentos/Informes/informe.pdf"}`.
3. **Fichero local del portátil**, solo si es pequeño (hasta unos 200 KB): el hub no ve el disco del usuario, así que
   hay que mandarlo dentro de la llamada. Lee el fichero y codifícalo en base64
   (`[Convert]::ToBase64String([IO.File]::ReadAllBytes($ruta))` en PowerShell) y pásalo como
   `{"name": "<nombre con extensión>", "content_base64": "<base64>"}`. No muestres el base64 al usuario.
   Un fichero local grande: que el usuario lo suba a SharePoint/OneDrive y use el enlace (opción 1).

Límite de Graph para adjuntos incrustados: **3 MB por fichero y por correo**. Por encima, pon el enlace en el cuerpo
del correo en lugar de adjuntar. `upload_file_to_onedrive(user_email, filename, content_base64=..., folder_path=...)`
permite subir hasta 4 MB a OneDrive cuando el fichero lo genera Claude (un informe, un CSV).

### Leer y trabajar adjuntos de un correo

1. `list_emails(user_email, only_with_attachments=true, search="...")` → localiza el correo y copia su `id`.
2. `list_attachments(user_email, message_id)` → elige el adjunto por nombre y copia su `id`.
3. `get_attachment(user_email, message_id, attachment_id)` → devuelve `content_base64`.
4. Decodifica el base64 y **escríbelo en el scratchpad** (p. ej. `factura.pdf`), luego ábrelo con `Read` o la skill correspondiente (`pdf`, `xlsx`, `docx`...) para trabajarlo.
   - No muestres el base64 al usuario; guárdalo directamente en fichero.
   - Adjuntos >10 MB devuelven error: en ese caso súbelo a OneDrive.

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

### Microsoft To Do

**Solo lectura** (el permiso concedido en Entra es `Tasks.Read`). No existen tools para crear,
completar ni borrar tareas; requerirían `Tasks.ReadWrite`.

- `list_todo_lists(user_email)` — lista las listas de tareas del usuario
  - Devuelve `id`, `displayName`, `wellknownListName`, `isOwner`, `isShared`
  - La lista por defecto es la que tiene `wellknownListName == "defaultList"`
- `list_todo_tasks(user_email, list_id, top, include_completed)` — tareas de una lista
  - `list_id`: opcional; vacío = lista por defecto
  - `top`: cuántas devolver (default 50), ordenadas por fecha de creación descendente
  - `include_completed`: `false` (default) oculta las completadas
  - Devuelve `id`, `title`, `status`, `importance`, `dueDateTime`, `createdDateTime`,
    `lastModifiedDateTime` y `body` truncado a 500 caracteres
- `get_todo_task(user_email, list_id, task_id)` — una tarea con sus subelementos (`checklistItems`)

**Aviso de sesión:** estas tools piden un scope adicional (`Tasks.Read`) que las sesiones M365
antiguas no tienen. Si devuelven `No se pudo renovar el token`, el probe de calendario del Paso 0
**no** lo detecta: hay que volver a ejecutar el login (ver "Login automático") y reintentar.

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

**Responder en el hilo con adjunto:**
> "Contesta al último correo de Sergi sobre los SKU de Planted adjuntando el Excel que hay en Documentos/Informes/skus.xlsx"
> → `list_emails(search="Planted")` para el `id`, luego `reply_email(message_id=..., body=..., attachments=[{"onedrive_path": "Documentos/Informes/skus.xlsx"}])`

> "Responde a Belén con la factura que está en este enlace de SharePoint: https://heurafoods.sharepoint.com/:b:/s/Finanzas/..."
> → `reply_email(message_id=..., body=..., attachments=[{"share_url": "https://heurafoods.sharepoint.com/:b:/s/Finanzas/..."}])`

**Calendario:**
> "Crea una reunión con ana@heurafoods.com el viernes a las 10h para revisar el cierre mensual"

**Teams:**
> "Manda un mensaje al canal General del equipo de Finanzas diciendo que el informe está listo"

**To Do:**
> "¿Qué tareas tengo pendientes en To Do?"
