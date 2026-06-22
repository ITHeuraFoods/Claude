"""
Ejecutar en el laptop del usuario para registrar su sesión M365 en el servidor MCP.
Requiere: pip install msal requests
"""
import msal
import requests
import os
import sys

CLIENT_ID  = "1f5ff61e-43dc-48fe-af84-d9c3f558dbcc"
TENANT_ID  = "4ff8acc2-4c1a-49ba-9344-9e47d370f6fc"
AUTHORITY  = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES     = ["Mail.Send", "Mail.ReadWrite", "Calendars.ReadWrite",
              "Files.ReadWrite.All", "Chat.ReadWrite", "ChannelMessage.Send"]

SERVER_URL = os.environ.get("HEURA_MCP_URL", "http://laptop-itadm:3003")
SECRET     = os.environ.get("HEURA_REGISTER_SECRET", "")

if not SECRET:
    print("ERROR: define la variable de entorno HEURA_REGISTER_SECRET")
    print("  set HEURA_REGISTER_SECRET=<secreto>  && python graph_login_remote.py")
    sys.exit(1)

cache = msal.SerializableTokenCache()
app   = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

print("Abriendo navegador para autenticación M365...")
result = app.acquire_token_interactive(scopes=SCOPES)

if "error" in result:
    print(f"Error de autenticación: {result.get('error_description', result['error'])}")
    sys.exit(1)

accounts = app.get_accounts()
user_email = accounts[0]["username"] if accounts else result.get("id_token_claims", {}).get("preferred_username", "")

print(f"Autenticado como: {user_email}")
print("Enviando token al servidor MCP...")

r = requests.post(
    f"{SERVER_URL}/register",
    json={"user_email": user_email, "token_cache": cache.serialize()},
    headers={"X-Heura-Secret": SECRET},
    timeout=10,
)

if r.ok:
    print(f"Listo. Sesión M365 registrada para {user_email}")
else:
    print(f"Error al registrar: {r.status_code} {r.text}")
    sys.exit(1)
