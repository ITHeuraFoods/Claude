"""
heura-graph-mcp — MCP de Microsoft 365 (Graph) para Heura.

Pensado para correr en un servidor Linux detrás de un reverse proxy con TLS
(Hetzner + Caddy), NO en el portátil de nadie. Ver `infra/README.md`.

QUÉ CAMBIA RESPECTO A LA VERSIÓN QUE CORRÍA EN laptop-itadm
-----------------------------------------------------------
1. **La identidad ya no es un parámetro.** Antes cada tool recibía `user_email` y
   `_get_token()` abría la caché de ese email sin comprobar quién llamaba: cualquiera que
   alcanzase el puerto 3002 podía enviar correo o borrar tareas en nombre de otro. Ahora el
   usuario sale del bearer token de la petición (`_current_user()`), que el propio hub emitió
   al hacer login. Las tools ya no aceptan `user_email`.
2. **El login vive aquí, no en el laptop.** `/auth/login` hace el Authorization Code + PKCE
   contra Entra ID y `/auth/callback` guarda la caché MSAL y emite el bearer del usuario.
   Esto sustituye por completo a `graph_login_remote.py`, al endpoint `/register` con secreto
   compartido, al acceso directo del escritorio y a `C:\\heura-mcp\\` en la flota.
3. **Un único juego de scopes.** La versión anterior tenía SCOPES / TODO_SCOPES /
   TODO_WRITE_SCOPES escalonados para no invalidar cachés ya emitidas. Con un App
   Registration nuevo todo el mundo se loguea de cero, así que ese escalonado ya no protege
   nada y se colapsa en `GRAPH_SCOPES`.
4. **Sin estado de sesión MCP.** `stateless_http=True`: reiniciar el servicio no invalida las
   sesiones de los clientes conectados, y permite replicar sin afinidad de sesión.
5. **Configuración por entorno, log de auditoría en stdout** (lo recoge journald) y `/health`.

VARIABLES DE ENTORNO
--------------------
Obligatorias:
    HEURA_ENTRA_CLIENT_ID       Application (client) ID del App Registration
    HEURA_ENTRA_CLIENT_SECRET   Client secret. Admite HEURA_ENTRA_CLIENT_SECRET_FILE con la
                                ruta a un fichero (systemd LoadCredential), preferible a la variable.
    HEURA_PUBLIC_URL            URL pública del hub, ej. https://mcp.heurafoods.com
Opcionales:
    HEURA_ENTRA_TENANT_ID       (default: tenant de Heura)
    HEURA_STATE_DIR             (default: /var/lib/heura-mcp)
    HEURA_BIND_HOST             (default: 127.0.0.1 — el proxy es quien escucha en público)
    HEURA_BIND_PORT             (default: 3002)
    HEURA_ALLOWED_DOMAINS       dominios de correo admitidos, coma (default: heurafoods.com)
    HEURA_LOG_LEVEL             (default: INFO)
"""
import hashlib
import html
import json
import logging
import os
import secrets as secrets_mod
import stat
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import msal
import requests
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

# ════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ════════════════════════════════════════════════════════════════════════════

def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_required(name: str) -> str:
    """
    Lee la variable, o el contenido del fichero al que apunte `{NAME}_FILE`.

    La indirección por fichero es la que permite entregar el client secret con
    `LoadCredential=` de systemd (o un secret montado, si algún día esto va en un
    contenedor) en vez de dejarlo escrito en un EnvironmentFile que cualquier proceso
    del servicio puede leer en /proc/self/environ.
    """
    path = _env(f"{name}_FILE")
    if path:
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            sys.exit(f"FATAL: no se pudo leer {name}_FILE ({path}): {exc}")
        if not value:
            sys.exit(f"FATAL: {name}_FILE ({path}) está vacío.")
        return value

    value = _env(name)
    if not value:
        sys.exit(
            f"FATAL: falta la variable de entorno {name} (o {name}_FILE). "
            "Ver la cabecera de este fichero e infra/README.md."
        )
    return value


CLIENT_ID     = _env_required("HEURA_ENTRA_CLIENT_ID")
CLIENT_SECRET = _env_required("HEURA_ENTRA_CLIENT_SECRET")
PUBLIC_URL    = _env_required("HEURA_PUBLIC_URL").rstrip("/")
TENANT_ID     = _env("HEURA_ENTRA_TENANT_ID", "4ff8acc2-4c1a-49ba-9344-9e47d370f6fc")
AUTHORITY     = f"https://login.microsoftonline.com/{TENANT_ID}"
GRAPH         = "https://graph.microsoft.com/v1.0"

STATE_DIR  = Path(_env("HEURA_STATE_DIR", "/var/lib/heura-mcp"))
TOKEN_DIR  = STATE_DIR / "m365_tokens"      # cachés MSAL, una por usuario
BEARER_DB  = STATE_DIR / "bearers.json"     # sha256(bearer) -> usuario

REDIRECT_URI = f"{PUBLIC_URL}/auth/callback"
MCP_PATH     = "/graph/mcp"
MCP_SCOPE    = "heura:m365"                 # scope de nuestros bearers, no de Graph

