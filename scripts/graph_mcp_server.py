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
TOKEN_DIR = r"C:\heura-mcp\m365_tokens"
GRAPH     = "https://graph.microsoft.com/v1.0"

mcp = FastMCP("graph-heura", host="0.0.0.0", port=3002)


def _get_token(user_email: str) -> str:
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

    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if cache.has_state_changed:
        with open(path, "w") as f:
            f.write(cache.serialize())

    if not result or "access_token" not in result:
        raise ValueError(f"No se pudo renovar el token para {user_email}: {result}")
    return result["access_token"]


def _call(method: str, endpoint: str, user_email: str, **kwargs):
    token   = _get_token(user_email)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.request(method, f"{GRAPH}{endpoint}", headers=headers, **kwargs)
    r.raise_for_status()
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
