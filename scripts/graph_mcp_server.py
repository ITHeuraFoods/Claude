import os
import json
import secrets as secrets_mod
import threading
import requests
import msal
from http.server import HTTPServer, BaseHTTPRequestHandler
from mcp.server.fastmcp import FastMCP

CLIENT_ID = "1f5ff61e-43dc-48fe-af84-d9c3f558dbcc"
TENANT_ID = "4ff8acc2-4c1a-49ba-9344-9e47d370f6fc"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES    = ["Mail.Send", "Mail.ReadWrite", "Calendars.ReadWrite", "Files.ReadWrite.All",
             "Chat.ReadWrite", "ChannelMessage.Send"]
# Scopes ampliados solo para las tools de Microsoft To Do. NO añadir Tasks.Read a SCOPES:
# las cachés MSAL ya emitidas no lo contienen y acquire_token_silent devolvería None para
# todos los usuarios, rompiendo correo, calendario, OneDrive y Teams hasta que cada uno
# volviese a loguearse. Así solo To Do falla —con mensaje claro— hasta el nuevo login.
TODO_SCOPES = SCOPES + ["Tasks.Read"]
# Mismo razonamiento un nivel más abajo: las tools de ESCRITURA piden Tasks.ReadWrite en un
# scope aparte en vez de subir TODO_SCOPES. Si se hubiese cambiado TODO_SCOPES a ReadWrite,
# la lectura —que ya funciona con los tokens Tasks.Read emitidos— se rompería hasta que
# cada usuario volviese a loguearse. Así solo fallan las escrituras hasta el nuevo login, y
# una vez hecho ese login la lectura sigue valiendo: MSAL sirve un token cacheado siempre
# que los scopes pedidos sean subconjunto de los del token, y ReadWrite implica Read.
TODO_WRITE_SCOPES = SCOPES + ["Tasks.ReadWrite"]
TOKEN_DIR = r"C:\heura-mcp\m365_tokens"
GRAPH     = "https://graph.microsoft.com/v1.0"

mcp = FastMCP("graph-heura", host="0.0.0.0", port=3002)


def _get_token(user_email: str, scopes: list | None = None) -> str:
    safe = user_email.strip().replace("@", "_").replace(".", "_")
    path = os.path.join(TOKEN_DIR, f"{safe}.json")
    if not os.path.exists(path):
        raise ValueError(
            f"No hay sesión M365 activa para {user_email}. "
            "Haz doble clic en 'Conectar M365 con Claude' en tu escritorio para autenticarte."
        )
    cache = msal.SerializableTokenCache()
    with open(path) as f:
        cache.deserialize(f.read())

    app      = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
    accounts = app.get_accounts()
    if not accounts:
        raise ValueError(f"Token caducado para {user_email}. Vuelve a hacer doble clic en 'Conectar M365 con Claude'.")

    result = app.acquire_token_silent(scopes or SCOPES, account=accounts[0])
    if cache.has_state_changed:
        with open(path, "w") as f:
            f.write(cache.serialize())

    if not result or "access_token" not in result:
        raise ValueError(f"No se pudo renovar el token para {user_email}: {result}")
    return result["access_token"]


def _call(method: str, endpoint: str, user_email: str, scopes: list | None = None, **kwargs):
    token   = _get_token(user_email, scopes)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.request(method, f"{GRAPH}{endpoint}", headers=headers, **kwargs)
    if not r.ok:
        # raise_for_status() a secas se come el cuerpo de la respuesta, que es justo donde
        # Graph dice QUÉ cláusula OData ha rechazado. Sin esto, un 400 solo deja la URL y
        # hay que adivinar (nos pasó con list_todo_tasks). Se conserva response= para que
        # los except que miran e.response.status_code sigan funcionando.
        try:
            detail = ((r.json().get("error") or {}).get("message") or "").strip()
        except ValueError:
            detail = (r.text or "")[:300].strip()
        raise requests.exceptions.HTTPError(
            f"{r.status_code} {r.reason} en {method} {endpoint}"
            + (f" — {detail}" if detail else ""),
            response=r,
        )
    return r.json() if r.content else {}


# ── CORREO ──────────────────────────────────────────────────────────────────