ALLOWED_DOMAINS = [
    d.strip().lower().lstrip("@")
    for d in _env("HEURA_ALLOWED_DOMAINS", "heurafoods.com").split(",")
    if d.strip()
]

# Un único juego de scopes de Graph. Tasks.ReadWrite implica Tasks.Read, así que cubre
# tanto la lectura como la escritura de To Do. Ver punto 3 de la cabecera.
GRAPH_SCOPES = [
    "Mail.Send",
    "Mail.ReadWrite",
    "Calendars.ReadWrite",
    "Files.ReadWrite.All",
    "Chat.ReadWrite",
    "ChannelMessage.Send",
    "Tasks.ReadWrite",
]

BEARER_TTL_DAYS = int(_env("HEURA_BEARER_TTL_DAYS", "90"))
LOGIN_FLOW_TTL  = 600      # un login a medias caduca en 10 min
# /auth/login es público por necesidad (es por donde se obtiene el bearer), así que cada
# visita crea estado en memoria sin que nadie se haya autenticado todavía. La purga por
# antigüedad sola no acota nada: sin este tope, pegarle al endpoint hincha el proceso.
MAX_PENDING_FLOWS = 500


# ════════════════════════════════════════════════════════════════════════════
#  LOG DE AUDITORÍA
# ════════════════════════════════════════════════════════════════════════════
# Una línea JSON por evento a stdout; journald la recoge tal cual. Este servicio actúa
# sobre el correo de la plantilla, así que tiene que quedar registrado quién pidió qué.
# NUNCA se registran bearers, tokens de Graph ni el contenido de los mensajes.

logging.basicConfig(
    level=getattr(logging, _env("HEURA_LOG_LEVEL", "INFO"), logging.INFO),
    format="%(message)s",
    stream=sys.stdout,
)
_log = logging.getLogger("heura-graph-mcp")


def audit(event: str, **fields) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event}
    record.update({k: v for k, v in fields.items() if v is not None})
    _log.info(json.dumps(record, ensure_ascii=False, sort_keys=True))


# ════════════════════════════════════════════════════════════════════════════
#  ALMACÉN DE ESTADO
# ════════════════════════════════════════════════════════════════════════════
# Dos cosas por usuario: la caché MSAL (para llamar a Graph en su nombre) y el hash de su
# bearer (para saber que es él quien llama). El directorio va 0700 y los ficheros 0600: son
# refresh tokens de larga duración. Ver la nota sobre cifrado en reposo en infra/README.md.

_locks_guard = threading.Lock()
_user_locks: dict[str, threading.Lock] = {}


def _user_lock(user_email: str) -> threading.Lock:
    """
    Un lock por usuario para el ciclo leer-renovar-escribir de su caché MSAL.

    Las tools de FastMCP son funciones síncronas y se ejecutan en un threadpool, así que dos
    peticiones del mismo usuario pueden solaparse de verdad. Sin este lock, la segunda
    sobreescribe la caché que acaba de refrescar la primera y se pierde el refresh token
    renovado.
    """
    with _locks_guard:
        return _user_locks.setdefault(user_email, threading.Lock())


def _ensure_state_dirs() -> None:
    for directory in (STATE_DIR, TOKEN_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, stat.S_IRWXU)                      # 0700


