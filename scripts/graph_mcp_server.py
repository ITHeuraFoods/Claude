import os
import json
import base64
import binascii
import html
import mimetypes
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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
# Scopes ampliados por bloque funcional (1.6.0), separados por el mismo motivo que To Do:
# quien no se haya vuelto a loguear conserva lo que ya le funciona y solo le falla la
# funcion nueva, con un mensaje que le dice que relance «Conectar M365 con Claude».
MAILBOX_SCOPES      = SCOPES + ["MailboxSettings.ReadWrite"]           # fuera de oficina, categorias
PEOPLE_SCOPES       = SCOPES + ["People.Read", "User.ReadBasic.All"]   # buscar personas
SITES_SCOPES        = SCOPES + ["Sites.Read.All"]                      # sitios de SharePoint
PLACES_SCOPES       = SCOPES + ["Place.Read.All"]                      # salas
TEAMS_SCOPES        = SCOPES + ["Team.ReadBasic.All", "Channel.ReadBasic.All"]
CHANNEL_READ_SCOPES = TEAMS_SCOPES + ["ChannelMessage.Read.All"]
TZ_MADRID = "Europe/Madrid"
TOKEN_DIR = os.environ.get("HEURA_TOKEN_DIR", r"C:\heura-mcp\m365_tokens")
GRAPH     = "https://graph.microsoft.com/v1.0"

# La IP de escucha se fija por entorno: en el hub es la del tunel, no 0.0.0.0.
BIND_HOST = os.environ.get("HEURA_BIND_HOST", "0.0.0.0")
mcp = FastMCP("graph-heura", host=BIND_HOST, port=3002)


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
        nuevos = sorted(set(scopes or []) - set(SCOPES))
        if nuevos:
            raise ValueError(
                f"Esta funcion necesita permisos que la sesion M365 de {user_email} no tiene "
                f"({', '.join(nuevos)}). Vuelve a lanzar 'Conectar M365 con Claude' del escritorio "
                "(no hace falta reiniciar Claude) y reintenta. Si sigue fallando, IT tiene que "
                "conceder esos permisos en Entra."
            )
        raise ValueError(f"No se pudo renovar el token para {user_email}: {result}")
    return result["access_token"]


def _call(method: str, endpoint: str, user_email: str, scopes: list | None = None,
          extra_headers: dict | None = None, **kwargs):
    token   = _get_token(user_email, scopes)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
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

# Graph admite adjuntos inline (fileAttachment con contentBytes) hasta ~3 MB por
# fichero y 4 MB por peticion, base64 incluido. Por encima hace falta una
# uploadSession, que no implementamos: para eso esta OneDrive.
_MB = 1024 * 1024
_MAX_INLINE_MB = 3.0      # adjunto incrustado en la propia peticion (limite de Graph)
_MAX_ATTACH_MB = 150.0    # con sesion de subida por trozos (limite de Outlook)
_CHUNK = 10 * 327680      # 3,2 MB: Graph exige multiplos de 320 KiB
_PREFER_TZ = {"Prefer": f'outlook.timezone="{TZ_MADRID}"'}


def _recipients(csv: str) -> list:
    return [{"emailAddress": {"address": a.strip()}} for a in (csv or "").split(",") if a.strip()]


def _onedrive_bytes(user_email: str, path: str) -> bytes:
    """Descarga un fichero del OneDrive del usuario por ruta ('Documentos/x.pdf')."""
    token = _get_token(user_email)
    p = "/" + path.strip().lstrip("/")
    r = requests.get(f"{GRAPH}/me/drive/root:{p}:/content",
                     headers={"Authorization": f"Bearer {token}"}, timeout=120)
    if not r.ok:
        raise ValueError(f"No se pudo leer '{path}' del OneDrive de {user_email}: "
                         f"{r.status_code} {r.reason}")
    return r.content


def _share_id(url: str) -> str:
    return "u!" + base64.urlsafe_b64encode(url.strip().encode()).decode().rstrip("=")


def _share_bytes(user_email: str, url: str) -> tuple:
    """
    Descarga un fichero a partir de un enlace compartido de SharePoint u OneDrive
    (el que da "Copiar vinculo" en la web). Graph lo resuelve por /shares/{id},
    con id = "u!" + base64url(url). El usuario tiene que tener acceso al fichero.
    Devuelve (nombre, bytes).
    """
    token = _get_token(user_email)
    sid = _share_id(url)
    h = {"Authorization": f"Bearer {token}"}
    meta = requests.get(f"{GRAPH}/shares/{sid}/driveItem?$select=name,size,file", headers=h, timeout=60)
    if not meta.ok:
        raise ValueError(f"No se pudo resolver el enlace compartido ({meta.status_code} {meta.reason}). "
                         "Comprueba que es un enlace de SharePoint/OneDrive y que tienes acceso.")
    item = meta.json()
    if "file" not in item:
        raise ValueError("El enlace apunta a una carpeta o a un sitio, no a un fichero.")
    if item.get("size", 0) > _MAX_ATTACH_MB * _MB:
        raise ValueError(f"'{item.get('name')}' pesa {item.get('size', 0) / _MB:.1f} MB; el maximo por "
                         f"fichero es {_MAX_ATTACH_MB:g} MB. Pon el enlace en el cuerpo del correo.")
    r = requests.get(f"{GRAPH}/shares/{sid}/driveItem/content", headers=h, timeout=300)
    if not r.ok:
        raise ValueError(f"No se pudo descargar '{item.get('name')}': {r.status_code} {r.reason}")
    return item.get("name") or "adjunto", r.content


def _collect_attachments(user_email: str, attachments: list | None) -> list:
    """
    Resuelve la lista de adjuntos de las tools a [{name, data, content_type}].

    Cada elemento es un dict con UNA de estas tres formas:
      {"share_url": "https://heurafoods.sharepoint.com/:x:/s/.../archivo.xlsx"}   <- enlace de SharePoint/OneDrive
      {"onedrive_path": "Documentos/Informes/informe.pdf", "name": "opcional.pdf"} <- ruta en el OneDrive propio
      {"name": "informe.pdf", "content_base64": "<base64>", "content_type": "application/pdf"}

    Los ficheros del portatil del usuario no son accesibles desde el hub: para
    esos, o estan en SharePoint/OneDrive (lo normal en Heura) o Claude los manda
    en base64, que solo es razonable para ficheros pequenos.
    Hasta 3 MB van incrustados; hasta 150 MB, por sesion de subida (el correo se
    crea como borrador, se adjunta por trozos y se envia).
    """
    out = []
    for i, a in enumerate(attachments or []):
        if isinstance(a, str):
            try:
                a = json.loads(a)
            except ValueError:
                raise ValueError(f"Adjunto {i}: se esperaba un objeto JSON, no texto")
        if not isinstance(a, dict):
            raise ValueError(f"Adjunto {i}: se esperaba un objeto, no {type(a).__name__}")
        if a.get("share_url"):
            name, data = _share_bytes(user_email, a["share_url"])
            name = a.get("name") or name
        elif a.get("onedrive_path"):
            data = _onedrive_bytes(user_email, a["onedrive_path"])
            name = a.get("name") or a["onedrive_path"].rstrip("/").rsplit("/", 1)[-1]
        elif a.get("content_base64"):
            name = a.get("name")
            if not name:
                raise ValueError(f"Adjunto {i}: falta 'name'")
            try:
                data = base64.b64decode("".join(str(a["content_base64"]).split()), validate=True)
            except (binascii.Error, ValueError):
                raise ValueError(f"Adjunto '{name}': content_base64 no es base64 valido")
        else:
            raise ValueError(f"Adjunto {i}: hace falta 'share_url', 'onedrive_path' o 'content_base64'")
        if len(data) > _MAX_ATTACH_MB * _MB:
            raise ValueError(f"Adjunto '{name}' pesa {len(data) / _MB:.1f} MB; el maximo es "
                             f"{_MAX_ATTACH_MB:g} MB. Pon el enlace en el cuerpo del correo.")
        out.append({"name": name, "data": data,
                    "content_type": a.get("content_type") or mimetypes.guess_type(name)[0]})
    return out


def _inline_item(it: dict) -> dict:
    item = {"@odata.type": "#microsoft.graph.fileAttachment", "name": it["name"],
            "contentBytes": base64.b64encode(it["data"]).decode()}
    if it.get("content_type"):
        item["contentType"] = it["content_type"]
    return item