@mcp.tool()
def send_email(user_email: str, to: str, subject: str, body: str,
               body_type: str = "HTML", cc: str = "") -> dict:
    """
    Envía un email en nombre del usuario.
    - user_email: email M365 del remitente (ej: ana@heurafoods.com)
    - to: destinatario/s separados por coma
    - cc: (opcional) destinatarios en copia
    - body_type: 'HTML' o 'Text'
    """
    msg = {
        "subject": subject,
        "body": {"contentType": body_type, "content": body},
        "toRecipients": [{"emailAddress": {"address": a.strip()}} for a in to.split(",") if a.strip()],
    }
    if cc:
        msg["ccRecipients"] = [{"emailAddress": {"address": a.strip()}} for a in cc.split(",") if a.strip()]
    _call("POST", "/me/sendMail", user_email, json={"message": msg})
    return {"status": "enviado", "to": to, "subject": subject}


@mcp.tool()
def create_draft_email(user_email: str, to: str, subject: str, body: str,
                       body_type: str = "HTML", cc: str = "") -> dict:
    """
    Crea un borrador de email en la bandeja del usuario (no lo envía).
    - user_email: email M365 del remitente (ej: ana@heurafoods.com)
    - to: destinatario/s separados por coma
    - cc: (opcional) destinatarios en copia
    - body_type: 'HTML' o 'Text'
    Devuelve el id del borrador para poder enviarlo o editarlo después.
    """
    msg = {
        "subject": subject,
        "body": {"contentType": body_type, "content": body},
        "toRecipients": [{"emailAddress": {"address": a.strip()}} for a in to.split(",") if a.strip()],
    }
    if cc:
        msg["ccRecipients"] = [{"emailAddress": {"address": a.strip()}} for a in cc.split(",") if a.strip()]
    result = _call("POST", "/me/messages", user_email, json=msg)
    return {"status": "borrador_creado", "id": result.get("id"), "to": to, "subject": subject}


@mcp.tool()
def send_draft_email(user_email: str, draft_id: str) -> dict:
    """
    Envía un borrador previamente creado con create_draft_email.
    - draft_id: el id devuelto por create_draft_email
    """
    token   = _get_token(user_email)
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{GRAPH}/me/messages/{draft_id}/send", headers=headers)
    r.raise_for_status()
    return {"status": "enviado", "draft_id": draft_id}


@mcp.tool()
def list_emails(user_email: str, top: int = 10, folder: str = "inbox",
                only_with_attachments: bool = False, search: str = "") -> list:
    """
    Lista correos del usuario para localizar su id (necesario para leer adjuntos).
    - folder: carpeta a listar ('inbox', 'sentitems', 'drafts'... default 'inbox')
    - top: cuántos correos devolver (default 10)
    - only_with_attachments: si True, solo correos que tienen adjuntos
    - search: (opcional) texto a buscar en asunto/cuerpo/remitente (KQL de Graph)
    Devuelve id, subject, from, receivedDateTime, hasAttachments, bodyPreview.
    """
    select = "id,subject,from,receivedDateTime,hasAttachments,bodyPreview"
    endpoint = f"/me/mailFolders/{folder}/messages?$select={select}&$top={top}"
    if search:
        # $search no admite $orderby ni $filter combinados en Graph
        endpoint += f'&$search="{search}"'
    else:
        endpoint += "&$orderby=receivedDateTime desc"
        if only_with_attachments:
            endpoint += "&$filter=hasAttachments eq true"
    result = _call("GET", endpoint, user_email)
    return result.get("value", [])


@mcp.tool()
def list_attachments(user_email: str, message_id: str) -> list:
    """
    Lista los adjuntos de un correo (sin descargar su contenido).
    - message_id: id del correo (obtenido con list_emails)
    Devuelve id, name, contentType, size (bytes), isInline por cada adjunto.
    """
    endpoint = (f"/me/messages/{message_id}/attachments"
                "?$select=id,name,contentType,size,isInline")
    result = _call("GET", endpoint, user_email)
    return [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "contentType": a.get("contentType"),
            "size": a.get("size"),
            "isInline": a.get("isInline"),
            "type": a.get("@odata.type"),
        }
        for a in result.get("value", [])
    ]