def _write_private(path: Path, payload: str) -> None:
    """Escribe con permisos 0600 desde el principio, sin ventana en la que el fichero sea legible."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
    os.replace(tmp, path)


def _cache_path(user_email: str) -> Path:
    safe = user_email.strip().lower().replace("@", "_").replace(".", "_")
    return TOKEN_DIR / f"{safe}.json"


# ── Bearers ──────────────────────────────────────────────────────────────────

_bearer_cache: dict[str, dict] = {}
_bearer_mtime: float = -1.0
_bearer_guard = threading.Lock()


def _hash_bearer(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _load_bearers() -> dict[str, dict]:
    """
    Lee bearers.json releyéndolo solo si ha cambiado en disco.

    Se relee por mtime en vez de cachear en memoria para siempre para que revocar un bearer
    (borrarlo del fichero con --revoke) tenga efecto inmediato, sin reiniciar el servicio.
    """
    global _bearer_cache, _bearer_mtime
    with _bearer_guard:
        try:
            mtime = BEARER_DB.stat().st_mtime
        except FileNotFoundError:
            _bearer_cache, _bearer_mtime = {}, -1.0
            return {}
        if mtime != _bearer_mtime:
            try:
                _bearer_cache = json.loads(BEARER_DB.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                audit("bearer_db_unreadable", error=str(exc))
                return {}
            _bearer_mtime = mtime
        return _bearer_cache


def _save_bearers(db: dict[str, dict]) -> None:
    global _bearer_mtime
    _write_private(BEARER_DB, json.dumps(db, indent=2, sort_keys=True))
    _bearer_mtime = -1.0        # forzar relectura


def _issue_bearer(user_email: str) -> str:
    """Emite un bearer nuevo para el usuario y revoca los que tuviera. Solo se devuelve aquí."""
    raw = secrets_mod.token_urlsafe(40)
    now = datetime.now(timezone.utc)
    with _bearer_guard:
        try:
            db = json.loads(BEARER_DB.read_text(encoding="utf-8")) if BEARER_DB.exists() else {}
        except (json.JSONDecodeError, OSError):
            db = {}
        # Un bearer vivo por usuario: volver a loguearse invalida el anterior, así que un
        # bearer filtrado se corta con un simple re-login del afectado.
        db = {h: meta for h, meta in db.items() if meta.get("user_email") != user_email}
        db[_hash_bearer(raw)] = {
            "user_email": user_email,
            "issued_at":  now.isoformat(timespec="seconds"),
            "expires_at": (now + timedelta(days=BEARER_TTL_DAYS)).isoformat(timespec="seconds"),
        }
        _save_bearers(db)
    audit("bearer_issued", user=user_email, ttl_days=BEARER_TTL_DAYS)
    return raw


def _revoke_bearers(user_email: str) -> int:
    with _bearer_guard:
        try:
            db = json.loads(BEARER_DB.read_text(encoding="utf-8")) if BEARER_DB.exists() else {}
        except (json.JSONDecodeError, OSError):
            db = {}
        keep = {h: m for h, m in db.items() if m.get("user_email") != user_email}
        removed = len(db) - len(keep)
        _save_bearers(keep)
    audit("bearer_revoked", user=user_email, count=removed)
    return removed


# ════════════════════════════════════════════════════════════════════════════
#  AUTENTICACIÓN DEL LLAMANTE
# ════════════════════════════════════════════════════════════════════════════

class HeuraTokenVerifier(TokenVerifier):
    """
    Valida el bearer que el hub emitió en /auth/callback.

    Se busca por sha256 del token presentado, así que el fichero no contiene material
    reutilizable: filtrarlo no permite suplantar a nadie.

    Este es el punto de extensión para la Fase 3 (identidad delegada): sustituir esta clase
    por una que valide un JWT de Entra ID contra el JWKS del tenant y saque el usuario de
    `upn`/`oid` deja intacto el resto del fichero. Ver delegated-auth-architecture.md.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        meta = _load_bearers().get(_hash_bearer(token))
        if not meta:
            audit("auth_rejected", reason="unknown_bearer")
            return None

        expires_at = meta.get("expires_at")
        if expires_at and datetime.fromisoformat(expires_at) < datetime.now(timezone.utc):
            audit("auth_rejected", reason="expired_bearer", user=meta.get("user_email"))
            return None

        user_email = meta["user_email"]
        return AccessToken(
            token=token,
            client_id=user_email,
            scopes=[MCP_SCOPE],
            subject=user_email,
            claims={"iss": PUBLIC_URL, "user_email": user_email},
        )


def _current_user() -> str:
    """
    Email del usuario autenticado en esta petición.

    Única fuente de identidad del servidor. Ninguna tool acepta el usuario como parámetro:
    ahí estaba el agujero de la versión anterior.
    """
    token = get_access_token()
    if token is None or not token.subject:
        raise ValueError(
            "Petición sin autenticar. El MCP requiere un bearer token; "
            f"haz login en {PUBLIC_URL}/auth/login."
        )
    return token.subject


# ════════════════════════════════════════════════════════════════════════════
#  MSAL / GRAPH
# ════════════════════════════════════════════════════════════════════════════

def _msal_app(cache: msal.SerializableTokenCache | None = None) -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=cache,
    )


class NoSessionError(ValueError):
    """El usuario está autenticado en el hub pero no hay caché de Graph utilizable."""


def _graph_token(user_email: str) -> str:
    """Devuelve un access token de Graph para el usuario, refrescándolo si hace falta."""
    path = _cache_path(user_email)
    with _user_lock(user_email):
        if not path.exists():
            raise NoSessionError(
                f"No hay sesión M365 para {user_email}. "
                f"Vuelve a hacer login en {PUBLIC_URL}/auth/login."
            )

        cache = msal.SerializableTokenCache()
        cache.deserialize(path.read_text(encoding="utf-8"))
        app = _msal_app(cache)

        accounts = app.get_accounts(username=user_email)
        if not accounts:
            raise NoSessionError(
                f"La sesión M365 de {user_email} ya no es válida. "
                f"Vuelve a hacer login en {PUBLIC_URL}/auth/login."
            )

        result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])
        if cache.has_state_changed:
            _write_private(path, cache.serialize())

    if not result or "access_token" not in result:
        # El cuerpo de `result` puede traer el error de Entra; se registra pero no se
        # devuelve al cliente, porque a veces incluye identificadores del tenant.
        audit("graph_token_failed", user=user_email,
              error=(result or {}).get("error"),
              description=(result or {}).get("error_description"))
        raise NoSessionError(
            f"No se pudo renovar la sesión M365 de {user_email}. "
            f"Vuelve a hacer login en {PUBLIC_URL}/auth/login."
        )
    return result["access_token"]