def _fits_inline(items: list) -> bool:
    return (all(len(it["data"]) <= _MAX_INLINE_MB * _MB for it in items)
            and sum(len(it["data"]) for it in items) <= _MAX_INLINE_MB * _MB)


def _attachments_payload(user_email: str, attachments: list | None) -> list:
    """Adjuntos SOLO incrustados (3 MB por fichero y por peticion). Compatibilidad."""
    items = _collect_attachments(user_email, attachments)
    for it in items:
        if len(it["data"]) > _MAX_INLINE_MB * _MB:
            raise ValueError(f"Adjunto '{it['name']}' pesa {len(it['data']) / _MB:.1f} MB; el maximo "
                             f"incrustado es {_MAX_INLINE_MB:g} MB.")
    if sum(len(it["data"]) for it in items) > _MAX_INLINE_MB * _MB:
        raise ValueError(f"Los adjuntos suman mas de {_MAX_INLINE_MB:g} MB incrustados.")
    return [_inline_item(it) for it in items]


def _upload_chunks(upload_url: str, data: bytes) -> dict:
    """Sube `data` a una uploadSession de Graph por trozos de _CHUNK (sin Authorization)."""
    total, pos, last = len(data), 0, {}
    while pos < total:
        end = min(pos + _CHUNK, total)
        r = requests.put(upload_url, data=data[pos:end], timeout=300,
                         headers={"Content-Length": str(end - pos),
                                  "Content-Range": f"bytes {pos}-{end - 1}/{total}"})
        if r.status_code not in (200, 201, 202):
            raise ValueError(f"Fallo la subida por trozos en el byte {pos}: {r.status_code} "
                             f"{(r.text or '')[:200]}")
        pos = end
        try:
            last = r.json() if r.content else {}
        except ValueError:
            last = {}
    return last


def _attach_to_message(user_email: str, message_id: str, items: list) -> None:
    """Adjunta a un borrador: incrustado si cabe, sesion de subida si no."""
    for it in items:
        if len(it["data"]) <= _MAX_INLINE_MB * _MB:
            _call("POST", f"/me/messages/{message_id}/attachments", user_email, json=_inline_item(it))
        else:
            sess = _call("POST", f"/me/messages/{message_id}/attachments/createUploadSession", user_email,
                         json={"AttachmentItem": {"attachmentType": "file", "name": it["name"],
                                                  "size": len(it["data"]),
                                                  "contentType": it.get("content_type") or "application/octet-stream"}})
            _upload_chunks(sess["uploadUrl"], it["data"])


def _madrid_to_utc(value: str) -> datetime:
    """'2026-09-18T08:00' (hora Madrid) o ISO con zona -> datetime UTC."""
    v = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(TZ_MADRID))
    return dt.astimezone(timezone.utc)


def _deferred(send_at: str) -> dict:
    """Propiedad MAPI PR_DEFERRED_SEND_TIME: Exchange retiene el correo hasta esa hora."""
    if not send_at:
        return {}
    when = _madrid_to_utc(send_at)
    if when <= datetime.now(timezone.utc) + timedelta(minutes=1):
        raise ValueError(f"send_at ({send_at}) tiene que ser una hora futura (hora de Madrid).")
    return {"singleValueExtendedProperties": [
        {"id": "SystemTime 0x3FEF", "value": when.strftime("%Y-%m-%dT%H:%M:%SZ")}]}


def _html_body(body: str, body_type: str) -> str:
    if (body_type or "HTML").lower() == "text":
        return "<div>" + html.escape(body).replace("\n", "<br>") + "</div>"
    return body


def _message(to, subject, body, body_type, cc, bcc):
    msg = {"subject": subject, "body": {"contentType": body_type, "content": body},
           "toRecipients": _recipients(to)}
    if cc:
        msg["ccRecipients"] = _recipients(cc)
    if bcc:
        msg["bccRecipients"] = _recipients(bcc)
    return msg


@mcp.tool()
def send_email(user_email: str, to: str, subject: str, body: str,
               body_type: str = "HTML", cc: str = "", bcc: str = "",
               attachments: list | None = None, send_at: str = "") -> dict:
    """
    Envía un email NUEVO en nombre del usuario.
    - user_email: email M365 del remitente (ej: ana@heurafoods.com)
    - to / cc / bcc: destinatarios separados por coma (cc y bcc opcionales)
    - body_type: 'HTML' o 'Text'
    - attachments: (opcional) lista de adjuntos, cada uno
        {"share_url": "https://heurafoods.sharepoint.com/..."} (enlace de SharePoint/OneDrive),
        {"onedrive_path": "Documentos/Informes/informe.pdf"} o
        {"name": "informe.pdf", "content_base64": "..."}.
      Hasta 3 MB van incrustados; hasta 150 MB por sesión de subida.
    - send_at: (opcional) envío programado, hora de Madrid ISO (ej: 2026-09-18T08:00).
      Exchange retiene el correo y lo envía a esa hora aunque Claude ya no esté abierto.
    Para responder a un correo existente usa reply_email, no send_email: si no, rompes el hilo.
    """
    items = _collect_attachments(user_email, attachments)
    msg = _message(to, subject, body, body_type, cc, bcc)
    if not send_at and _fits_inline(items):
        if items:
            msg["attachments"] = [_inline_item(it) for it in items]
        _call("POST", "/me/sendMail", user_email, json={"message": msg})
    else:
        msg.update(_deferred(send_at))
        draft = _call("POST", "/me/messages", user_email, json=msg)
        _attach_to_message(user_email, draft["id"], items)
        _call("POST", f"/me/messages/{draft['id']}/send", user_email)
    return {"status": "programado" if send_at else "enviado", "to": to, "subject": subject,
            "send_at": send_at or None, "attachments": [it["name"] for it in items]}


@mcp.tool()
def reply_email(user_email: str, message_id: str, body: str, body_type: str = "HTML",
                reply_all: bool = False, to: str = "", cc: str = "", bcc: str = "",
                attachments: list | None = None, send_at: str = "") -> dict:
    """
    Responde a un correo existente SIN romper el hilo: la respuesta sale con el mismo
    conversationId y las cabeceras In-Reply-To/References del original, con el "RE:"
    y el mensaje citado debajo, igual que desde Outlook.
    - message_id: id del correo original (de list_emails)
    - body: texto de la respuesta; va encima del mensaje citado
    - body_type: 'HTML' o 'Text'
    - reply_all: True para responder a todos los destinatarios originales
    - to / cc / bcc: (opcional) destinatarios ADICIONALES separados por coma; los originales se mantienen
    - attachments: (opcional) misma forma que en send_email
    - send_at: (opcional) envío programado, hora de Madrid ISO
    """
    action = "createReplyAll" if reply_all else "createReply"
    draft = _call("POST", f"/me/messages/{message_id}/{action}", user_email)
    draft_id = draft.get("id")
    if not draft_id:
        raise ValueError("Graph no devolvió el borrador de respuesta")

    quoted = draft.get("body") or {}
    quoted_html = quoted.get("content", "")
    if str(quoted.get("contentType", "html")).lower() == "text":
        quoted_html = _html_body(quoted_html, "text")

    patch = {"body": {"contentType": "HTML", "content": _html_body(body, body_type) + quoted_html}}
    if to:
        patch["toRecipients"] = (draft.get("toRecipients") or []) + _recipients(to)
    if cc:
        patch["ccRecipients"] = (draft.get("ccRecipients") or []) + _recipients(cc)
    if bcc:
        patch["bccRecipients"] = (draft.get("bccRecipients") or []) + _recipients(bcc)
    patch.update(_deferred(send_at))
    _call("PATCH", f"/me/messages/{draft_id}", user_email, json=patch)

    items = _collect_attachments(user_email, attachments)
    _attach_to_message(user_email, draft_id, items)

    _call("POST", f"/me/messages/{draft_id}/send", user_email)
    final_to = patch.get("toRecipients") or draft.get("toRecipients") or []
    return {"status": "programado" if send_at else "respondido", "reply_all": reply_all,
            "subject": draft.get("subject"), "send_at": send_at or None,
            "to": [r.get("emailAddress", {}).get("address") for r in final_to],
            "attachments": [it["name"] for it in items],
            "conversationId": draft.get("conversationId")}


