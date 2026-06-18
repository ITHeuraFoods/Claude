"""
odoo_login.py — Inicio de sesión Odoo (alternativa por consola)
================================================================
Pide usuario y contraseña Odoo, valida y guarda SOLO el cookie session_id.
La contraseña nunca se almacena.

    python odoo_login.py        # iniciar sesión
    python odoo_login.py --out  # cerrar sesión (borra el token)
"""
import os, sys, io, json, getpass, tempfile
import requests

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ODOO_URL   = 'https://erp.heurafoods.com'
ODOO_DB    = 'heura_2024_06_28'
TOKEN_FILE = os.path.join(tempfile.gettempdir(), '.odoo_session_heura.json')


def logout():
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
        print('Sesión cerrada (token borrado).')
    else:
        print('No había sesión activa.')


def login():
    user = input('Usuario Odoo (email): ')
    pwd  = getpass.getpass('Contraseña Odoo: ')

    s = requests.Session()
    print('Validando contra Odoo...')
    r = s.post(f'{ODOO_URL}/web/session/authenticate', json={
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'db': ODOO_DB, 'login': user, 'password': pwd}
    }, timeout=30)
    res = r.json()
    uid = res.get('result', {}).get('uid')
    if not uid:
        print('ERROR: credenciales inválidas.')
        sys.exit(1)

    cookies = {c.name: c.value for c in s.cookies}
    if 'session_id' not in cookies:
        print('ADVERTENCIA: Odoo no devolvió session_id. Reintenta.')
        sys.exit(1)

    with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
        json.dump({'user': user, 'uid': uid, 'cookies': cookies}, f)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass

    print(f'Sesión iniciada como {user} (uid {uid}). Token guardado temporalmente.')
    print('Ya puedes pedirle a Claude consultas sobre Odoo.')


if __name__ == '__main__':
    if '--out' in sys.argv or '--logout' in sys.argv:
        logout()
    else:
        login()