def _call(method: str, endpoint: str, tool: str = "", **kwargs):
    """
    Llama a Graph como el usuario autenticado en esta petición.

    A diferencia de la versión anterior, no recibe `user_email` ni `scopes`: el usuario sale
    del bearer y los scopes son siempre GRAPH_SCOPES.
    """
    user_email = _current_user()
    token   = _graph_token(user_email)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.request(method, f"{GRAPH}{endpoint}", headers=headers, timeout=60, **kwargs)

    if not r.ok:
        # raise_for_status() a secas se come el cuerpo de la respuesta, que es justo donde
        # Graph dice QUÉ cláusula OData ha rechazado. Sin esto, un 400 solo deja la URL y
        # hay que adivinar (nos pasó con list_todo_tasks). Se conserva response= para que
        # los except que miran e.response.status_code sigan funcionando.
        try:
            detail = ((r.json().get("error") or {}).get("message") or "").strip()
        except ValueError:
            detail = (r.text or "")[:300].strip()
        audit("graph_error", user=user_email, tool=tool, method=method,
              endpoint=endpoint, status=r.status_code)
        raise requests.exceptions.HTTPError(
            f"{r.status_code} {r.reason} en {method} {endpoint}"
            + (f" — {detail}" if detail else ""),
            response=r,
        )

    return r.json() if r.content else {}


mcp = FastMCP(
    "graph-heura",
    host=_env("HEURA_BIND_HOST", "127.0.0.1"),
    port=int(_env("HEURA_BIND_PORT", "3002")),
    streamable_http_path=MCP_PATH,
    # Sin estado de sesión: reiniciar el servicio no rompe a los clientes conectados y no
    # hace falta afinidad de sesión en el proxy si algún día hay más de una instancia.
    stateless_http=True,
    json_response=True,
    token_verifier=HeuraTokenVerifier(),
    auth=AuthSettings(
        issuer_url=PUBLIC_URL,                          # los bearers los emite este hub
        resource_server_url=f"{PUBLIC_URL}{MCP_PATH}",
        required_scopes=[MCP_SCOPE],
    ),
)


# ── CORREO ──────────────────────────────────────────────────────────────────

@mcp.tool()
def whoami() -> dict:
    """
    Devuelve el usuario M365 con el que el hub te ha autenticado.
    Útil como comprobación de sesión: si responde, el bearer y la sesión de Graph son válidos.
    """
    user_email = _current_user()
    me = _call("GET", "/me?$select=displayName,mail,userPrincipalName", tool="whoami")
    audit("tool", user=user_email, tool="whoami")
    return {
        "user_email":  user_email,
        "displayName": me.get("displayName"),
        "mail":        me.get("mail") or me.get("userPrincipalName"),
    }


@mcp.tool()
def send_email(to: str, subject: str, body: str,
               body_type: str = "HTML", cc: str = "") -> dict:
    """
    Envía un email en nombre del usuario autenticado.
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
    _call("POST", "/me/sendMail", tool="send_email", json={"message": msg})
    audit("tool", user=_current_user(), tool="send_email", to=to, subject=subject)
    return {"status": "enviado", "to": to, "subject": subject}


@mcp.tool()
def create_draft_email(to: str, subject: str, body: str,
                       body_type: str = "HTML", cc: str = "") -> dict:
    """
    Crea un borrador de email en la bandeja del usuario (no lo envía).
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
    result = _call("POST", "/me/messages", tool="create_draft_email", json=msg)
    audit("tool", user=_current_user(), tool="create_draft_email", to=to, subject=subject)
    return {"status": "borrador_creado", "id": result.get("id"), "to": to, "subject": subject}


@mcp.tool()
def send_draft_email(draft_id: str) -> dict:
    """
    Envía un borrador previamente creado con create_draft_email.
    - draft_id: el id devuelto por create_draft_email
    """
    _call("POST", f"/me/messages/{draft_id}/send", tool="send_draft_email")
    audit("tool", user=_current_user(), tool="send_draft_email", draft_id=draft_id)
    return {"status": "enviado", "draft_id": draft_id}


