"""
Autenticacion e identidad para los MCP de Heura.  Fase 05, nivel tactico.

Problema que resuelve
---------------------
Las tools de Graph reciben `user_email` como parametro libre.  El servidor
guarda en disco las cachees MSAL de toda la organizacion, asi que cualquiera
que alcanzase el puerto podia pedir send_email(user_email="otra@persona") y el
servidor lo hacia.  No habia nada que atase la llamada a quien la hace.

Como lo resuelve
----------------
Middleware ASGI delante de la app del MCP:

  1. Exige `Authorization: Bearer <token>`.  El token identifica a la persona.
  2. Para `tools/call`, si los argumentos traen `user_email`, comprueba que
     coincide con la identidad del token.  Si no, 403 y no llega al MCP.
  3. Registra cada llamada: identidad, metodo, tool y resultado.

Se hace en el middleware, no dentro de las tools, por dos razones: no hay que
tocar el codigo de las 14 tools existentes, y las ContextVar no propagan de
forma fiable hasta las tools porque el session manager de streamable-http las
ejecuta en otro task group.

El mapa de tokens guarda solo el SHA-256, nunca el token en claro.  Se recarga
en caliente al cambiar el fichero: anadir a alguien no requiere reiniciar.
"""

import hashlib
import json
import logging
import os
import time

log = logging.getLogger("heura.auth")

# Dos fuentes, ambas con el mismo formato "sha256(token):email":
#   ADMIN_MAP  altas manuales de IT con heura-mcp-token.
#   ISSUED_MAP autoservicio: lo escribe /register tras autenticar a la persona
#              contra Entra. Solo el servicio de Graph puede escribirlo; el de
#              SAP lo lee por el grupo mcpauth.
ADMIN_MAP  = os.environ.get("HEURA_TOKEN_MAP", "/etc/heura-mcp/tokens.map")
ISSUED_MAP = os.environ.get("HEURA_ISSUED_MAP", "/var/lib/heura-mcp/auth/issued.map")
TOKEN_MAP = ADMIN_MAP  # compatibilidad


class _TokenMap:
    """Cache de sha256(token) -> email sobre varios ficheros, recargada al vuelo."""

    def __init__(self, *paths):
        self.paths = [p for p in paths if p]
        self._stamp = None
        self._map = {}

    def _stamp_now(self):
        out = []
        for p in self.paths:
            try:
                out.append(os.stat(p).st_mtime)
            except FileNotFoundError:
                out.append(None)
        return tuple(out)

    def _reload_if_needed(self):
        stamp = self._stamp_now()
        if stamp == self._stamp:
            return
        new = {}
        for p in self.paths:
            try:
                f = open(p, encoding="utf-8")
            except (FileNotFoundError, PermissionError):
                continue
            with f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    digest, _, email = line.partition(":")
                    if digest and email:
                        new[digest.strip().lower()] = email.strip().lower()
        self._map = new
        self._stamp = stamp
        log.info("mapa de tokens recargado: %d identidades", len(new))

    def identity_for(self, token):
        self._reload_if_needed()
        if not token:
            return None
        return self._map.get(hashlib.sha256(token.encode()).hexdigest())


def _deny(status, message):
    body = json.dumps({"error": message}).encode()
    return status, body


class HeuraAuth:
    """
    Envuelve la app ASGI del MCP.

    service           nombre para el log ("graph" o "sap")
    enforce_user_email  si True, `user_email` en los argumentos tiene que
                        coincidir con la identidad autenticada.
    """

    def __init__(self, app, service, enforce_user_email=True, token_map=TOKEN_MAP):
        self.app = app
        self.service = service
        self.enforce = enforce_user_email
        self.tokens = _TokenMap(token_map, ISSUED_MAP)

    async def _respond(self, send, status, body):
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth = headers.get(b"authorization", b"").decode("latin-1")
        token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
        identity = self.tokens.identity_for(token)

        if identity is None:
            log.warning("%s: 401 sin token valido desde %s", self.service,
                        scope.get("client", ("?",))[0])
            status, body = _deny(401, "Falta o no es valido el Authorization: Bearer")
            return await self._respond(send, status, body)

        # Sin cuerpo que inspeccionar (GET del stream SSE, DELETE de la sesion).
        if scope.get("method") not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)

        # Bufferamos el cuerpo para poder inspeccionarlo y reinyectarlo intacto.
        chunks = []
        more = True
        while more:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            chunks.append(msg.get("body", b""))
            more = msg.get("more_body", False)
        raw = b"".join(chunks)

        verdict = self._inspect(raw, identity)
        if verdict is not None:
            status, body = verdict
            return await self._respond(send, status, body)

        sent = False

        async def replay():
            # Tras devolver el cuerpo bufferado hay que delegar en el receive
            # ORIGINAL, no devolver http.disconnect: la app sigue llamando a
            # receive mientras emite el stream SSE, y un disconnect falso le
            # hace abortar la respuesta a medias (sintoma: 200 con cuerpo vacio).
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)

    def _inspect(self, raw, identity):
        """Devuelve None si se permite, o (status, body) si se rechaza."""
        try:
            msg = json.loads(raw) if raw else {}
        except ValueError:
            return None  # no es JSON: que lo rechace el MCP con su propio error

        for m in (msg if isinstance(msg, list) else [msg]):
            if not isinstance(m, dict):
                continue
            method = m.get("method", "")
            params = m.get("params") or {}
            tool = params.get("name", "")
            args = params.get("arguments") or {}

            if method == "tools/call" and self.enforce:
                requested = str(args.get("user_email", "")).strip().lower()
                if requested and requested != identity:
                    log.warning(
                        "%s: 403 %s intento actuar como %s en la tool %s",
                        self.service, identity, requested, tool)
                    return _deny(403, f"El token de {identity} no puede actuar como {requested}")

            if method:
                log.info("%s: %s %s%s", self.service, identity, method,
                         f" tool={tool}" if tool else "")
        return None


# -- Emision de tokens (autoservicio desde /register) ------------------------

def identity_from_msal_cache(token_cache):
    """
    Saca el correo de la propia cache MSAL.

    Es la pieza que cierra el agujero de /register: hasta ahora el handler se
    creia el `user_email` del cuerpo, asi que quien conociera el secreto
    compartido podia sobrescribir la entrada de otra persona. La cache la emite
    Entra tras un login interactivo, asi que solo se puede presentar una de una
    identidad con la que realmente sabes autenticarte.
    """
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


def issue_token(email):
    """Emite un token para `email`, sustituyendo el anterior si lo hubiera.

    Escritura atomica con fichero temporal y os.replace: si dos personas se
    registran a la vez, ninguna se queda con el mapa a medias.
    """
    import secrets
    email = email.strip().lower()
    token = secrets.token_hex(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    sufijo = ":" + email

    lineas = []
    if os.path.exists(ISSUED_MAP):
        with open(ISSUED_MAP, encoding="utf-8") as f:
            for linea in f.read().splitlines():
                if linea.strip() and not linea.strip().endswith(sufijo):
                    lineas.append(linea)
    lineas.append(digest + sufijo)

    tmp = ISSUED_MAP + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for linea in lineas:
            f.write(linea)
            f.write(chr(10))
    os.chmod(tmp, 0o640)
    os.replace(tmp, ISSUED_MAP)
    log.info("token emitido para %s", email)
    return token