@mcp.tool()
def get_attachment(user_email: str, message_id: str, attachment_id: str,
                   max_mb: float = 10.0) -> dict:
    """
    Descarga un adjunto de tipo fichero y devuelve su contenido en base64.
    Claude debe decodificar 'content_base64' y guardarlo en disco para trabajarlo.
    - message_id: id del correo (list_emails)
    - attachment_id: id del adjunto (list_attachments)
    - max_mb: límite de tamaño; por encima devuelve error (usa OneDrive para ficheros grandes)
    """
    att = _call("GET", f"/me/messages/{message_id}/attachments/{attachment_id}", user_email)
    odata = att.get("@odata.type", "")
    if "fileAttachment" not in odata:
        return {"error": f"Adjunto no descargable como fichero (tipo {odata}). "
                         "Solo se soportan fileAttachment."}
    size = att.get("size", 0)
    if size > max_mb * 1024 * 1024:
        return {"error": f"Adjunto demasiado grande ({size} bytes > {max_mb} MB). "
                         "Súbelo a OneDrive en su lugar."}
    return {
        "name": att.get("name"),
        "contentType": att.get("contentType"),
        "size": size,
        "content_base64": att.get("contentBytes", ""),
    }


# ── CALENDARIO ──────────────────────────────────────────────────────────────

@mcp.tool()
def list_calendar_events(user_email: str, days: int = 7) -> list:
    """
    Lista los próximos eventos del calendario del usuario.
    - days: cuántos días hacia adelante (default 7)
    """
    from datetime import datetime, timedelta
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = _call(
        "GET",
        f"/me/calendarView?startDateTime={now}&endDateTime={end}"
        f"&$select=subject,start,end,location,attendees&$top=20&$orderby=start/dateTime",
        user_email,
    )
    return result.get("value", [])


@mcp.tool()
def create_calendar_event(user_email: str, subject: str, start: str, end: str,
                           body: str = "", attendees: str = "", location: str = "") -> dict:
    """
    Crea un evento en el calendario del usuario.
    - start / end: ISO 8601 en hora local Madrid (ej: 2026-06-25T10:00:00)
    - attendees: emails separados por coma (opcional)
    """
    payload = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": "Europe/Madrid"},
        "end":   {"dateTime": end,   "timeZone": "Europe/Madrid"},
        "body":  {"contentType": "HTML", "content": body},
        "location": {"displayName": location},
    }
    if attendees:
        payload["attendees"] = [
            {"emailAddress": {"address": a.strip()}, "type": "required"}
            for a in attendees.split(",") if a.strip()
        ]
    result = _call("POST", "/me/events", user_email, json=payload)
    return {"status": "creado", "id": result.get("id"), "subject": subject, "start": start}


# ── ONEDRIVE / SHAREPOINT ────────────────────────────────────────────────────

@mcp.tool()
def upload_file_to_onedrive(user_email: str, filename: str, content: str,
                             folder_path: str = "") -> dict:
    """
    Crea o sobreescribe un archivo de texto en OneDrive del usuario.
    - folder_path: ruta dentro de OneDrive, ej: 'Documentos/Informes' (vacío = raíz)
    - content: contenido del fichero como texto plano o HTML
    """
    token   = _get_token(user_email)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "text/plain"}
    path    = f"/{folder_path}/{filename}".replace("//", "/")
    r       = requests.put(f"{GRAPH}/me/drive/root:{path}:/content",
                           headers=headers, data=content.encode())
    r.raise_for_status()
    result = r.json()
    return {"status": "subido", "name": result.get("name"), "webUrl": result.get("webUrl")}


# ── TEAMS ────────────────────────────────────────────────────────────────────

@mcp.tool()
def send_teams_channel_message(user_email: str, team_id: str, channel_id: str,
                                message: str) -> dict:
    """
    Envía un mensaje a un canal de Teams.
    - team_id: ID del equipo (GUID)
    - channel_id: ID del canal (GUID)
    """
    payload = {"body": {"contentType": "html", "content": message}}
    result  = _call("POST", f"/teams/{team_id}/channels/{channel_id}/messages",
                    user_email, json=payload)
    return {"status": "enviado", "id": result.get("id")}


@mcp.tool()
def send_teams_chat_message(user_email: str, chat_id: str, message: str) -> dict:
    """
    Envía un mensaje a un chat 1:1 o grupal de Teams.
    - chat_id: ID del chat (se obtiene de la URL del chat en Teams)
    """
    payload = {"body": {"contentType": "html", "content": message}}
    result  = _call("POST", f"/chats/{chat_id}/messages", user_email, json=payload)
    return {"status": "enviado", "id": result.get("id")}


