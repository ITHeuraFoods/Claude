---
name: m365-heura
description: Interactúa con Microsoft 365 de Heura en nombre del usuario. Úsala cuando el usuario quiera enviar emails, leer correo o sus adjuntos, crear o consultar eventos de calendario, subir ficheros a OneDrive/SharePoint, enviar mensajes en Teams, o consultar y gestionar sus tareas y listas de Microsoft To Do (tareas pendientes, to-dos, tasks). Gestiona el login M365 si no hay sesión activa.
---

# M365 Heura — Email, Calendario, OneDrive, Teams y To Do

Esta skill conecta con Microsoft Graph API a través del MCP `graph-heura-remote` y actúa
con la identidad real del usuario (OAuth 2.0 delegado).

## Normas de seguridad (aplícalas SIEMPRE)

- **NUNCA envíes un email, mensaje de Teams o crees un evento sin confirmación explícita del usuario.**
  Muestra siempre un resumen de lo que vas a hacer y espera un "sí" o "confirma" antes de ejecutar.
- **NUNCA escribas en un fichero de OneDrive sin confirmación.**
- **NUNCA borres una tarea de To Do sin confirmación**: `delete_todo_task` es irreversible.
  Si el usuario solo quiere quitarla de en medio, usa `complete_todo_task`.

## Paso 0 — Verificar sesión (OBLIGATORIO antes de cualquier acción)

**No preguntes el email del usuario.** El hub sabe quién es por su token: ninguna tool
acepta un parámetro de usuario. Llama a `whoami()` como comprobación silenciosa y no
muestres el resultado.

- **Si devuelve el usuario** → sesión válida, procede con la acción solicitada.
- **Si el MCP responde 401 / "no autenticado" / los tools no aparecen** → falta el token
  del hub: ver *Alta en el hub* abajo.
- **Si devuelve "No hay sesión M365" o "La sesión ya no es válida"** → el token del hub es
  válido pero la sesión de Graph caducó: el usuario tiene que volver a hacer login en
  `https://mcp.heurafoods.com/auth/login`. Dile eso y espera.

### Alta en el hub

Esto solo hace falta una vez por persona (y de nuevo si caduca a los 90 días). No lo hagas
tú: son pasos que el usuario ejecuta en su navegador y en su terminal. Indícale:

1. Abre `https://mcp.heurafoods.com/auth/login` y haz login con tu cuenta de Heura.
2. La página te devuelve un comando; ejecútalo en PowerShell:
   `setx HEURA_MCP_TOKEN <token>`
3. Reinicia Claude Code.

Después vuelve a `whoami()` para confirmar. Si sigue fallando, que contacte con IT
(it@heurafoods.com).

> No hace falta VPN. El hub es accesible por internet con TLS.

## Herramientas disponibles (vía MCP graph-heura-remote)

Ninguna recibe el email del usuario: el hub lo deduce del token de la petición.

### Sesión
- `whoami()` — usuario autenticado; úsalo como comprobación de sesión

### Correo
- `send_email(to, subject, body, body_type, cc)` — envía email en nombre del usuario
  - `body_type`: "HTML" (default) o "Text"
  - `cc`: opcional, separados por coma
- `create_draft_email(to, subject, body, body_type, cc)` — crea borrador sin enviarlo; devuelve su `id`
- `send_draft_email(draft_id)` — envía un borrador creado antes
- `list_emails(top, folder, only_with_attachments, search)` — lista correos para obtener su `id`
  - `folder`: `inbox` (default), `sentitems`, `drafts`...
  - `only_with_attachments`: `true` para ver solo correos con adjuntos
  - `search`: texto a buscar (asunto/remitente/cuerpo)
- `list_attachments(message_id)` — lista los adjuntos de un correo (nombre, tipo, tamaño)
- `get_attachment(message_id, attachment_id)` — descarga un adjunto (devuelve `content_base64`)

### Leer y trabajar adjuntos de un correo

1. `list_emails(only_with_attachments=true, search="...")` → localiza el correo y copia su `id`.
2. `list_attachments(message_id)` → elige el adjunto por nombre y copia su `id`.
3. `get_attachment(message_id, attachment_id)` → devuelve `content_base64`.
4. Decodifica el base64 y **escríbelo en el scratchpad** (p. ej. `factura.pdf`), luego ábrelo con `Read` o la skill correspondiente (`pdf`, `xlsx`, `docx`...) para trabajarlo.
   - No muestres el base64 al usuario; guárdalo directamente en fichero.
   - Adjuntos >10 MB devuelven error: en ese caso súbelo a OneDrive.

### Calendario
- `list_calendar_events(days)` — lista próximos eventos (default: 7 días)
- `create_calendar_event(subject, start, end, body, attendees, location)`
  - `start` / `end`: formato ISO 8601 hora Madrid, ej: `2026-06-25T10:00:00`
  - `attendees`: emails separados por coma (opcional)

### OneDrive
- `upload_file_to_onedrive(filename, content, folder_path)`
  - `folder_path`: ruta dentro de OneDrive, ej: `Documentos/Informes` (vacío = raíz)
  - `content`: texto plano o HTML

### Teams
- `send_teams_channel_message(team_id, channel_id, message)` — post en canal
- `send_teams_chat_message(chat_id, message)` — mensaje en chat 1:1 o grupal
  - `team_id` / `channel_id` / `chat_id`: GUIDs obtenibles desde la URL de Teams

### Microsoft To Do

Lectura y escritura.

- `list_todo_lists()` — lista las listas de tareas del usuario
  - Devuelve `id`, `displayName`, `wellknownListName`, `isOwner`, `isShared`
  - La lista por defecto es la que tiene `wellknownListName == "defaultList"`
- `list_todo_tasks(list_id, top, include_completed)` — tareas de una lista
  - `list_id`: opcional; vacío = lista por defecto
  - `top`: cuántas devolver (default 50), ordenadas por fecha de creación descendente
  - `include_completed`: `false` (default) oculta las completadas
- `get_todo_task(list_id, task_id)` — una tarea con sus subelementos (`checklistItems`)
- `create_todo_task(title, list_id, due_date, body, importance)` — crea una tarea
  - `due_date`: `YYYY-MM-DD` o ISO completo; `importance`: `low` | `normal` | `high`
- `update_todo_task(list_id, task_id, title, status, due_date, body, importance)` — PATCH:
  solo cambia los campos que pases
- `complete_todo_task(list_id, task_id)` — marca como completada (**reversible**, preferible a borrar)
- `delete_todo_task(list_id, task_id, expected_title)` — **borrado definitivo, no hay papelera**
  - `expected_title` es obligatorio: el hub lee la tarea y aborta si el título no coincide

## Flujo estándar

1. `whoami()` para verificar sesión
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

**To Do:**
> "¿Qué tareas tengo pendientes en To Do?"
> "Añade una tarea para revisar el inventario el lunes"