@mcp.tool()
def forward_email(user_email: str, message_id: str, to: str, comment: str = "",
                  body_type: str = "HTML", cc: str = "", bcc: str = "",
                  attachments: list | None = None, send_at: str = "") -> dict:
    """
    Reenvía un correo existente CONSERVANDO sus adjuntos originales y el hilo ("RV:"),
    igual que Reenviar en Outlook.
    - message_id: id del correo original (de list_emails)
    - to / cc / bcc: destinatarios separados por coma
    - comment: texto que va encima del mensaje reenviado (opcional)
    - attachments: adjuntos ADICIONALES, misma forma que en send_email
    - send_at: (opcional) envío programado, hora de Madrid ISO
    """
    draft = _call("POST", f"/me/messages/{message_id}/createForward", user_email)
    draft_id = draft.get("id")
    if not draft_id:
        raise ValueError("Graph no devolvió el borrador de reenvío")
    quoted = draft.get("body") or {}
    quoted_html = quoted.get("content", "")
    if str(quoted.get("contentType", "html")).lower() == "text":
        quoted_html = _html_body(quoted_html, "text")
    patch = {"toRecipients": _recipients(to)}
    if comment:
        patch["body"] = {"contentType": "HTML", "content": _html_body(comment, body_type) + quoted_html}
    if cc:
        patch["ccRecipients"] = _recipients(cc)
    if bcc:
        patch["bccRecipients"] = _recipients(bcc)
    patch.update(_deferred(send_at))
    _call("PATCH", f"/me/messages/{draft_id}", user_email, json=patch)
    items = _collect_attachments(user_email, attachments)
    _attach_to_message(user_email, draft_id, items)
    _call("POST", f"/me/messages/{draft_id}/send", user_email)
    return {"status": "programado" if send_at else "reenviado", "subject": draft.get("subject"),
            "to": to, "send_at": send_at or None,
            "original_attachments": [a.get("name") for a in (draft.get("attachments") or [])],
            "attachments": [it["name"] for it in items]}


@mcp.tool()
def create_draft_email(user_email: str, to: str, subject: str, body: str,
                       body_type: str = "HTML", cc: str = "", bcc: str = "",
                       attachments: list | None = None, send_at: str = "") -> dict:
    """
    Crea un borrador de email en la bandeja del usuario (no lo envía), para que lo revise
    en Outlook antes de que salga.
    - user_email: email M365 del remitente (ej: ana@heurafoods.com)
    - to / cc / bcc: destinatarios separados por coma (cc y bcc opcionales)
    - body_type: 'HTML' o 'Text'
    - attachments: (opcional) misma forma que en send_email (hasta 150 MB por sesión de subida)
    - send_at: (opcional) hora de Madrid ISO; al enviarlo (desde Outlook o con send_draft_email)
      Exchange lo retendrá hasta esa hora.
    Devuelve el id del borrador para poder enviarlo con send_draft_email.
    """
    msg = _message(to, subject, body, body_type, cc, bcc)
    msg.update(_deferred(send_at))
    result = _call("POST", "/me/messages", user_email, json=msg)
    items = _collect_attachments(user_email, attachments)
    if items:
        if not result.get("id"):
            raise ValueError("Graph creo el borrador pero no devolvio su id; no se pudieron adjuntar los ficheros")
        _attach_to_message(user_email, result["id"], items)
    return {"status": "borrador_creado", "id": result.get("id"), "to": to, "subject": subject,
            "send_at": send_at or None, "attachments": [it["name"] for it in items],
            "webLink": result.get("webLink")}


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


_WELL_KNOWN_FOLDERS = {"inbox", "archive", "deleteditems", "sentitems", "drafts", "junkemail",
                       "outbox", "clutter", "conversationhistory", "scheduled"}
_FOLDER_ALIASES = {"bandeja de entrada": "inbox", "entrada": "inbox", "archivo": "archive",
                   "archivar": "archive", "eliminados": "deleteditems", "papelera": "deleteditems",
                   "enviados": "sentitems", "elementos enviados": "sentitems", "borradores": "drafts",
                   "correo no deseado": "junkemail", "spam": "junkemail"}


def _folder_id(user_email: str, folder: str) -> str:
    """Nombre conocido, alias en castellano, nombre visible (dos niveles) o id -> id de carpeta."""
    f = (folder or "inbox").strip()
    low = f.lower()
    if low in _WELL_KNOWN_FOLDERS:
        return low
    if low in _FOLDER_ALIASES:
        return _FOLDER_ALIASES[low]
    if len(f) > 60 and " " not in f:
        return f
    top = _call("GET", "/me/mailFolders?$top=200&$select=id,displayName", user_email).get("value", [])
    for x in top:
        if str(x.get("displayName", "")).lower() == low:
            return x["id"]
    for x in top:
        for c in _call("GET", f"/me/mailFolders/{x['id']}/childFolders?$top=200&$select=id,displayName",
                       user_email).get("value", []):
            if str(c.get("displayName", "")).lower() == low:
                return c["id"]
    raise ValueError(f"No encuentro la carpeta '{folder}'. Carpetas: "
                     + ", ".join(str(x.get("displayName")) for x in top))


def _day_bounds(value: str, end: bool) -> str:
    v = value.strip()
    if len(v) == 10:
        v += "T23:59:59" if end else "T00:00:00"
    return _madrid_to_utc(v).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slim_message(m: dict) -> dict:
    return {
        "id": m.get("id"), "subject": m.get("subject"),
        "from": ((m.get("from") or {}).get("emailAddress") or {}).get("address"),
        "from_name": ((m.get("from") or {}).get("emailAddress") or {}).get("name"),
        "to": [(r.get("emailAddress") or {}).get("address") for r in (m.get("toRecipients") or [])],
        "receivedDateTime": m.get("receivedDateTime"), "hasAttachments": m.get("hasAttachments"),
        "isRead": m.get("isRead"), "bodyPreview": m.get("bodyPreview"),
        "conversationId": m.get("conversationId"), "webLink": m.get("webLink"),
    }


@mcp.tool()
def list_folders(user_email: str) -> list:
    """Lista las carpetas de correo (dos niveles) con id, nombre y contadores."""
    out = []
    for x in _call("GET", "/me/mailFolders?$top=200&$select=id,displayName,unreadItemCount,totalItemCount,childFolderCount",
                   user_email).get("value", []):
        out.append({"id": x["id"], "name": x.get("displayName"), "unread": x.get("unreadItemCount"),
                    "total": x.get("totalItemCount")})
        if x.get("childFolderCount"):
            for c in _call("GET", f"/me/mailFolders/{x['id']}/childFolders?$top=200&$select=id,displayName,unreadItemCount,totalItemCount",
                           user_email).get("value", []):
                out.append({"id": c["id"], "name": f"{x.get('displayName')}/{c.get('displayName')}",
                            "unread": c.get("unreadItemCount"), "total": c.get("totalItemCount")})
    return out


@mcp.tool()
def list_emails(user_email: str, top: int = 10, folder: str = "inbox",
                only_with_attachments: bool = False, search: str = "",
                from_address: str = "", since: str = "", until: str = "",
                unread_only: bool = False) -> list:
    """
    Lista o busca correos en cualquier carpeta. Devuelve id, subject, from, to, fecha,
    hasAttachments, isRead, bodyPreview, conversationId y webLink.
    - folder: 'inbox' (default), 'sentitems', 'drafts', 'archive', 'deleteditems', un nombre de
      carpeta tal como se ve en Outlook (p. ej. 'Proveedores') o un id de carpeta.
    - top: cuántos devolver (default 10)
    - from_address: remitente exacto (email) o parte del nombre/email si se combina con search
    - since / until: fechas 'YYYY-MM-DD' o ISO hora Madrid; acotan por fecha de recepción
    - only_with_attachments / unread_only: filtros booleanos
    - search: texto libre (asunto/cuerpo/remitente, sintaxis KQL de Outlook). Con search, los
      demás filtros se aplican después sobre los resultados.
    """
    fid = _folder_id(user_email, folder)
    select = "id,subject,from,toRecipients,receivedDateTime,hasAttachments,isRead,bodyPreview,conversationId,webLink"
    base = f"/me/mailFolders/{fid}/messages?$select={select}"
    if search:
        # $search no admite $orderby ni $filter en Graph: se filtra despues en memoria
        endpoint = base + f'&$top={min(max(top * 4, top), 250)}&$search="{search}"'
        msgs = _call("GET", endpoint, user_email).get("value", [])
        lo = _day_bounds(since, False) if since else None
        hi = _day_bounds(until, True) if until else None
        out = []
        for m in msgs:
            fa = (((m.get("from") or {}).get("emailAddress") or {}))
            fa_txt = f"{fa.get('name', '')} {fa.get('address', '')}".lower()
            if from_address and from_address.lower() not in fa_txt:
                continue
            if only_with_attachments and not m.get("hasAttachments"):
                continue
            if unread_only and m.get("isRead"):
                continue
            rd = str(m.get("receivedDateTime") or "")
            if lo and rd < lo:
                continue
            if hi and rd > hi:
                continue
            out.append(_slim_message(m))
        return out[:top]

    # Graph obliga a que la propiedad de $orderby este tambien en $filter cuando se filtra
    # por otras: por eso receivedDateTime va siempre en el filtro.
    filters = [f"receivedDateTime ge {_day_bounds(since, False) if since else '1970-01-01T00:00:00Z'}"]
    if until:
        filters.append(f"receivedDateTime le {_day_bounds(until, True)}")
    if from_address:
        filters.append(f"from/emailAddress/address eq '{from_address.strip().replace(chr(39), chr(39) * 2)}'")
    if only_with_attachments:
        filters.append("hasAttachments eq true")
    if unread_only:
        filters.append("isRead eq false")
    endpoint = base + f"&$top={top}&$filter={' and '.join(filters)}&$orderby=receivedDateTime desc"
    return [_slim_message(m) for m in _call("GET", endpoint, user_email).get("value", [])]