# ── MICROSOFT TO DO ──────────────────────────────────────────────────────────
# Lectura con Tasks.Read (TODO_SCOPES); escritura con Tasks.ReadWrite (TODO_WRITE_SCOPES).
# Ver el bloque de scopes arriba: están separados a propósito para que conceder escritura no
# tumbe la lectura de quien todavía no se haya vuelto a loguear.


def _flatten_todo_task(t: dict) -> dict:
    """Aplana un todoTask de Graph: dueDateTime a ISO simple y body a texto truncado."""
    due = t.get("dueDateTime") or {}
    body = t.get("body") or {}
    content = (body.get("content") or "").strip()
    return {
        "id": t.get("id"),
        "title": t.get("title"),
        "status": t.get("status"),
        "importance": t.get("importance"),
        "dueDateTime": due.get("dateTime"),
        "dueTimeZone": due.get("timeZone"),
        "createdDateTime": t.get("createdDateTime"),
        "lastModifiedDateTime": t.get("lastModifiedDateTime"),
        "body": content[:500] + ("…" if len(content) > 500 else ""),
    }


def _default_todo_list_id(user_email: str) -> str:
    """Devuelve el id de la lista por defecto de To Do (o la primera si no existe)."""
    lists = _call("GET", "/me/todo/lists", user_email, scopes=TODO_SCOPES).get("value", [])
    if not lists:
        raise ValueError(f"{user_email} no tiene ninguna lista de Microsoft To Do.")
    for l in lists:
        if l.get("wellknownListName") == "defaultList":
            return l["id"]
    return lists[0]["id"]


@mcp.tool()
def list_todo_lists(user_email: str) -> list:
    """
    Lista las listas de tareas de Microsoft To Do del usuario.
    - user_email: email M365 del usuario (ej: ana@heurafoods.com)
    Devuelve id, displayName, wellknownListName, isOwner, isShared por cada lista.
    La lista por defecto es la que tiene wellknownListName == 'defaultList'.
    """
    result = _call("GET", "/me/todo/lists", user_email, scopes=TODO_SCOPES)
    return [
        {
            "id": l.get("id"),
            "displayName": l.get("displayName"),
            "wellknownListName": l.get("wellknownListName"),
            "isOwner": l.get("isOwner"),
            "isShared": l.get("isShared"),
        }
        for l in result.get("value", [])
    ]


def _fetch_todo_tasks(user_email: str, list_id: str, top: int) -> list:
    """
    Trae las tareas crudas de una lista degradando la query hasta que Graph la acepte.

    /me/todo/lists/{id}/tasks rechaza con 400 combinaciones OData que sí valen en otros
    recursos de Graph: el 2026-08-05 `$select=…,body&$top=N&$orderby=createdDateTime desc`
    devolvía 400 en todas las listas del usuario de prueba. El intento anterior de
    arreglarlo reintentaba con la MISMA query base, así que el fallback también fallaba.
    En vez de adivinar qué cláusula sobra, se prueban de la más rica a la más pobre. El
    orden y el recorte final se hacen en Python, que funciona siempre.
    """
    select = ("id,title,status,importance,dueDateTime,createdDateTime,"
              "lastModifiedDateTime,body")
    variants = [
        f"?$select={select}&$top={top}&$orderby=createdDateTime desc",
        f"?$select={select}&$top={top}",
        f"?$top={top}",
        "",
    ]
    last_error = None
    for qs in variants:
        try:
            result = _call("GET", f"/me/todo/lists/{list_id}/tasks{qs}",
                           user_email, scopes=TODO_SCOPES)
            return result.get("value", [])
        except requests.exceptions.HTTPError as e:
            # Solo un 400 (query mal formada) justifica degradar. Un 401/403 es de sesión
            # o de permisos y hay que propagarlo tal cual, no esconderlo tras 3 reintentos.
            if e.response is None or e.response.status_code != 400:
                raise
            last_error = e
    raise last_error


