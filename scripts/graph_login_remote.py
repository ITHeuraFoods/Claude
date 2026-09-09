"""
Conectar la cuenta M365 de una persona con los MCP de Heura.

Un solo paso para el usuario: doble clic, login de Microsoft, listo.

Lo que hace por dentro:
  1. Login interactivo contra Entra (MSAL, authorization code + PKCE).
     NO device code: el tenant lo tiene bloqueado por politica de Acceso
     Condicional ("Microsoft-managed: Block device code flow"), asi que el
     login tiene que ocurrir en el equipo de la persona, con navegador.
  2. Manda la cache de tokens al endpoint /register del hub MCP.
  3. El servidor deduce la identidad DE LA PROPIA CACHE, registra la sesion y
     devuelve un token de acceso a los MCP para esa persona.
  4. Escribe ese token en las configuraciones locales de Claude y garantiza la
     entrada en la configuracion de usuario, que es la que sobrevive a un
     /plugin update.

Volver a ejecutarlo rota el token y reescribe la configuracion: es lo que hay
que hacer si alguien cambia de equipo o cree que su token se ha filtrado.
"""

import json
import os
import sys
from pathlib import Path

import msal
import requests

CLIENT_ID = "1f5ff61e-43dc-48fe-af84-d9c3f558dbcc"
TENANT_ID = "4ff8acc2-4c1a-49ba-9344-9e47d370f6fc"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES    = ["Mail.Send", "Mail.ReadWrite", "Calendars.ReadWrite",
             "Files.ReadWrite.All", "Chat.ReadWrite", "ChannelMessage.Send",
             "Tasks.Read"]

# Hub MCP en Hetzner, alcanzable por la LAN de Heura o por la SSL-VPN.
# Cuando exista el registro DNS, cambiar solo estas constantes.
MCP_HOST     = os.environ.get("HEURA_MCP_HOST", "10.99.0.10")
REGISTER_URL = os.environ.get("HEURA_MCP_URL", f"http://{MCP_HOST}:3003")
SERVERS      = {"sap-heura-remote":   f"http://{MCP_HOST}:3001/mcp",
                "graph-heura-remote": f"http://{MCP_HOST}:3002/mcp"}

SECRET = os.environ.get("HEURA_REGISTER_SECRET", "")

SETTINGS = Path.home() / ".claude" / "settings.json"


def salir(msg, codigo=1):
    print(f"\n{msg}\n")
    sys.exit(codigo)


def configs_existentes():
    """Ficheros de configuracion de Claude que pueden llevar estos servidores.

    Se tocan todos los que existan, no solo uno: la configuracion de usuario
    tiene prioridad sobre la del plugin, y una entrada vieja olvidada en
    .claude.json deja al cliente hablando con un servidor que ya no existe.
    Ese error costo una tarde entera de depuracion el 2026-09-08.
    """
    home = Path.home()
    appdata = os.environ.get("APPDATA")
    rutas = [
        home / ".claude" / "plugins" / "marketplaces" / "heura" / "plugins" / "heura-erp" / ".mcp.json",
        SETTINGS,
        home / ".claude.json",
    ]
    if appdata:
        rutas.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
    return [r for r in rutas if r.is_file()]


def _respaldar(ruta):
    try:
        ruta.with_suffix(ruta.suffix + ".bak").write_text(
            ruta.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass


def parchear(ruta, token):
    """Pone url + cabecera en cada bloque mcpServers que ya exista."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"  ! {ruta.name}: no se pudo leer ({exc})")
        return 0

    tocados = 0

    def recorrer(nodo):
        nonlocal tocados
        if not isinstance(nodo, dict):
            return
        for clave, valor in nodo.items():
            if clave == "mcpServers" and isinstance(valor, dict):
                for nombre, srv in valor.items():
                    if nombre in SERVERS and isinstance(srv, dict):
                        srv["type"] = "http"
                        srv["url"] = SERVERS[nombre]
                        srv.setdefault("headers", {})["Authorization"] = f"Bearer {token}"
                        tocados += 1
            else:
                recorrer(valor)

    recorrer(datos)

    if tocados:
        _respaldar(ruta)
        ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return tocados


def asegurar_en_settings(token):
    """Crea los servidores en ~/.claude/settings.json si no estaban.

    Es la configuracion de USUARIO: tiene prioridad y, sobre todo, es la unica
    que sobrevive a un /plugin update. El .mcp.json del plugin se reescribe al
    actualizar el marketplace y se llevaria el token por delante.
    """
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)

    if SETTINGS.is_file():
        try:
            datos = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except ValueError:
            print(f"  ! {SETTINGS} no es JSON valido, no lo toco")
            return 0
    else:
        datos = {}

    if not isinstance(datos.get("mcpServers"), dict):
        datos["mcpServers"] = {}

    creadas = 0
    for nombre, url in SERVERS.items():
        if nombre not in datos["mcpServers"]:
            datos["mcpServers"][nombre] = {
                "type": "http",
                "url": url,
                "headers": {"Authorization": f"Bearer {token}"},
            }
            creadas += 1

    if creadas:
        if SETTINGS.is_file():
            _respaldar(SETTINGS)
        SETTINGS.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    return creadas


def main():
    if not SECRET:
        salir("ERROR: falta la variable de entorno HEURA_REGISTER_SECRET.\n"
              "Usa el acceso directo 'Conectar M365 con Claude' del escritorio.")

    print("Abriendo el navegador para el login de Microsoft...")
    cache = msal.SerializableTokenCache()
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
    resultado = app.acquire_token_interactive(scopes=SCOPES)

    if "error" in resultado:
        salir("Error de autenticacion: "
              f"{resultado.get('error_description', resultado['error'])}")

    cuentas = app.get_accounts()
    quien = (cuentas[0]["username"] if cuentas
             else resultado.get("id_token_claims", {}).get("preferred_username", "?"))
    print(f"Autenticado como {quien}")

    print(f"Registrando la sesion en {REGISTER_URL} ...")
    try:
        r = requests.post(
            f"{REGISTER_URL}/register",
            json={"user_email": quien, "token_cache": cache.serialize()},
            headers={"X-Heura-Secret": SECRET},
            timeout=20,
        )
    except requests.RequestException as exc:
        salir("No se ha podido contactar con el hub MCP.\n"
              "Comprueba que tienes la VPN de Heura conectada.\n"
              f"Detalle: {exc}")

    if not r.ok:
        salir(f"El servidor rechazo el registro: {r.status_code} {r.text}")

    respuesta = r.json()
    identidad = respuesta.get("user", quien)
    token = respuesta.get("token")
    print(f"Sesion registrada para {identidad}")

    if not token:
        salir("La sesion quedo registrada, pero el servidor no emitio token.\n"
              "Avisa a IT: hay que revisar /var/lib/heura-mcp/auth en el hub.", 2)

    print("Actualizando la configuracion local de Claude...")
    total = 0
    for ruta in configs_existentes():
        n = parchear(ruta, token)
        if n:
            print(f"  - {ruta}: {n} servidor(es)")
            total += n

    creadas = asegurar_en_settings(token)
    if creadas:
        print(f"  - {SETTINGS}: {creadas} servidor(es) creados")
        total += creadas

    print(f"\nListo. {total} entradas escritas.")
    print("REINICIA Claude para que recoja los cambios.")


if __name__ == "__main__":
    main()