@mcp.tool()
def list_emails(top: int = 10, folder: str = "inbox",
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
    result = _call("GET", endpoint, tool="list_emails")
    audit("tool", user=_current_user(), tool="list_emails", folder=folder, top=top)
    return result.get("value", [])


@mcp.tool()
def list_attachments(message_id: str) -> list:
    """
    Lista los adjuntos de un correo (sin descargar su contenido).
    - message_id: id del correo (obtenido con list_emails)
    Devuelve id, name, contentType, size (bytes), isInline por cada adjunto.
    """
    endpoint = (f"/me/messages/{message_id}/attachments"
                "?$select=id,name,contentType,size,isInline")
    result = _call("GET", endpoint, tool="list_attachments")
    audit("tool", user=_current_user(), tool="list_attachments", message_id=message_id)
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
def get_attachment(message_id: str, attachment_id: str, max_mb: float = 10.0) -> dict:
    """
    Descarga un adjunto de tipo fichero y devuelve su contenido en base64.
    Claude debe decodificar 'content_base64' y guardarlo en disco para trabajarlo.
    - message_id: id del correo (list_emails)
    - attachment_id: id del adjunto (list_attachments)
    - max_mb: límite de tamaño; por encima devuelve error (usa OneDrive para ficheros grandes)
    """
    att = _call("GET", f"/me/messages/{message_id}/attachments/{attachment_id}",
                tool="get_attachment")
    odata = att.get("@odata.type", "")
    if "fileAttachment" not in odata:
        return {"error": f"Adjunto no descargable como fichero (tipo {odata}). "
                         "Solo se soportan fileAttachment."}
    size = att.get("size", 0)
    if size > max_mb * 1024 * 1024:
        return {"error": f"Adjunto demasiado grande ({size} bytes > {max_mb} MB). "
                         "Súbelo a OneDrive en su lugar."}
    audit("tool", user=_current_user(), tool="get_attachment",
          message_id=message_id, name=att.get("name"), size=size)
    return {
        "name": att.get("name"),
        "contentType": att.get("contentType"),
        "size": size,
        "content_base64": att.get("contentBytes", ""),
    }


# ── CALENDARIO ──────────────────────────────────────────────────────────────

@mcp.tool()
def list_calendar_events(days: int = 7) -> list:
    """
    Lista los próximos eventos del calendario del usuario.
    - days: cuántos días hacia adelante (default 7)
    """
    now = datetime.now(timezone.utc)
    start = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    end   = (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = _call(
        "GET",
        f"/me/calendarView?startDateTime={start}&endDateTime={end}"
        f"&$select=subject,start,end,location,attendees&$top=20&$orderby=start/dateTime",
        tool="list_calendar_events",
    )
    audit("tool", user=_current_user(), tool="list_calendar_events", days=days)
    return result.get("value", [])


@mcp.tool()
def create_calendar_event(subject: str, start: str, end: str, body: str = "",
                          attendees: str = "", location: str = "") -> dict:
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
    result = _call("POST", "/me/events", tool="create_calendar_event", json=payload)
    audit("tool", user=_current_user(), tool="create_calendar_event",
          subject=subject, start=start)
    return {"status": "creado", "id": result.get("id"), "subject": subject, "start": start}


# ── ONEDRIVE / SHAREPOINT ────────────────────────────────────────────────────

@mcp.tool()
def upload_file_to_onedrive(filename: str, content: str, folder_path: str = "") -> dict:
    """
    Crea o sobreescribe un archivo de texto en OneDrive del usuario.
    - folder_path: ruta dentro de OneDrive, ej: 'Documentos/Informes' (vacío = raíz)
    - content: contenido del fichero como texto plano o HTML
    """
    user_email = _current_user()
    token   = _graph_token(user_email)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "text/plain"}
    path    = f"/{folder_path}/{filename}".replace("//", "/")
    r = requests.put(f"{GRAPH}/me/drive/root:{path}:/content",
                     headers=headers, data=content.encode(), timeout=120)
    if not r.ok:
        audit("graph_error", user=user_email, tool="upload_file_to_onedrive",
              status=r.status_code)
        r.raise_for_status()
    result = r.json()
    audit("tool", user=user_email, tool="upload_file_to_onedrive", path=path)
    return {"status": "subido", "name": result.get("name"), "webUrl": result.get("webUrl")}


# ── TEAMS ────────────────────────────────────────────────────────────────────

@mcp.tool()
def send_teams_channel_message(team_id: str, channel_id: str, message: str) -> dict:
    """
    Envía un mensaje a un canal de Teams.
    - team_id: ID del equipo (GUID)
    - channel_id: ID del canal (GUID)
    """
    payload = {"body": {"contentType": "html", "content": message}}
    result  = _call("POST", f"/teams/{team_id}/channels/{channel_id}/messages",
                    tool="send_teams_channel_message", json=payload)
    audit("tool", user=_current_user(), tool="send_teams_channel_message",
          team_id=team_id, channel_id=channel_id)
    return {"status": "enviado", "id": result.get("id")}


@mcp.tool()
def send_teams_chat_message(chat_id: str, message: str) -> dict:
    """
    Envía un mensaje a un chat 1:1 o grupal de Teams.
    - chat_id: ID del chat (se obtiene de la URL del chat en Teams)
    """
    payload = {"body": {"contentType": "html", "content": message}}
    result  = _call("POST", f"/chats/{chat_id}/messages",
                    tool="send_teams_chat_message", json=payload)
    audit("tool", user=_current_user(), tool="send_teams_chat_message", chat_id=chat_id)
    return {"status": "enviado", "id": result.get("id")}


# ── MICROSOFT TO DO ──────────────────────────────────────────────────────────

def _flatten_todo_task(t: dict) -> dict:
    """Aplana un todoTask de Graph: dueDateTime a ISO simple y body a texto truncado."""
    due  = t.get("dueDateTime") or {}
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


def _default_todo_list_id() -> str:
    """Devuelve el id de la lista por defecto de To Do (o la primera si no existe)."""
    lists = _call("GET", "/me/todo/lists", tool="todo_lists").get("value", [])
    if not lists:
        raise ValueError(f"{_current_user()} no tiene ninguna lista de Microsoft To Do.")
    for l in lists:
        if l.get("wellknownListName") == "defaultList":
            return l["id"]
    return lists[0]["id"]


@mcp.tool()
def list_todo_lists() -> list:
    """
    Lista las listas de tareas de Microsoft To Do del usuario.
    Devuelve id, displayName, wellknownListName, isOwner, isShared por cada lista.
    La lista por defecto es la que tiene wellknownListName == 'defaultList'.
    """
    result = _call("GET", "/me/todo/lists", tool="list_todo_lists")
    audit("tool", user=_current_user(), tool="list_todo_lists")
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


def _fetch_todo_tasks(list_id: str, top: int) -> list:
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
                           tool="list_todo_tasks")
            return result.get("value", [])
        except requests.exceptions.HTTPError as e:
            # Solo un 400 (query mal formada) justifica degradar. Un 401/403 es de sesión
            # o de permisos y hay que propagarlo tal cual, no esconderlo tras 3 reintentos.
            if e.response is None or e.response.status_code != 400:
                raise
            last_error = e
    raise last_error