@mcp.tool()
def list_todo_tasks(user_email: str, list_id: str = "", top: int = 50,
                    include_completed: bool = False) -> list:
    """
    Lista las tareas de una lista de Microsoft To Do.
    - user_email: email M365 del usuario
    - list_id: (opcional) id de la lista (list_todo_lists). Vacío = lista por defecto
    - top: cuántas tareas devolver (default 50)
    - include_completed: si True incluye también las tareas ya completadas
    Devuelve id, title, status, importance, dueDateTime, createdDateTime,
    lastModifiedDateTime y body truncado a 500 caracteres, más recientes primero.
    """
    if not list_id:
        list_id = _default_todo_list_id(user_email)

    tasks = _fetch_todo_tasks(user_email, list_id, top)
    if not include_completed:
        tasks = [t for t in tasks if t.get("status") != "completed"]
    tasks.sort(key=lambda t: t.get("createdDateTime") or "", reverse=True)
    return [_flatten_todo_task(t) for t in tasks[:top]]


@mcp.tool()
def get_todo_task(user_email: str, list_id: str, task_id: str) -> dict:
    """
    Devuelve una tarea de To Do con sus subelementos (checklist).
    - user_email: email M365 del usuario
    - list_id: id de la lista (list_todo_lists)
    - task_id: id de la tarea (list_todo_tasks)
    """
    result = _call("GET", f"/me/todo/lists/{list_id}/tasks/{task_id}?$expand=checklistItems",
                   user_email, scopes=TODO_SCOPES)
    task = _flatten_todo_task(result)
    task["checklistItems"] = [
        {
            "id": c.get("id"),
            "displayName": c.get("displayName"),
            "isChecked": c.get("isChecked"),
        }
        for c in result.get("checklistItems", [])
    ]
    return task


def _due_payload(due_date: str) -> dict:
    """Convierte 'YYYY-MM-DD' (o ISO completo) al dateTimeTimeZone que espera Graph."""
    stamp = due_date.strip()
    if len(stamp) == 10:            # solo fecha: To Do la trata como todo el día
        stamp += "T00:00:00"
    return {"dateTime": stamp, "timeZone": "UTC"}


@mcp.tool()
def create_todo_task(user_email: str, title: str, list_id: str = "",
                     due_date: str = "", body: str = "",
                     importance: str = "normal") -> dict:
    """
    Crea una tarea en Microsoft To Do. Requiere Tasks.ReadWrite.
    - user_email: email M365 del usuario
    - title: título de la tarea (obligatorio)
    - list_id: (opcional) id de la lista (list_todo_lists). Vacío = lista por defecto
    - due_date: (opcional) 'YYYY-MM-DD' o ISO completo
    - body: (opcional) notas de la tarea
    - importance: 'low' | 'normal' | 'high'
    """
    if not title.strip():
        raise ValueError("title no puede estar vacío.")
    if importance not in ("low", "normal", "high"):
        raise ValueError("importance debe ser 'low', 'normal' o 'high'.")
    if not list_id:
        list_id = _default_todo_list_id(user_email)

    payload = {"title": title.strip(), "importance": importance}
    if due_date:
        payload["dueDateTime"] = _due_payload(due_date)
    if body:
        payload["body"] = {"contentType": "text", "content": body}

    result = _call("POST", f"/me/todo/lists/{list_id}/tasks", user_email,
                   scopes=TODO_WRITE_SCOPES, json=payload)
    return {"status": "creada", **_flatten_todo_task(result)}


@mcp.tool()
def update_todo_task(user_email: str, list_id: str, task_id: str,
                     title: str = "", status: str = "", due_date: str = "",
                     body: str = "", importance: str = "") -> dict:
    """
    Modifica una tarea de To Do. Requiere Tasks.ReadWrite.
    Solo se envían a Graph los campos que se pasen; el resto queda intacto (PATCH).
    - user_email: email M365 del usuario
    - list_id / task_id: ids (list_todo_lists / list_todo_tasks)
    - title: (opcional) nuevo título
    - status: (opcional) 'notStarted' | 'inProgress' | 'completed' | 'waitingOnOthers' | 'deferred'
    - due_date: (opcional) 'YYYY-MM-DD' o ISO completo
    - body: (opcional) nuevas notas
    - importance: (opcional) 'low' | 'normal' | 'high'
    """
    valid_status = ("notStarted", "inProgress", "completed", "waitingOnOthers", "deferred")
    if status and status not in valid_status:
        raise ValueError(f"status debe ser uno de: {', '.join(valid_status)}.")
    if importance and importance not in ("low", "normal", "high"):
        raise ValueError("importance debe ser 'low', 'normal' o 'high'.")

    payload = {}
    if title:
        payload["title"] = title.strip()
    if status:
        payload["status"] = status
    if due_date:
        payload["dueDateTime"] = _due_payload(due_date)
    if body:
        payload["body"] = {"contentType": "text", "content": body}
    if importance:
        payload["importance"] = importance
    if not payload:
        raise ValueError("No se ha indicado ningún campo que modificar.")

    result = _call("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}", user_email,
                   scopes=TODO_WRITE_SCOPES, json=payload)
    return {"status": "actualizada", **_flatten_todo_task(result)}


