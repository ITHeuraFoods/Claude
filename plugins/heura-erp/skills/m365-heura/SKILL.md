---
name: m365-heura
description: Interactúa con Microsoft 365 de Heura en nombre del usuario. Úsala cuando el usuario quiera leer, buscar, enviar, responder, reenviar, mover o programar correos (con adjuntos), gestionar su calendario (crear, modificar, cancelar, responder invitaciones, ver disponibilidad, salas, Teams, fuera de oficina), leer o escribir chats y canales de Teams, trabajar con ficheros de OneDrive o SharePoint, buscar personas de Heura, o gestionar sus tareas de Microsoft To Do. Gestiona el login M365 automáticamente si no hay sesión activa.
---

# M365 Heura — Correo, Calendario, Teams, OneDrive/SharePoint, Personas y To Do

Esta skill conecta con Microsoft Graph API a través del MCP `graph-heura-remote` y actúa
con la identidad real del usuario (OAuth 2.0 delegado). Las horas se expresan siempre en
**hora de Madrid** (ISO 8601, ej. `2026-09-25T10:00:00`).

## Normas de seguridad (aplícalas SIEMPRE)

- **NUNCA envíes un email o mensaje de Teams, ni crees, modifiques o canceles un evento, ni
  respondas a una invitación, ni muevas o borres correo sin confirmación explícita del usuario.**
  Muestra un resumen de lo que vas a hacer y espera un "sí" o "confirma".
- **NUNCA escribas en OneDrive o SharePoint sin confirmación.**
- Si el usuario duda entre enviar y revisar, usa `create_draft_email`: él lo revisa en Outlook.
- Si el usuario no ha especificado su email M365, pregúntalo antes de continuar.

## Paso 0 — Identificar al usuario y verificar sesión M365

Antes de cualquier acción necesitas el email M365 del usuario (ej: `ana@heurafoods.com`).
Si no lo has mencionado en esta sesión, pregúntalo.

### Verificación de sesión — OBLIGATORIA antes de cualquier acción

Una vez tengas el email, **llama siempre primero** a `list_calendar_events(user_email, days=0)` como probe silencioso. No muestres el resultado al usuario.

- **Si devuelve resultado (lista vacía o con eventos)** → sesión activa, procede.
- **Si devuelve error "No hay sesión M365" / "Token caducado"** → ejecuta el login (ver abajo) y procede.
- **Si el MCP `graph-heura-remote` no está disponible o los tools no aparecen** → ejecuta el login, luego `/mcp restart graph-heura-remote`, y procede.
- **Si una tool concreta devuelve "Esta funcion necesita permisos que la sesion M365 ... no tiene"** →
  ejecuta el login y reintenta esa tool. No hace falta reiniciar Claude: desde la 1.6.0 volver a
  loguearse no invalida el token anterior. Si tras el login sigue fallando, IT tiene que conceder
  esos permisos en Entra: díselo al usuario.

### Login automático

Sin explicar el problema ni pedir nada al usuario, ejecuta via Bash usando la ruta absoluta de Python (evita el secuestro del alias de la Microsoft Store):
```powershell
& "C:\Program Files\Python312\python.exe" C:\heura-mcp\graph_login_remote.py
```
Si esa ruta no existe, prueba con `python C:\heura-mcp\graph_login_remote.py` como fallback.
Con `--rotar` invalida los tokens anteriores del usuario (solo si sospecha que se ha filtrado).

Espera a que el proceso termine (el usuario hará login en el navegador). Cuando imprima "Sesion registrada", continúa.

Si `C:\heura-mcp\graph_login_remote.py` no existe, el despliegue de Intune aún no ha llegado a este equipo: indica al usuario que contacte con IT (it@heurafoods.com).

## Herramientas disponibles (vía MCP graph-heura-remote)

### Correo: leer y buscar
- `list_emails(user_email, top, folder, only_with_attachments, search, from_address, since, until, unread_only)`
  - `folder`: `inbox` (default), `sentitems`, `drafts`, `archive`, `deleteditems`, un nombre tal como se ve en
    Outlook (`Proveedores`) o un id. `list_folders(user_email)` da la lista con contadores.
  - `from_address`: email exacto del remitente; `since`/`until`: `YYYY-MM-DD` o ISO Madrid
  - `search`: texto libre; con `search`, los demás filtros se aplican después sobre los resultados
  - Devuelve `id`, `subject`, `from`, `to`, `receivedDateTime`, `hasAttachments`, `isRead`, `bodyPreview`, `conversationId`, `webLink`
- `get_email(user_email, message_id, as_text)` — el correo completo con cuerpo (texto plano por defecto). Léelo antes de responder.
- `list_attachments(user_email, message_id)` y `get_attachment(user_email, message_id, attachment_id)` — adjuntos (ver abajo)

### Correo: enviar, responder, reenviar
- `send_email(user_email, to, subject, body, body_type, cc, bcc, attachments, send_at)` — email **nuevo**
- `reply_email(user_email, message_id, body, body_type, reply_all, to, cc, bcc, attachments, send_at)` — responde
  **sin romper el hilo** (mismo `conversationId`, `RE:` y original citado). **Si el usuario dice "responder",
  "contestar" o "seguir el hilo", usa siempre `reply_email`, nunca `send_email`.** `to`/`cc`/`bcc` añaden
  destinatarios a los originales.