@mcp.tool()
def list_todo_tasks(list_id: str = "", top: int = 50,
                    include_completed: bool = False) -> list:
    """
    Lista las tareas de una lista de Microsoft To Do.
    - list_id: (opcional) id de la lista (list_todo_lists). Vacío = lista por defecto
    - top: cuántas tareas devolver (default 50)
    - include_completed: si True incluye también las tareas ya completadas
    Devuelve id, title, status, importance, dueDateTime, createdDateTime,
    lastModifiedDateTime y body truncado a 500 caracteres, más recientes primero.
    """
    if not list_id:
        list_id = _default_todo_list_id()

    tasks = _fetch_todo_tasks(list_id, top)
    if not include_completed:
        tasks = [t for t in tasks if t.get("status") != "completed"]
    tasks.sort(key=lambda t: t.get("createdDateTime") or "", reverse=True)
    audit("tool", user=_current_user(), tool="list_todo_tasks", list_id=list_id)
    return [_flatten_todo_task(t) for t in tasks[:top]]


@mcp.tool()
def get_todo_task(list_id: str, task_id: str) -> dict:
    """
    Devuelve una tarea de To Do con sus subelementos (checklist).
    - list_id: id de la lista (list_todo_lists)
    - task_id: id de la tarea (list_todo_tasks)
    """
    result = _call("GET", f"/me/todo/lists/{list_id}/tasks/{task_id}?$expand=checklistItems",
                   tool="get_todo_task")
    audit("tool", user=_current_user(), tool="get_todo_task", task_id=task_id)
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
def create_todo_task(title: str, list_id: str = "", due_date: str = "",
                     body: str = "", importance: str = "normal") -> dict:
    """
    Crea una tarea en Microsoft To Do.
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
        list_id = _default_todo_list_id()

    payload = {"title": title.strip(), "importance": importance}
    if due_date:
        payload["dueDateTime"] = _due_payload(due_date)
    if body:
        payload["body"] = {"contentType": "text", "content": body}

    result = _call("POST", f"/me/todo/lists/{list_id}/tasks",
                   tool="create_todo_task", json=payload)
    audit("tool", user=_current_user(), tool="create_todo_task", title=title.strip())
    return {"status": "creada", **_flatten_todo_task(result)}


@mcp.tool()
def update_todo_task(list_id: str, task_id: str, title: str = "", status: str = "",
                     due_date: str = "", body: str = "", importance: str = "") -> dict:
    """
    Modifica una tarea de To Do.
    Solo se envían a Graph los campos que se pasen; el resto queda intacto (PATCH).
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

    result = _call("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}",
                   tool="update_todo_task", json=payload)
    audit("tool", user=_current_user(), tool="update_todo_task",
          task_id=task_id, fields=sorted(payload))
    return {"status": "actualizada", **_flatten_todo_task(result)}


@mcp.tool()
def complete_todo_task(list_id: str, task_id: str) -> dict:
    """
    Marca una tarea de To Do como completada.
    Alternativa REVERSIBLE a delete_todo_task: para quitar una tarea de en medio, esta es la
    opción a preferir salvo que se quiera borrarla de verdad.
    - list_id / task_id: ids (list_todo_lists / list_todo_tasks)
    """
    return update_todo_task(list_id, task_id, status="completed")


@mcp.tool()
def delete_todo_task(list_id: str, task_id: str, expected_title: str) -> dict:
    """
    BORRA una tarea de To Do de forma DEFINITIVA.
    To Do no tiene papelera: lo borrado no se recupera. Si solo se quiere quitar la tarea de
    la vista, usar complete_todo_task, que es reversible.
    - list_id / task_id: ids (list_todo_lists / list_todo_tasks)
    - expected_title: título exacto que se espera que tenga la tarea. Obligatorio: se lee la
      tarea y se aborta si no coincide. Un task_id copiado de un listado viejo apunta a otra
      tarea si la lista ha cambiado, y aquí ese error no se puede deshacer.
    """
    if not expected_title.strip():
        raise ValueError("expected_title es obligatorio para poder confirmar qué se borra.")

    current = _call("GET", f"/me/todo/lists/{list_id}/tasks/{task_id}", tool="delete_todo_task")
    actual  = (current.get("title") or "").strip()
    if actual != expected_title.strip():
        raise ValueError(
            f"Abortado: la tarea {task_id} se titula {actual!r}, no {expected_title.strip()!r}. "
            "Vuelve a listar las tareas para coger el id correcto."
        )

    _call("DELETE", f"/me/todo/lists/{list_id}/tasks/{task_id}", tool="delete_todo_task")
    audit("tool", user=_current_user(), tool="delete_todo_task",
          task_id=task_id, title=actual)
    return {"status": "borrada", "id": task_id, "title": actual}