@mcp.tool()
def complete_todo_task(user_email: str, list_id: str, task_id: str) -> dict:
    """
    Marca una tarea de To Do como completada. Requiere Tasks.ReadWrite.
    Alternativa REVERSIBLE a delete_todo_task: para quitar una tarea de en medio, esta es la
    opción a preferir salvo que se quiera borrarla de verdad.
    - user_email: email M365 del usuario
    - list_id / task_id: ids (list_todo_lists / list_todo_tasks)
    """
    return update_todo_task(user_email, list_id, task_id, status="completed")


@mcp.tool()
def delete_todo_task(user_email: str, list_id: str, task_id: str,
                     expected_title: str) -> dict:
    """
    BORRA una tarea de To Do de forma DEFINITIVA. Requiere Tasks.ReadWrite.
    To Do no tiene papelera: lo borrado no se recupera. Si solo se quiere quitar la tarea de
    la vista, usar complete_todo_task, que es reversible.
    - user_email: email M365 del usuario
    - list_id / task_id: ids (list_todo_lists / list_todo_tasks)
    - expected_title: título exacto que se espera que tenga la tarea. Obligatorio: se lee la
      tarea y se aborta si no coincide. Un task_id copiado de un listado viejo apunta a otra
      tarea si la lista ha cambiado, y aquí ese error no se puede deshacer.
    """
    if not expected_title.strip():
        raise ValueError("expected_title es obligatorio para poder confirmar qué se borra.")

    current = _call("GET", f"/me/todo/lists/{list_id}/tasks/{task_id}", user_email,
                    scopes=TODO_WRITE_SCOPES)
    actual = (current.get("title") or "").strip()
    if actual != expected_title.strip():
        raise ValueError(
            f"Abortado: la tarea {task_id} se titula {actual!r}, no {expected_title.strip()!r}. "
            "Vuelve a listar las tareas para coger el id correcto."
        )

    _call("DELETE", f"/me/todo/lists/{list_id}/tasks/{task_id}", user_email,
          scopes=TODO_WRITE_SCOPES)
    return {"status": "borrada", "id": task_id, "title": actual}


# ── REGISTRO REMOTO DE TOKEN (puerto 3003) ───────────────────────────────────

REGISTER_SECRET = os.environ.get("HEURA_REGISTER_SECRET", "")


class _RegisterHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silenciar logs de acceso

    def _respond(self, code, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/register":
            self._respond(404, {"error": "Not found"})
            return

        if not REGISTER_SECRET:
            self._respond(500, {"error": "HEURA_REGISTER_SECRET no configurado"})
            return

        auth = self.headers.get("X-Heura-Secret", "")
        if not secrets_mod.compare_digest(auth, REGISTER_SECRET):
            self._respond(401, {"error": "No autorizado"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length))
        user_email  = body.get("user_email", "").strip()
        token_cache = body.get("token_cache", "")

        if not user_email or not token_cache:
            self._respond(400, {"error": "Faltan user_email o token_cache"})
            return

        safe = user_email.replace("@", "_").replace(".", "_")
        path = os.path.join(TOKEN_DIR, f"{safe}.json")
        os.makedirs(TOKEN_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(token_cache)

        self._respond(200, {"status": "ok", "user": user_email})


def _start_register_server():
    server = HTTPServer(("0.0.0.0", 3003), _RegisterHandler)
    server.serve_forever()


if __name__ == "__main__":
    os.makedirs(TOKEN_DIR, exist_ok=True)
    threading.Thread(target=_start_register_server, daemon=True).start()
    print("Register endpoint escuchando en :3003/register")
    mcp.run(transport="streamable-http")