@mcp.tool()
def get_email(user_email: str, message_id: str, as_text: bool = True, max_chars: int = 20000) -> dict:
    """
    Devuelve un correo completo: cabeceras y cuerpo (texto plano por defecto, HTML si as_text=False).
    Úsalo para leer un correo entero antes de responderlo; list_emails solo trae un extracto.
    """
    prefer = {"Prefer": 'outlook.body-content-type="text"'} if as_text else None
    m = _call("GET", f"/me/messages/{message_id}?$select=id,subject,from,toRecipients,ccRecipients,"
                     "receivedDateTime,sentDateTime,body,hasAttachments,isRead,conversationId,webLink,"
                     "importance,categories,flag",
              user_email, extra_headers=prefer)
    out = _slim_message(m)
    out.update({
        "cc": [(r.get("emailAddress") or {}).get("address") for r in (m.get("ccRecipients") or [])],
        "importance": m.get("importance"), "categories": m.get("categories"),
        "flag": (m.get("flag") or {}).get("flagStatus"),
        "body": ((m.get("body") or {}).get("content") or "")[:max_chars],
        "body_type": (m.get("body") or {}).get("contentType"),
    })
    return out


@mcp.tool()
def move_email(user_email: str, message_id: str, folder: str) -> dict:
    """
    Mueve un correo a otra carpeta. folder admite 'archive' (archivar), 'deleteditems',
    'inbox', 'junkemail', un nombre de carpeta tal como se ve en Outlook o un id.
    """
    dest = _folder_id(user_email, folder)
    r = _call("POST", f"/me/messages/{message_id}/move", user_email, json={"destinationId": dest})
    return {"status": "movido", "folder": folder, "new_id": r.get("id"), "subject": r.get("subject")}


@mcp.tool()
def mark_email(user_email: str, message_id: str, is_read: bool | None = None,
               categories: list | None = None, flag: str = "", importance: str = "") -> dict:
    """
    Marca un correo: leído/no leído, categorías, seguimiento e importancia. Solo cambia lo que se pasa.
    - is_read: true/false
    - categories: lista de nombres de categoría de Outlook (sustituye a las actuales; [] las quita)
    - flag: 'flagged', 'complete' o 'notFlagged'
    - importance: 'low', 'normal' o 'high'
    """
    patch = {}
    if is_read is not None:
        patch["isRead"] = bool(is_read)
    if categories is not None:
        if isinstance(categories, str):
            categories = [c.strip() for c in categories.split(",") if c.strip()]
        patch["categories"] = list(categories)
    if flag:
        if flag not in ("flagged", "complete", "notFlagged"):
            raise ValueError("flag debe ser 'flagged', 'complete' o 'notFlagged'")
        patch["flag"] = {"flagStatus": flag}
    if importance:
        if importance not in ("low", "normal", "high"):
            raise ValueError("importance debe ser 'low', 'normal' o 'high'")
        patch["importance"] = importance
    if not patch:
        raise ValueError("No se ha indicado nada que cambiar")
    r = _call("PATCH", f"/me/messages/{message_id}", user_email, json=patch)
    return {"status": "actualizado", "id": r.get("id"), "isRead": r.get("isRead"),
            "categories": r.get("categories"), "flag": (r.get("flag") or {}).get("flagStatus"),
            "importance": r.get("importance")}


@mcp.tool()
def list_categories(user_email: str) -> list:
    """Categorías de Outlook definidas por el usuario (nombre y color), para usarlas en mark_email."""
    r = _call("GET", "/me/outlook/masterCategories", user_email, scopes=MAILBOX_SCOPES)
    return [{"name": c.get("displayName"), "color": c.get("color")} for c in r.get("value", [])]


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

def _slim_event(e: dict) -> dict:
    return {
        "id": e.get("id"), "subject": e.get("subject"),
        "start": (e.get("start") or {}).get("dateTime"), "end": (e.get("end") or {}).get("dateTime"),
        "timeZone": (e.get("start") or {}).get("timeZone"),
        "location": (e.get("location") or {}).get("displayName"),
        "organizer": ((e.get("organizer") or {}).get("emailAddress") or {}).get("address"),
        "attendees": [{"email": (a.get("emailAddress") or {}).get("address"),
                       "type": a.get("type"),
                       "response": (a.get("status") or {}).get("response")} for a in (e.get("attendees") or [])],
        "my_response": (e.get("responseStatus") or {}).get("response"),
        "isOnlineMeeting": e.get("isOnlineMeeting"),
        "joinUrl": (e.get("onlineMeeting") or {}).get("joinUrl"),
        "isCancelled": e.get("isCancelled"), "isAllDay": e.get("isAllDay"),
        "recurring": bool(e.get("seriesMasterId") or e.get("recurrence")),
        "webLink": e.get("webLink"),
    }


_EVENT_SELECT = ("id,subject,start,end,location,attendees,organizer,responseStatus,isOnlineMeeting,"
                 "onlineMeeting,isCancelled,isAllDay,seriesMasterId,webLink")