# ════════════════════════════════════════════════════════════════════════════
#  LOGIN (Authorization Code + PKCE contra Entra ID)
# ════════════════════════════════════════════════════════════════════════════
# Sustituye a graph_login_remote.py y al endpoint /register con secreto compartido. Estas
# rutas van por `custom_route`, que el SDK deja fuera de RequireAuthMiddleware: tienen que
# ser públicas, porque son justamente por donde se obtiene el bearer.

_pending_flows: dict[str, tuple[dict, float]] = {}
_flows_guard = threading.Lock()


def _remember_flow(flow: dict) -> bool:
    """Guarda el flow pendiente. Devuelve False si se ha alcanzado el tope."""
    now = time.time()
    with _flows_guard:
        # Purgar los logins que nadie terminó antes de añadir el nuevo.
        for state in [s for s, (_, born) in _pending_flows.items() if now - born > LOGIN_FLOW_TTL]:
            del _pending_flows[state]
        if len(_pending_flows) >= MAX_PENDING_FLOWS:
            return False
        _pending_flows[flow["state"]] = (flow, now)
        return True


def _take_flow(state: str) -> dict | None:
    with _flows_guard:
        entry = _pending_flows.pop(state, None)
    if entry is None:
        return None
    flow, born = entry
    return None if time.time() - born > LOGIN_FLOW_TTL else flow


def _page(title: str, body_html: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        f"<title>{title}</title>"
        "<style>"
        "body{font:15px/1.6 system-ui,sans-serif;background:#f1f3ef;color:#151d18;"
        "margin:0;padding:48px 20px}"
        "main{max-width:620px;margin:0 auto;background:#fff;border:1px solid #d5dad2;"
        "border-radius:6px;padding:28px 30px}"
        "h1{font-size:1.35rem;margin:0 0 14px}"
        "code,pre{font-family:ui-monospace,monospace;background:#e8ebe5;border:1px solid #d5dad2;"
        "border-radius:4px}"
        "code{padding:.12em .35em;font-size:.9em}"
        "pre{padding:12px 14px;overflow-x:auto;font-size:.85rem;white-space:pre-wrap;"
        "word-break:break-all}"
        ".warn{color:#9a3025;font-weight:600}"
        "</style>"
        f"<main>{body_html}</main>",
        status_code=status,
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    """
    Comprobación de vida para el chequeo externo. Pública y sin datos sensibles: solo dice
    que el proceso está en pie y que el estado en disco es accesible.
    """
    try:
        sessions = len(list(TOKEN_DIR.glob("*.json")))
        writable = os.access(STATE_DIR, os.W_OK)
    except OSError as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)

    ok = writable
    return JSONResponse(
        {
            "status": "ok" if ok else "degraded",
            "service": "graph-heura",
            "sessions": sessions,
            "state_writable": writable,
        },
        status_code=200 if ok else 503,
    )


@mcp.custom_route("/auth/login", methods=["GET"])
async def auth_login(request: Request) -> Response:
    """Arranca el login de M365. El usuario abre esta URL en su navegador."""
    app  = _msal_app()
    flow = app.initiate_auth_code_flow(GRAPH_SCOPES, redirect_uri=REDIRECT_URI)
    if "auth_uri" not in flow:
        audit("login_start_failed", error=flow.get("error"))
        return _page("Error", "<h1>No se pudo iniciar el login</h1>"
                              "<p>Avisa a IT (it@heurafoods.com).</p>", status=500)
    if not _remember_flow(flow):
        audit("login_throttled", pending=MAX_PENDING_FLOWS)
        return _page("Inténtalo en un momento",
                     "<h1>Hay demasiados logins en curso</h1>"
                     "<p>Espera unos minutos y vuelve a intentarlo. Si se repite, avisa a "
                     "IT (it@heurafoods.com).</p>", status=503)
    audit("login_start")
    return RedirectResponse(flow["auth_uri"], status_code=302)