- `forward_email(user_email, message_id, to, comment, body_type, cc, bcc, attachments, send_at)` — reenvía
  **conservando los adjuntos originales** (`RV:`); `comment` va encima del mensaje reenviado
- `create_draft_email(user_email, to, subject, body, body_type, cc, bcc, attachments, send_at)` — borrador en
  Outlook para que el usuario lo revise; devuelve `id` y `webLink`. `send_draft_email(user_email, draft_id)` lo envía.
- Comunes: `body_type` "HTML" (default) o "Text"; `cc`/`bcc` separados por coma; `send_at` = **envío programado**
  (hora Madrid ISO): Exchange retiene el correo y lo envía a esa hora aunque Claude ya no esté abierto.

### Correo: organizar
- `move_email(user_email, message_id, folder)` — mover; `folder="archive"` archiva, `"deleteditems"` elimina
- `mark_email(user_email, message_id, is_read, categories, flag, importance)` — leído/no leído, categorías
  (lista de nombres; `[]` las quita), `flag` (`flagged`/`complete`/`notFlagged`), `importance` (`low`/`normal`/`high`)
- `list_categories(user_email)` — categorías de Outlook definidas por el usuario

### Adjuntos: enviar un fichero

`attachments` es una lista de objetos, cada uno con UNA de estas formas, en orden de preferencia:
1. **Enlace de SharePoint u OneDrive** (lo normal en Heura): pide al usuario el enlace de «Copiar vínculo» y pásalo
   como `{"share_url": "<enlace>"}`. El hub lo descarga con la identidad del usuario: solo ficheros a los que tiene acceso.
2. **Ruta en su OneDrive**: `{"onedrive_path": "Documentos/Informes/informe.pdf"}`. Si el fichero está en
   Escritorio o Documentos y el equipo sincroniza esas carpetas con OneDrive, esta ruta ya sirve.
3. **Fichero local del portátil**, solo si es pequeño (hasta unos 200 KB): el hub no ve el disco del usuario, así
   que hay que mandarlo dentro de la llamada. Codifícalo en base64
   (`[Convert]::ToBase64String([IO.File]::ReadAllBytes($ruta))` en PowerShell) y pásalo como
   `{"name": "<nombre con extensión>", "content_base64": "<base64>"}`. No muestres el base64 al usuario.
   Fichero local grande: que el usuario lo suba a SharePoint/OneDrive y use el enlace (opción 1).

Límites: hasta **3 MB** el adjunto va incrustado; hasta **150 MB** el hub lo sube por trozos (el correo se crea
como borrador, se adjunta y se envía; tarda más). Para ficheros generados por Claude (informes, CSV),
`upload_file_to_onedrive` (hasta 150 MB) y luego `onedrive_path`.

### Adjuntos: leer los de un correo

1. `list_emails(user_email, only_with_attachments=true, search="...")` → `id` del correo.
2. `list_attachments(user_email, message_id)` → `id` del adjunto.
3. `get_attachment(user_email, message_id, attachment_id)` → `content_base64`.
4. Decodifica y **escríbelo en el scratchpad**, luego ábrelo con `Read` o la skill que toque (`pdf`, `xlsx`, `docx`).
   No muestres el base64 al usuario. Adjuntos >10 MB: pide al usuario el enlace de SharePoint y usa `download_file`.

### Calendario
- `list_calendar_events(user_email, days, start, until, top)` — eventos con `id`, `joinUrl` de Teams, asistentes y su respuesta, `my_response`
- `create_calendar_event(user_email, subject, start, end, body, attendees, location, optional_attendees, room, is_online_meeting, recurrence, reminder_minutes, all_day)`
  - `room`: email de la sala (de `list_rooms`); se reserva y se pone como ubicación
  - `is_online_meeting: true` añade el enlace de Teams
  - `recurrence`: `{"type": "weekly", "interval": 1, "days_of_week": ["monday"], "until": "2026-12-31"}` o
    `{"type": "monthly", "day_of_month": 1, "count": 6}` (`type`: daily/weekly/monthly; `until` o `count`; sin ambos, sin fin)
- `update_calendar_event(user_email, event_id, subject, start, end, body, location, attendees, optional_attendees, room, is_online_meeting, reminder_minutes)` — solo cambia lo que se pasa; `attendees` **sustituye** la lista
- `cancel_calendar_event(user_email, event_id, comment)` — cancela (organizador) o elimina (evento propio sin asistentes)
- `respond_to_event(user_email, event_id, response, comment, send_response)` — `accept` / `decline` / `tentative` a una invitación recibida
- `get_availability(user_email, emails, start, end, interval_minutes)` — libre/ocupado de personas y salas
  (`availabilityView`: 0 libre, 1 tentativo, 2 ocupado, 3 fuera de oficina, 4 sin datos)
