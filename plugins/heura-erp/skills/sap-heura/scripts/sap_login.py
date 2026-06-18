"""
sap_login.py — Inicio de sesión SAP (ejecútalo TÚ en tu terminal)
==================================================================
Pide tu usuario y contraseña SAP, valida contra el sistema y guarda
ÚNICAMENTE el token de sesión temporal (cookie). Tu contraseña NUNCA
se almacena ni se muestra a Claude.

    python sap_login.py        # iniciar sesión
    python sap_login.py --out  # cerrar sesión (borra el token)

El token caduca solo (sesión SAP). Vuelve a loguearte cuando expire.
"""
import os, sys, io, json, getpass, warnings, tempfile
import requests

warnings.filterwarnings('ignore')
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SAP_HOST   = 'https://10.3.2.48:44300'
SAP_VHOST  = 'vhfftps4ci.sap.heurafoods.com'
SAP_CLIENT = '100'
TOKEN_FILE = os.path.join(tempfile.gettempdir(), '.sap_session_heura.json')
TEST_URL   = f'{SAP_HOST}/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder?$top=1'

def logout():
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
        print('Sesión cerrada (token borrado).')
    else:
        print('No había sesión activa.')

def login():
    user = input('Usuario SAP: ')
    pwd  = getpass.getpass('Contraseña SAP: ')

    s = requests.Session()
    s.auth   = (user, pwd)
    s.verify = False
    s.headers.update({'sap-client': SAP_CLIENT, 'Host': SAP_VHOST, 'Accept': 'application/json'})

    print('Validando contra SAP...')
    r = s.get(TEST_URL, timeout=30)
    if r.status_code != 200:
        print(f'ERROR {r.status_code}: credenciales inválidas o sin acceso.')
        sys.exit(1)

    # Guardar SOLO las cookies de sesión (no la contraseña)
    cookies = {c.name: c.value for c in s.cookies}
    if not any(n.startswith('SAP_SESSIONID') for n in cookies):
        print('ADVERTENCIA: SAP no emitió cookie de sesión. Reintenta.')
        sys.exit(1)

    with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
        json.dump({'user': user, 'cookies': cookies}, f)
    # permisos solo-usuario (best effort en Windows)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass

    print(f'Sesión iniciada como {user}. Token guardado temporalmente.')
    print('Ya puedes pedirle a Claude consultas sobre SAP.')

if __name__ == '__main__':
    if '--out' in sys.argv or '--logout' in sys.argv:
        logout()
    else:
        login()