@mcp.custom_route("/auth/callback", methods=["GET"])
async def auth_callback(request: Request) -> Response:
    """
    Vuelta de Entra ID: canjea el código, guarda la caché de Graph y emite el bearer.
    El bearer se muestra UNA vez; no queda recuperable (en disco solo está su sha256).
    """
    params = dict(request.query_params)

    if "error" in params:
        audit("login_failed", error=params.get("error"))
        return _page("Login cancelado",
                     "<h1>Login cancelado</h1>"
                     f"<p>Entra ID devolvió <code>{html.escape(params.get('error', ''))}</code>. "
                     "Vuelve a intentarlo.</p>", status=400)

    flow = _take_flow(params.get("state", ""))
    if flow is None:
        return _page("Login caducado",
                     "<h1>El login ha caducado</h1>"
                     f'<p>Vuelve a empezar en <a href="{PUBLIC_URL}/auth/login">'
                     f"{PUBLIC_URL}/auth/login</a>.</p>", status=400)

    cache  = msal.SerializableTokenCache()
    app    = _msal_app(cache)
    result = app.acquire_token_by_auth_code_flow(flow, params, scopes=GRAPH_SCOPES)

    if "access_token" not in result:
        audit("login_failed", error=result.get("error"),
              description=result.get("error_description"))
        return _page("Error de login",
                     "<h1>No se pudo completar el login</h1>"
                     "<p>Vuelve a intentarlo. Si persiste, avisa a IT "
                     "(it@heurafoods.com).</p>", status=400)

    claims     = result.get("id_token_claims") or {}
    user_email = (claims.get("preferred_username") or claims.get("upn") or "").strip().lower()

    if not user_email:
        audit("login_failed", error="no_username_claim")
        return _page("Error de login",
                     "<h1>No se pudo identificar al usuario</h1>"
                     "<p>Avisa a IT (it@heurafoods.com).</p>", status=400)

    # El App Registration es single-tenant, pero el dominio se comprueba igualmente: una
    # cuenta invitada del tenant no debe poder darse de alta en el hub.
    domain = user_email.rpartition("@")[2]
    if domain not in ALLOWED_DOMAINS:
        audit("login_denied", user=user_email, reason="domain_not_allowed")
        return _page("Acceso denegado",
                     "<h1>Acceso denegado</h1>"
                     f"<p>La cuenta <code>{html.escape(user_email)}</code> no pertenece a un "
                     "dominio "
                     "autorizado.</p>", status=403)

    _ensure_state_dirs()
    _write_private(_cache_path(user_email), cache.serialize())
    bearer = _issue_bearer(user_email)
    audit("login_ok", user=user_email)

    return _page(
        "Sesión M365 lista",
        f"<h1>Listo, {html.escape(user_email)}</h1>"
        "<p>Tu sesión de M365 ya está registrada en el hub. Para que Claude Code pueda "
        "usarla, guarda este token como variable de entorno. "
        "<span class='warn'>Solo se muestra esta vez.</span></p>"
        "<p><strong>Windows</strong> (PowerShell, y luego reinicia Claude Code):</p>"
        f"<pre>setx HEURA_MCP_TOKEN {bearer}</pre>"
        "<p><strong>macOS / Linux</strong> (añádelo a tu <code>~/.zshrc</code> o "
        "<code>~/.bashrc</code>):</p>"
        f"<pre>export HEURA_MCP_TOKEN={bearer}</pre>"
        "<p>Trátalo como una contraseña: permite actuar sobre tu correo, calendario, Teams "
        "y tareas. Si se te escapa, vuelve a hacer login aquí y el anterior queda "
        "invalidado.</p>"
        f'<p>¿Problemas? <a href="mailto:it@heurafoods.com">it@heurafoods.com</a></p>',
    )


# ════════════════════════════════════════════════════════════════════════════
#  ARRANQUE Y ADMINISTRACIÓN
# ════════════════════════════════════════════════════════════════════════════

def _admin_cli(argv: list[str]) -> int:
    """Operaciones de mantenimiento para IT. No arranca el servidor."""
    command = argv[0]

    if command == "--list-sessions":
        # El censo sale de los bearers, no de los ficheros de caché: un usuario que hizo
        # login pero cuya caché se borró (o al revés) tiene que aparecer, porque es
        # justamente el estado que hay que diagnosticar.
        bearers = {m["user_email"]: m for m in _load_bearers().values()}
        cached  = {p.name: p for p in TOKEN_DIR.glob("*.json")}
        users   = sorted(set(bearers) | {
            e for e in bearers if _cache_path(e).name in cached
        })
        # Cachés sin bearer conocido: se listan por nombre de fichero para que no pasen
        # desapercibidas al limpiar.
        orphans = sorted(set(cached) - {_cache_path(e).name for e in bearers})

        if not users and not orphans:
            print("Sin sesiones registradas.")
        for email in users:
            meta  = bearers.get(email, {})
            cache = _cache_path(email)
            stamp = (f"{datetime.fromtimestamp(cache.stat().st_mtime, timezone.utc):%Y-%m-%d}"
                     if cache.exists() else "NINGUNA")
            print(f"{email:40s} cache={stamp:10s} "
                  f"bearer={'sí' if meta else 'NO':3s} "
                  f"expira={meta.get('expires_at', '-')}")
        for name in orphans:
            print(f"{'(caché huérfana)':40s} fichero={name}")
        return 0

    if command == "--revoke":
        if len(argv) < 2:
            print("Uso: --revoke <email>", file=sys.stderr)
            return 2
        email = argv[1].strip().lower()
        removed = _revoke_bearers(email)
        cache = _cache_path(email)
        if cache.exists():
            cache.unlink()
        print(f"{email}: {removed} bearer(s) revocado(s), caché de Graph borrada.")
        print("El usuario tendrá que volver a hacer login para recuperar el acceso.")
        return 0

    print(__doc__)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(_admin_cli(sys.argv[1:]))

    _ensure_state_dirs()
    audit("startup", public_url=PUBLIC_URL, mcp_path=MCP_PATH, state_dir=str(STATE_DIR))
    mcp.run(transport="streamable-http")