- `find_meeting_times(user_email, attendees, duration_minutes, start, end, max_candidates)` — huecos en los que todos están libres
- `list_rooms(user_email)` — salas (nombre, email, capacidad)
- `get_out_of_office(user_email)` / `set_out_of_office(user_email, status, start, end, internal_message, external_message, external_audience)` —
  `status`: `scheduled` (con `start`/`end`), `alwaysEnabled`, `disabled`

Para cuadrar una reunión: `find_meeting_times` o `get_availability` → propuesta al usuario → `create_calendar_event`.

### Teams
- `list_chats(user_email, top)` — chats con miembros; `get_chat_messages(user_email, chat_id, top)` — leer un chat
- `find_chat_with(user_email, person)` — chat 1:1 con una persona por **nombre o email** (lo crea si no existe)
- `send_teams_chat_message(user_email, message, chat_id, to)` — con `chat_id`, o con `to` = nombre/email de la persona
- `list_teams(user_email)`, `list_channels(user_email, team_id)`, `get_channel_messages(user_email, team_id, channel_id, top)`,
  `send_teams_channel_message(user_email, team_id, channel_id, message)`

### OneDrive y SharePoint
- `list_files(user_email, folder_path, site)` — `site` vacío = OneDrive propio; URL del sitio
  (`https://heurafoods.sharepoint.com/sites/Finanzas`) = su biblioteca de documentos
- `search_sharepoint_sites(user_email, query)` — encuentra la URL de un sitio por nombre
- `upload_file_to_onedrive(user_email, filename, content, folder_path, content_base64, site)` — texto o binario (base64), hasta 150 MB, OneDrive o SharePoint
- `download_file(user_email, path, share_url, site, max_mb)` — devuelve `content_base64`: guárdalo en el scratchpad y ábrelo con la skill que toque
- `create_sharing_link(user_email, path, share_url, site, link_type, scope)` — enlace `view`/`edit` para la organización

### Personas
- `find_person(user_email, query, top)` — busca por nombre y devuelve email, cargo y departamento. Úsalo cuando el
  usuario nombre a alguien sin email ("envíaselo a Belén"); si hay varias coincidencias, pregunta cuál.

### Microsoft To Do
- `list_todo_lists(user_email)` — listas (`id`, `displayName`, `wellknownListName`); la por defecto tiene `wellknownListName == "defaultList"`
- `list_todo_tasks(user_email, list_id, top, include_completed)` — tareas de una lista (`list_id` vacío = por defecto)
- `get_todo_task(user_email, list_id, task_id)` — una tarea con sus `checklistItems`
- `create_todo_task(user_email, title, list_id, body, due_date, importance)`, `update_todo_task(...)`,
  `complete_todo_task(user_email, list_id, task_id)`, `delete_todo_task(user_email, list_id, task_id)` — requieren el
  permiso `Tasks.ReadWrite` (login reciente)

## Permisos nuevos (1.6.0)

Fuera de oficina, categorías, buscar personas, SharePoint por URL, salas, equipos/canales y escritura en To Do
piden permisos que las sesiones antiguas no tienen. Si una de esas tools devuelve "Esta funcion necesita
permisos...", lanza el login (arriba) y reintenta; el resto de tools no se ven afectadas.

## Flujo estándar

1. Confirmar email del usuario
2. Entender la acción solicitada; si nombra personas sin email, resolverlas con `find_person`
3. **Mostrar resumen** de lo que se va a hacer (destinatarios, asunto, adjuntos, fechas, sala...)
4. Esperar confirmación explícita del usuario
5. Ejecutar con la tool correspondiente
6. Confirmar resultado

## Ejemplos de uso

**Email:**
> "Envía un email a compras@heurafoods.com diciéndoles que el pedido 4500002621 está aprobado, con copia oculta a Marc"
> → `find_person("Marc")` si hace falta → `send_email(..., bcc="marc.coloma@heurafoods.com")`

**Responder en el hilo con adjunto de SharePoint:**
> "Responde a Belén con la factura que está en este enlace: https://heurafoods.sharepoint.com/:b:/s/Finanzas/..."
> → `list_emails(search="...")` para el `id` → `reply_email(message_id=..., body=..., attachments=[{"share_url": "..."}])`

**Borrador para revisar, programado:**
> "Prepárame un borrador para el equipo con el informe adjunto, que salga el lunes a las 8"
> → `create_draft_email(..., attachments=[...], send_at="2026-09-22T08:00")` → el usuario lo revisa en Outlook y lo envía

**Organizar:**
> "Archiva los correos de Vodafone de la semana pasada y márcalos como leídos"
> → `list_emails(from_address="...", since=..., until=...)` → confirmar → `mark_email(is_read=true)` + `move_email(folder="archive")`

**Calendario:**
> "Busca un hueco de 45 minutos con Ana y Marc esta semana, reserva la sala grande y pon enlace de Teams"
> → `find_meeting_times` → `list_rooms` → confirmar → `create_calendar_event(room=..., is_online_meeting=true)`

**Teams:**
> "Dile a Sergi por Teams que el informe está listo"
> → `send_teams_chat_message(message=..., to="Sergi Roca")`

**To Do:**
> "¿Qué tareas tengo pendientes en To Do?"