@mcp.tool()
def list_calendar_events(user_email: str, days: int = 7, start: str = "", until: str = "",
                         top: int = 50) -> list:
    """
    Lista eventos del calendario en hora de Madrid, con su id (necesario para modificar,
    cancelar o responder).
    - days: cuántos días hacia adelante desde ahora (default 7); se ignora si se pasan start/until
    - start / until: rango explícito, 'YYYY-MM-DD' o ISO hora Madrid
    """
    if start or until:
        lo = _day_bounds(start, False) if start else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        hi = _day_bounds(until, True) if until else (_madrid_to_utc(start) + timedelta(days=days or 7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        now = datetime.now(timezone.utc)
        lo = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        hi = (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = _call("GET", f"/me/calendarView?startDateTime={lo}&endDateTime={hi}"
                          f"&$select={_EVENT_SELECT}&$top={top}&$orderby=start/dateTime",
                   user_email, extra_headers=_PREFER_TZ)
    return [_slim_event(e) for e in result.get("value", [])]


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _recurrence(rec, start: str) -> dict | None:
    """
    Traduce una recurrencia sencilla al formato de Graph. Acepta ya el formato de Graph
    ({"pattern":..., "range":...}) o uno simple:
      {"type": "daily|weekly|monthly", "interval": 1, "days_of_week": ["monday","wednesday"],
       "day_of_month": 15, "until": "2026-12-31" | "count": 10}
    """
    if not rec:
        return None
    if isinstance(rec, str):
        rec = json.loads(rec)
    if "pattern" in rec and "range" in rec:
        return rec
    t = str(rec.get("type", "weekly")).lower()
    if t not in ("daily", "weekly", "monthly"):
        raise ValueError("recurrence.type debe ser daily, weekly o monthly")
    pattern = {"type": t, "interval": int(rec.get("interval", 1))}
    days = rec.get("days_of_week") or rec.get("daysOfWeek")
    if isinstance(days, str):
        days = [d.strip() for d in days.split(",") if d.strip()]
    start_dt = datetime.fromisoformat(start[:19])
    if t == "weekly":
        pattern["daysOfWeek"] = [d.lower() for d in days] if days else [_WEEKDAYS[start_dt.weekday()]]
        pattern["firstDayOfWeek"] = "monday"
    elif t == "monthly":
        pattern["type"] = "absoluteMonthly"
        pattern["dayOfMonth"] = int(rec.get("day_of_month") or start_dt.day)
    rng = {"type": "noEnd", "startDate": start[:10], "recurrenceTimeZone": TZ_MADRID}
    if rec.get("until"):
        rng.update({"type": "endDate", "endDate": str(rec["until"])[:10]})
    elif rec.get("count"):
        rng.update({"type": "numbered", "numberOfOccurrences": int(rec["count"])})
    return {"pattern": pattern, "range": rng}


def _attendee_list(required: str, optional: str = "", room: str = "") -> list:
    out = [{"emailAddress": {"address": a.strip()}, "type": "required"}
           for a in (required or "").split(",") if a.strip()]
    out += [{"emailAddress": {"address": a.strip()}, "type": "optional"}
            for a in (optional or "").split(",") if a.strip()]
    if room:
        out.append({"emailAddress": {"address": room.strip()}, "type": "resource"})
    return out


@mcp.tool()
def create_calendar_event(user_email: str, subject: str, start: str, end: str,
                          body: str = "", attendees: str = "", location: str = "",
                          optional_attendees: str = "", room: str = "",
                          is_online_meeting: bool = False, recurrence: dict | None = None,
                          reminder_minutes: int | None = None, all_day: bool = False) -> dict:
    """
    Crea un evento (o reunión) en el calendario del usuario y envía las invitaciones.
    - start / end: ISO 8601 en hora local Madrid (ej: 2026-06-25T10:00:00)
    - attendees / optional_attendees: emails separados por coma
    - room: email de la sala (de list_rooms); se reserva como recurso y se pone como ubicación
    - is_online_meeting: True añade el enlace de Teams
    - recurrence: {"type": "weekly", "interval": 1, "days_of_week": ["monday"], "until": "2026-12-31"}
      o {"type": "monthly", "day_of_month": 1, "count": 6}; también vale el formato de Graph
    - reminder_minutes: aviso antes del evento
    """
    payload = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": TZ_MADRID},
        "end":   {"dateTime": end,   "timeZone": TZ_MADRID},
        "body":  {"contentType": "HTML", "content": body},
        "location": {"displayName": location or (room.split("@")[0] if room else "")},
    }
    if all_day:
        payload["isAllDay"] = True
    if room:
        payload["location"] = {"displayName": location or room.split("@")[0],
                               "locationEmailAddress": room.strip(), "locationType": "conferenceRoom"}
    att = _attendee_list(attendees, optional_attendees, room)
    if att:
        payload["attendees"] = att
    if is_online_meeting:
        payload["isOnlineMeeting"] = True
        payload["onlineMeetingProvider"] = "teamsForBusiness"
    rec = _recurrence(recurrence, start)
    if rec:
        payload["recurrence"] = rec
    if reminder_minutes is not None:
        payload["isReminderOn"] = True
        payload["reminderMinutesBeforeStart"] = int(reminder_minutes)
    result = _call("POST", "/me/events", user_email, json=payload, extra_headers=_PREFER_TZ)
    out = _slim_event(result)
    out["status"] = "creado"
    return out


@mcp.tool()
def update_calendar_event(user_email: str, event_id: str, subject: str = "", start: str = "",
                          end: str = "", body: str = "", location: str = "", attendees: str = "",
                          optional_attendees: str = "", room: str = "",
                          is_online_meeting: bool | None = None,
                          reminder_minutes: int | None = None) -> dict:
    """
    Modifica un evento existente (solo los campos que se pasan) y notifica a los asistentes.
    - event_id: de list_calendar_events
    - attendees / optional_attendees / room: si se pasan, SUSTITUYEN la lista actual de asistentes
    Para una serie recurrente, el id de la ocurrencia modifica solo esa; el de la serie, todas.
    """
    patch = {}
    if subject:
        patch["subject"] = subject
    if start:
        patch["start"] = {"dateTime": start, "timeZone": TZ_MADRID}
    if end:
        patch["end"] = {"dateTime": end, "timeZone": TZ_MADRID}
    if body:
        patch["body"] = {"contentType": "HTML", "content": body}
    if location or room:
        patch["location"] = {"displayName": location or room.split("@")[0]}
        if room:
            patch["location"].update({"locationEmailAddress": room.strip(), "locationType": "conferenceRoom"})
    if attendees or optional_attendees or room:
        patch["attendees"] = _attendee_list(attendees, optional_attendees, room)
    if is_online_meeting is not None:
        patch["isOnlineMeeting"] = bool(is_online_meeting)
        if is_online_meeting:
            patch["onlineMeetingProvider"] = "teamsForBusiness"
    if reminder_minutes is not None:
        patch["isReminderOn"] = True
        patch["reminderMinutesBeforeStart"] = int(reminder_minutes)
    if not patch:
        raise ValueError("No se ha indicado nada que cambiar")
    result = _call("PATCH", f"/me/events/{event_id}", user_email, json=patch, extra_headers=_PREFER_TZ)
    out = _slim_event(result)
    out["status"] = "actualizado"
    return out


@mcp.tool()
def cancel_calendar_event(user_email: str, event_id: str, comment: str = "") -> dict:
    """
    Cancela un evento. Si el usuario es el organizador y hay asistentes, envía la cancelación
    con el comentario; si no (evento propio sin asistentes), lo elimina del calendario.
    Para declinar una invitación ajena usa respond_to_event.
    """
    try:
        _call("POST", f"/me/events/{event_id}/cancel", user_email, json={"comment": comment})
        return {"status": "cancelado", "notified": True}
    except requests.exceptions.HTTPError as exc:
        code = getattr(exc.response, "status_code", 0)
        if code not in (400, 403, 405):
            raise
    _call("DELETE", f"/me/events/{event_id}", user_email)
    return {"status": "eliminado", "notified": False}


@mcp.tool()
def respond_to_event(user_email: str, event_id: str, response: str, comment: str = "",
                     send_response: bool = True) -> dict:
    """
    Responde a una invitación recibida.
    - response: 'accept', 'decline' o 'tentative'
    - comment: texto opcional para el organizador
    - send_response: False para no enviar la respuesta al organizador
    """
    action = {"accept": "accept", "aceptar": "accept", "decline": "decline", "rechazar": "decline",
              "tentative": "tentativelyAccept", "tentativo": "tentativelyAccept",
              "tentativelyaccept": "tentativelyAccept"}.get(response.strip().lower())
    if not action:
        raise ValueError("response debe ser 'accept', 'decline' o 'tentative'")
    _call("POST", f"/me/events/{event_id}/{action}", user_email,
          json={"comment": comment, "sendResponse": bool(send_response)})
    return {"status": action, "event_id": event_id}


@mcp.tool()
def get_availability(user_email: str, emails: str, start: str, end: str,
                     interval_minutes: int = 30) -> list:
    """
    Disponibilidad (libre/ocupado) de una o varias personas o salas entre dos horas de Madrid.
    - emails: separados por coma (incluye al propio usuario si quieres verte a ti)
    Devuelve por persona la vista de disponibilidad (0 libre, 1 tentativo, 2 ocupado, 3 fuera de
    oficina, 4 sin datos) por tramo de interval_minutes y los bloques ocupados.
    """
    body = {"schedules": [a.strip() for a in emails.split(",") if a.strip()],
            "startTime": {"dateTime": start, "timeZone": TZ_MADRID},
            "endTime": {"dateTime": end, "timeZone": TZ_MADRID},
            "availabilityViewInterval": int(interval_minutes)}
    r = _call("POST", "/me/calendar/getSchedule", user_email, json=body, extra_headers=_PREFER_TZ)
    out = []
    for s in r.get("value", []):
        out.append({"email": s.get("scheduleId"), "availabilityView": s.get("availabilityView"),
                    "busy": [{"status": i.get("status"), "start": (i.get("start") or {}).get("dateTime"),
                              "end": (i.get("end") or {}).get("dateTime"), "subject": i.get("subject")}
                             for i in s.get("scheduleItems", [])],
                    "error": (s.get("error") or {}).get("message")})
    return out


@mcp.tool()
def find_meeting_times(user_email: str, attendees: str, duration_minutes: int = 30,
                       start: str = "", end: str = "", max_candidates: int = 5) -> list:
    """
    Propone huecos en los que todos los asistentes están libres (horario laboral), para cuadrar
    una reunión. start/end acotan la búsqueda (hora Madrid); sin ellos, Graph busca en los
    próximos días.
    """
    body = {"attendees": [{"emailAddress": {"address": a.strip()}, "type": "required"}
                          for a in attendees.split(",") if a.strip()],
            "meetingDuration": f"PT{int(duration_minutes)}M",
            "maxCandidates": int(max_candidates), "returnSuggestionReasons": True,
            "isOrganizerOptional": False}
    if start and end:
        body["timeConstraint"] = {"activityDomain": "work", "timeSlots": [
            {"start": {"dateTime": start, "timeZone": TZ_MADRID}, "end": {"dateTime": end, "timeZone": TZ_MADRID}}]}
    r = _call("POST", "/me/findMeetingTimes", user_email, json=body, extra_headers=_PREFER_TZ)
    out = []
    for s in r.get("meetingTimeSuggestions", []):
        slot = s.get("meetingTimeSlot") or {}
        out.append({"start": (slot.get("start") or {}).get("dateTime"), "end": (slot.get("end") or {}).get("dateTime"),
                    "confidence": s.get("confidence"), "reason": s.get("suggestionReason"),
                    "attendees": [{"email": ((a.get("attendee") or {}).get("emailAddress") or {}).get("address"),
                                   "availability": a.get("availability")} for a in s.get("attendeeAvailability", [])]})
    if not out and r.get("emptySuggestionsReason"):
        return [{"error": r["emptySuggestionsReason"]}]
    return out


@mcp.tool()
def list_rooms(user_email: str) -> list:
    """Salas de reuniones de la organización (nombre, email para reservar, capacidad, edificio)."""
    r = _call("GET", "/places/microsoft.graph.room?$top=100", user_email, scopes=PLACES_SCOPES)
    return [{"name": p.get("displayName"), "email": p.get("emailAddress"), "capacity": p.get("capacity"),
             "building": p.get("building"), "floor": p.get("floorNumber")} for p in r.get("value", [])]


@mcp.tool()
def get_out_of_office(user_email: str) -> dict:
    """Estado actual de las respuestas automáticas (fuera de oficina) del usuario."""
    return _call("GET", "/me/mailboxSettings/automaticRepliesSetting", user_email,
                 scopes=MAILBOX_SCOPES, extra_headers=_PREFER_TZ)


@mcp.tool()
def set_out_of_office(user_email: str, status: str = "scheduled", start: str = "", end: str = "",
                      internal_message: str = "", external_message: str = "",
                      external_audience: str = "all") -> dict:
    """
    Activa o quita el fuera de oficina.
    - status: 'scheduled' (entre start y end, hora Madrid), 'alwaysEnabled' o 'disabled'
    - internal_message / external_message: HTML o texto; si external está vacío se usa el interno
    - external_audience: 'all', 'contactsOnly' o 'none'
    """
    if status not in ("scheduled", "alwaysEnabled", "disabled"):
        raise ValueError("status debe ser scheduled, alwaysEnabled o disabled")
    setting = {"status": status, "externalAudience": external_audience}
    if status != "disabled":
        setting["internalReplyMessage"] = internal_message
        setting["externalReplyMessage"] = external_message or internal_message
    if status == "scheduled":
        if not (start and end):
            raise ValueError("Con status='scheduled' hacen falta start y end")
        setting["scheduledStartDateTime"] = {"dateTime": start, "timeZone": TZ_MADRID}
        setting["scheduledEndDateTime"] = {"dateTime": end, "timeZone": TZ_MADRID}
    r = _call("PATCH", "/me/mailboxSettings", user_email, json={"automaticRepliesSetting": setting},
              scopes=MAILBOX_SCOPES, extra_headers=_PREFER_TZ)
    return {"status": "actualizado", "automaticReplies": r.get("automaticRepliesSetting", setting)}


# ── ONEDRIVE / SHAREPOINT ────────────────────────────────────────────────────

def _drive_base(user_email: str, site: str = "") -> str:
    """'' -> OneDrive propio; URL o id de sitio de SharePoint -> biblioteca por defecto del sitio."""
    s = (site or "").strip()
    if not s:
        return "/me/drive"
    if s.startswith("http"):
        m = re.match(r"https?://([^/]+)(/(?:sites|teams)/[^/?#]+)", s)
        if not m:
            raise ValueError("La URL del sitio debe ser como https://heurafoods.sharepoint.com/sites/Finanzas")
        info = _call("GET", f"/sites/{m.group(1)}:{m.group(2)}?$select=id", user_email, scopes=SITES_SCOPES)
        s = info["id"]
    return f"/sites/{s}/drive"


def _item_path(base: str, path: str) -> str:
    p = "/" + (path or "").strip().strip("/")
    return f"{base}/root" if p == "/" else f"{base}/root:{p}:"


def _slim_item(x: dict) -> dict:
    return {"id": x.get("id"), "name": x.get("name"), "size": x.get("size"),
            "type": "folder" if "folder" in x else "file",
            "children": (x.get("folder") or {}).get("childCount"),
            "lastModified": x.get("lastModifiedDateTime"), "webUrl": x.get("webUrl")}


@mcp.tool()
def list_files(user_email: str, folder_path: str = "", site: str = "", top: int = 200) -> list:
    """
    Lista el contenido de una carpeta de OneDrive (site vacío) o de la biblioteca de documentos
    de un sitio de SharePoint (site = URL del sitio, p. ej. https://heurafoods.sharepoint.com/sites/Finanzas).
    - folder_path: ruta dentro de la biblioteca ('' = raíz), p. ej. 'Documentos compartidos/Facturas'
    """
    base = _drive_base(user_email, site)
    r = _call("GET", f"{_item_path(base, folder_path)}/children?$top={top}"
                     "&$select=id,name,size,lastModifiedDateTime,webUrl,folder,file", user_email)
    return [_slim_item(x) for x in r.get("value", [])]


@mcp.tool()
def search_sharepoint_sites(user_email: str, query: str) -> list:
    """Busca sitios de SharePoint por nombre y devuelve su URL (para usarla como `site` en las tools de ficheros)."""
    r = _call("GET", f"/sites?search={requests.utils.quote(query)}&$select=id,displayName,webUrl,description",
              user_email, scopes=SITES_SCOPES)
    return [{"name": s.get("displayName"), "url": s.get("webUrl"), "id": s.get("id"),
             "description": s.get("description")} for s in r.get("value", [])]


def _put_file(user_email: str, base: str, path: str, data: bytes, ctype: str) -> dict:
    token = _get_token(user_email)
    target = _item_path(base, path)
    if len(data) <= 4 * _MB:
        r = requests.put(f"{GRAPH}{target}/content", headers={"Authorization": f"Bearer {token}",
                         "Content-Type": ctype}, data=data, timeout=300)
        if not r.ok:
            raise ValueError(f"No se pudo subir '{path}': {r.status_code} {r.reason} {(r.text or '')[:200]}")
        return r.json()
    sess = _call("POST", f"{target}/createUploadSession", user_email,
                 json={"item": {"@microsoft.graph.conflictBehavior": "replace"}})
    return _upload_chunks(sess["uploadUrl"], data)


@mcp.tool()
def upload_file_to_onedrive(user_email: str, filename: str, content: str = "",
                            folder_path: str = "", content_base64: str = "", site: str = "") -> dict:
    """
    Crea o sobreescribe un archivo en OneDrive del usuario o en un sitio de SharePoint.
    - folder_path: ruta dentro de la biblioteca, ej: 'Documentos/Informes' (vacío = raíz)
    - content: contenido como texto plano o HTML (ficheros de texto)
    - content_base64: contenido binario en base64 (PDF, Excel...). Excluyente con content.
      Hasta 4 MB directo; por encima, sesión de subida por trozos (hasta 150 MB).
    - site: vacío = OneDrive propio; URL del sitio de SharePoint para su biblioteca de documentos
    La ruta resultante sirve como onedrive_path en los adjuntos (solo OneDrive propio); para
    SharePoint usa el webUrl devuelto como share_url.
    """
    if content_base64:
        try:
            data = base64.b64decode("".join(content_base64.split()), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("content_base64 no es base64 válido")
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    else:
        data, ctype = content.encode(), "text/plain"
    if len(data) > _MAX_ATTACH_MB * _MB:
        raise ValueError(f"El fichero pesa {len(data) / _MB:.1f} MB; el máximo son {_MAX_ATTACH_MB:g} MB.")
    base = _drive_base(user_email, site)
    path = f"{folder_path.strip('/')}/{filename}".strip("/")
    result = _put_file(user_email, base, path, data, ctype)
    return {"status": "subido", "name": result.get("name"), "path": path, "size": len(data),
            "webUrl": result.get("webUrl"), "id": result.get("id")}


@mcp.tool()
def download_file(user_email: str, path: str = "", share_url: str = "", site: str = "",
                  max_mb: float = 25.0) -> dict:
    """
    Descarga un fichero y lo devuelve en base64 para que Claude lo guarde en disco (scratchpad)
    y lo abra con la skill que toque (pdf, xlsx, docx...).
    - path + site: ruta en OneDrive propio (site vacío) o en la biblioteca de un sitio de SharePoint
    - share_url: alternativa, enlace de «Copiar vínculo» de SharePoint/OneDrive
    - max_mb: límite (default 25) para no saturar el contexto; por encima devuelve error
    """
    if share_url:
        name, data = _share_bytes(user_email, share_url)
    else:
        if not path:
            raise ValueError("Hace falta path o share_url")
        base = _drive_base(user_email, site)
        token = _get_token(user_email)
        meta = _call("GET", f"{_item_path(base, path)}?$select=name,size,file", user_email)
        if "file" not in meta:
            raise ValueError(f"'{path}' es una carpeta, no un fichero")
        if meta.get("size", 0) > max_mb * _MB:
            raise ValueError(f"'{meta.get('name')}' pesa {meta.get('size', 0) / _MB:.1f} MB (> {max_mb:g} MB). "
                             "Pide un enlace con create_sharing_link en vez de descargarlo.")
        r = requests.get(f"{GRAPH}{_item_path(base, path)}/content",
                         headers={"Authorization": f"Bearer {token}"}, timeout=300)
        if not r.ok:
            raise ValueError(f"No se pudo descargar '{path}': {r.status_code} {r.reason}")
        name, data = meta.get("name"), r.content
    if len(data) > max_mb * _MB:
        raise ValueError(f"'{name}' pesa {len(data) / _MB:.1f} MB (> {max_mb:g} MB).")
    return {"name": name, "size": len(data), "contentType": mimetypes.guess_type(name or "")[0],
            "content_base64": base64.b64encode(data).decode()}


@mcp.tool()
def create_sharing_link(user_email: str, path: str = "", share_url: str = "", site: str = "",
                        link_type: str = "view", scope: str = "organization") -> dict:
    """
    Genera un enlace para compartir un fichero o carpeta.
    - path + site: ruta en OneDrive propio o en un sitio de SharePoint; o share_url de un enlace existente
    - link_type: 'view' (solo lectura) o 'edit'
    - scope: 'organization' (cualquiera de Heura con el enlace) o 'anonymous' (si la política lo permite)
    """
    if link_type not in ("view", "edit"):
        raise ValueError("link_type debe ser 'view' o 'edit'")
    if share_url:
        target = f"/shares/{_share_id(share_url)}/driveItem"
    else:
        if not path:
            raise ValueError("Hace falta path o share_url")
        target = _item_path(_drive_base(user_email, site), path)
    r = _call("POST", f"{target}/createLink", user_email, json={"type": link_type, "scope": scope})
    link = r.get("link") or {}
    return {"status": "creado", "url": link.get("webUrl"), "type": link.get("type"), "scope": link.get("scope")}


# ── PERSONAS ────────────────────────────────────────────────────────────────

@mcp.tool()
def find_person(user_email: str, query: str, top: int = 5) -> list:
    """
    Busca personas de la organización por nombre (o parte) y devuelve email, cargo y departamento.
    Primero entre los contactos relevantes del usuario; si no hay, en el directorio.
    """
    q = query.strip().replace('"', "")
    out, seen = [], set()
    try:
        r = _call("GET", f'/me/people?$search="{q}"&$top={top}&$select=displayName,scoredEmailAddresses,jobTitle,department,personType',
                  user_email, scopes=PEOPLE_SCOPES)
        for p in r.get("value", []):
            if (p.get("personType") or {}).get("class") not in (None, "Person"):
                continue
            mail = ((p.get("scoredEmailAddresses") or [{}])[0]).get("address")
            if mail and mail.lower() not in seen:
                seen.add(mail.lower())
                out.append({"name": p.get("displayName"), "email": mail, "jobTitle": p.get("jobTitle"),
                            "department": p.get("department"), "source": "contactos"})
    except (requests.exceptions.HTTPError, ValueError):
        pass
    if len(out) < top:
        r = _call("GET", f'/users?$search="displayName:{q}" OR "mail:{q}"&$top={top}&$select=displayName,mail,jobTitle,department',
                  user_email, scopes=PEOPLE_SCOPES, extra_headers={"ConsistencyLevel": "eventual"})
        for u in r.get("value", []):
            mail = u.get("mail")
            if mail and mail.lower() not in seen:
                seen.add(mail.lower())
                out.append({"name": u.get("displayName"), "email": mail, "jobTitle": u.get("jobTitle"),
                            "department": u.get("department"), "source": "directorio"})
    return out[:top]


def _resolve_person(user_email: str, person: str) -> dict:
    """'nombre' o 'email' -> {"name", "email"}; error claro si no hay una coincidencia inequívoca."""
    p = person.strip()
    if "@" in p:
        return {"name": p, "email": p.lower()}
    hits = find_person(user_email, p, top=5)
    if not hits:
        raise ValueError(f"No encuentro a nadie que se llame '{person}' en Heura.")
    exact = [h for h in hits if str(h.get("name", "")).lower() == p.lower()]
    if len(exact) == 1:
        return exact[0]
    if len(hits) == 1:
        return hits[0]
    raise ValueError(f"'{person}' es ambiguo: " + "; ".join(f"{h['name']} <{h['email']}>" for h in hits)
                     + ". Indica el email o el nombre completo.")


# ── TEAMS ────────────────────────────────────────────────────────────────────

def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>|</p>|</div>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def _slim_chat(c: dict) -> dict:
    members = [{"name": m.get("displayName"), "email": m.get("email")} for m in (c.get("members") or [])]
    return {"id": c.get("id"), "topic": c.get("topic"), "chatType": c.get("chatType"),
            "members": members, "lastUpdated": c.get("lastUpdatedDateTime"), "webUrl": c.get("webUrl")}


@mcp.tool()
def list_chats(user_email: str, top: int = 20) -> list:
    """Chats de Teams del usuario (1:1, grupo y reunión), del más reciente al más antiguo, con sus miembros."""
    # /me/chats no admite $orderby por lastUpdatedDateTime (400); Graph ya los devuelve del mas
    # reciente al mas antiguo.
    r = _call("GET", f"/me/chats?$expand=members&$top={top}", user_email)
    return [_slim_chat(c) for c in r.get("value", [])]


@mcp.tool()
def get_chat_messages(user_email: str, chat_id: str, top: int = 20) -> list:
    """Últimos mensajes de un chat de Teams (texto plano, del más reciente al más antiguo)."""
    r = _call("GET", f"/me/chats/{chat_id}/messages?$top={top}", user_email)
    out = []
    for m in r.get("value", []):
        if m.get("messageType") != "message" or m.get("deletedDateTime"):
            continue
        out.append({"id": m.get("id"), "from": ((m.get("from") or {}).get("user") or {}).get("displayName"),
                    "createdDateTime": m.get("createdDateTime"),
                    "text": _strip_html((m.get("body") or {}).get("content", "")),
                    "attachments": [a.get("name") for a in (m.get("attachments") or []) if a.get("name")]})
    return out


@mcp.tool()
def find_chat_with(user_email: str, person: str) -> dict:
    """
    Devuelve el chat 1:1 de Teams con una persona (por nombre o email); si no existe, lo crea.
    Útil para no tener que conocer el chat_id.
    """
    who = _resolve_person(user_email, person)
    target = who["email"].lower()
    endpoint = "/me/chats?$filter=chatType eq 'oneOnOne'&$expand=members&$top=50"
    for _ in range(6):
        r = _call("GET", endpoint, user_email)
        for c in r.get("value", []):
            if any(str(m.get("email") or "").lower() == target for m in (c.get("members") or [])):
                out = _slim_chat(c)
                out.update({"person": who, "created": False})
                return out
        nxt = r.get("@odata.nextLink")
        if not nxt:
            break
        endpoint = nxt.replace(GRAPH, "")
    c = _call("POST", "/chats", user_email, json={
        "chatType": "oneOnOne",
        "members": [
            {"@odata.type": "#microsoft.graph.aadUserConversationMember", "roles": ["owner"],
             "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{user_email}')"},
            {"@odata.type": "#microsoft.graph.aadUserConversationMember", "roles": ["owner"],
             "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{target}')"},
        ]})
    out = _slim_chat(c)
    out.update({"person": who, "created": True})
    return out


@mcp.tool()
def send_teams_chat_message(user_email: str, message: str, chat_id: str = "", to: str = "") -> dict:
    """
    Envía un mensaje en un chat de Teams.
    - chat_id: id del chat (de list_chats o de la URL de Teams), o bien
    - to: nombre o email de la persona; se busca (o crea) el chat 1:1 con ella
    """
    if not message.strip():
        raise ValueError("El mensaje está vacío")
    if not chat_id:
        if not to:
            raise ValueError("Hace falta chat_id o to")
        chat_id = find_chat_with(user_email, to)["id"]
    payload = {"body": {"contentType": "html", "content": message}}
    result = _call("POST", f"/chats/{chat_id}/messages", user_email, json=payload)
    return {"status": "enviado", "id": result.get("id"), "chat_id": chat_id}


@mcp.tool()
def list_teams(user_email: str) -> list:
    """Equipos de Teams a los que pertenece el usuario (id y nombre)."""
    r = _call("GET", "/me/joinedTeams?$select=id,displayName,description", user_email, scopes=TEAMS_SCOPES)
    return [{"id": t.get("id"), "name": t.get("displayName"), "description": t.get("description")}
            for t in r.get("value", [])]


@mcp.tool()
def list_channels(user_email: str, team_id: str) -> list:
    """Canales de un equipo (id y nombre), para send_teams_channel_message y get_channel_messages."""
    r = _call("GET", f"/teams/{team_id}/channels?$select=id,displayName,membershipType", user_email,
              scopes=TEAMS_SCOPES)
    return [{"id": c.get("id"), "name": c.get("displayName"), "type": c.get("membershipType")}
            for c in r.get("value", [])]


@mcp.tool()
def get_channel_messages(user_email: str, team_id: str, channel_id: str, top: int = 20) -> list:
    """Últimos mensajes de un canal de Teams en texto plano (requiere el permiso ChannelMessage.Read.All)."""
    r = _call("GET", f"/teams/{team_id}/channels/{channel_id}/messages?$top={top}", user_email,
              scopes=CHANNEL_READ_SCOPES)
    out = []
    for m in r.get("value", []):
        if m.get("messageType") != "message" or m.get("deletedDateTime"):
            continue
        out.append({"id": m.get("id"), "from": ((m.get("from") or {}).get("user") or {}).get("displayName"),
                    "createdDateTime": m.get("createdDateTime"), "subject": m.get("subject"),
                    "text": _strip_html((m.get("body") or {}).get("content", "")),
                    "replies": m.get("replyToId") is None})
    return out


@mcp.tool()
def send_teams_channel_message(user_email: str, team_id: str, channel_id: str,
                               message: str) -> dict:
    """
    Envía un mensaje a un canal de Teams.
    - team_id / channel_id: de list_teams y list_channels (o de la URL del canal)
    """
    payload = {"body": {"contentType": "html", "content": message}}
    result = _call("POST", f"/teams/{team_id}/channels/{channel_id}/messages",
                   user_email, json=payload)
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

# Solo esta presente en el despliegue del hub; sin el, /register funciona pero
# no emite token de acceso a los MCP.
try:
    import heura_auth
except ImportError:
    heura_auth = None


def _identity_from_msal_cache(token_cache):
    """Devuelve el correo que consta en la propia cache MSAL, o "" si no hay."""
    try:
        data = json.loads(token_cache)
    except ValueError:
        return ""
    for acc in (data.get("Account") or {}).values():
        if isinstance(acc, dict):
            user = str(acc.get("username") or "").strip().lower()
            if user:
                return user
    return ""


# Diagnostico de flota: los platform scripts de Intune no devuelven salida (solo
# exito/fallo), asi que intune-diag-user.ps1 manda aqui su linea de estado. Se
# guarda una linea por informe; la ultima de cada equipo es la que vale.
DIAG_FILE = os.environ.get("HEURA_DIAG_FILE", "/var/lib/heura-mcp/diag/equipos.tsv")


def _append_diag(body: dict) -> dict:
    """Anota un informe de diagnostico (equipo, usuario, estado, detalle) en DIAG_FILE."""
    import datetime
    def limpio(v, n=400):
        return " ".join(str(v or "").split())[:n].replace("\t", " ")
    equipo, usuario = limpio(body.get("computer"), 60), limpio(body.get("user"), 60)
    if not equipo:
        raise ValueError("Falta 'computer'")
    estado = "OK" if body.get("ok") else "KO"
    linea = "\t".join([
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        equipo, usuario, estado, limpio(body.get("detail")),
    ])
    os.makedirs(os.path.dirname(DIAG_FILE), exist_ok=True)
    with open(DIAG_FILE, "a", encoding="utf-8") as f:
        f.write(linea + "\n")
    return {"status": "anotado", "computer": equipo, "estado": estado}


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
        if self.path not in ("/register", "/diag"):
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

        if self.path == "/diag":
            try:
                self._respond(200, _append_diag(body))
            except (ValueError, OSError) as exc:
                self._respond(400, {"error": str(exc)})
            return

        token_cache = body.get("token_cache", "")
        declarado   = body.get("user_email", "").strip().lower()

        if not token_cache:
            self._respond(400, {"error": "Falta token_cache"})
            return

        # La identidad sale de la CACHE, no del cuerpo. Antes se confiaba en el
        # user_email recibido, asi que quien conociera el secreto compartido
        # podia sobrescribir la sesion de otra persona. La cache la emite Entra
        # tras un login interactivo: solo se puede presentar una propia.
        user_email = _identity_from_msal_cache(token_cache)
        if not user_email:
            self._respond(400, {"error": "No se puede deducir la identidad de la cache MSAL"})
            return
        if declarado and declarado != user_email:
            print(f"AVISO /register: declaraba {declarado} pero la cache es de {user_email}",
                  flush=True)

        safe = user_email.replace("@", "_").replace(".", "_")
        path = os.path.join(TOKEN_DIR, f"{safe}.json")
        os.makedirs(TOKEN_DIR, mode=0o700, exist_ok=True)
        with open(path, "w") as f:
            f.write(token_cache)
        # 0600 explicito: el fichero lleva el refresh token del usuario y el
        # umask del proceso lo dejaba legible por todo el mundo.
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # en Windows no aplica

        # Token de acceso a los MCP para esa identidad, si el modulo de
        # autenticacion esta disponible (despliegue en el hub). En un arranque
        # suelto sin heura_auth la sesion se registra igual y no hay token.
        # Desde 2026-09-17 registrarse NO invalida los tokens anteriores de la persona
        # (las sesiones de Claude abiertas seguian con el viejo y morian con 401 hasta
        # reiniciar). rotate=true los revoca a proposito (token filtrado, equipo perdido).
        token = None
        if heura_auth is not None:
            try:
                try:
                    token = heura_auth.issue_token(user_email, rotate=bool(body.get("rotate")))
                except TypeError:  # heura_auth antiguo en el hub, sin rotate
                    token = heura_auth.issue_token(user_email)
            except OSError as exc:
                print(f"ERROR /register: sesion guardada pero sin token: {exc}", flush=True)

        self._respond(200, {"status": "ok", "user": user_email, "token": token})


def _start_register_server():
    server = HTTPServer((BIND_HOST, 3003), _RegisterHandler)
    server.serve_forever()


if __name__ == "__main__":
    os.makedirs(TOKEN_DIR, exist_ok=True)
    threading.Thread(target=_start_register_server, daemon=True).start()
    print("Register endpoint escuchando en :3003/register")
    mcp.run(transport="streamable-http")
