"""
============================================================================
  HEURA · Odoo Connector
  Consulta Odoo (ERP) en lenguaje natural a través de Claude
============================================================================

Ábrelo dentro de Claude y pregunta en lenguaje natural, p.ej.:

    "Compras al proveedor LA SIRENA este año"
    "Ventas del producto 100020 en 2024"
    "Facturas de proveedor pendientes de pago"
    "Stock actual del producto 100020"

Claude lee el CATÁLOGO de modelos, construye la consulta y ejecuta query().

REQUISITOS
----------
    pip install requests
    Acceso a https://erp.heurafoods.com

SEGURIDAD
---------
No contiene credenciales. Usa el token de sesión guardado por odoo_login
(solo se guarda el cookie session_id, nunca la contraseña).
============================================================================
"""
import os
import sys
import io
import json
import getpass
import tempfile

import requests

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ════════════════════════════════════════════════════════════════════════════
#  CONEXIÓN
# ════════════════════════════════════════════════════════════════════════════
ODOO_URL   = 'https://erp.heurafoods.com'
ODOO_DB    = 'heura_2024_06_28'
TOKEN_FILE = os.path.join(tempfile.gettempdir(), '.odoo_session_heura.json')

_session = None


class NoSessionError(Exception):
    """No hay sesión Odoo activa. Claude debe lanzar odoo_login.ps1."""
    pass


def connect(user=None, password=None, interactive=False):
    """
    Crea la sesión Odoo. Prioridad:
      1. Token de sesión guardado por el login (cookie session_id, sin contraseña)
      2. Credenciales por argumento o entorno ODOO_USER / ODOO_PASS
      3. Input interactivo SOLO si interactive=True

    Si no hay token ni credenciales y interactive=False, lanza NoSessionError
    en lugar de colgarse pidiendo input().
    """
    global _session
    s = requests.Session()

    # 1) token de sesión
    if not user and not password and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding='utf-8') as f:
            data = json.load(f)
        for name, value in data.get('cookies', {}).items():
            s.cookies.set(name, value)
        _session = s
        return s

    # 2) credenciales explícitas / entorno
    user     = user     or os.environ.get('ODOO_USER')
    password = password or os.environ.get('ODOO_PASS')

    # 3) sin token ni credenciales
    if not user or not password:
        if not interactive:
            raise NoSessionError(
                'No hay sesión Odoo activa. Lanza la ventana de login: '
                'Start-Process pwsh -ArgumentList "-NoProfile","-File","scripts/odoo_login.ps1" -Wait'
            )
        if not user:
            user = input('Usuario Odoo (email): ')
        if not password:
            password = getpass.getpass('Contraseña Odoo: ')

    # autenticar para obtener session_id
    r = s.post(f'{ODOO_URL}/web/session/authenticate', json={
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'db': ODOO_DB, 'login': user, 'password': password}
    }, timeout=30)
    res = r.json()
    if not res.get('result', {}).get('uid'):
        raise NoSessionError('Credenciales Odoo inválidas.')
    _session = s
    return s


def _ensure():
    if _session is None:
        connect()
    return _session


# ════════════════════════════════════════════════════════════════════════════
#  CATÁLOGO DE MODELOS  (lo que Claude lee para construir consultas)
# ════════════════════════════════════════════════════════════════════════════
CATALOG = {

    # ─────────────────────────── COMPRAS ───────────────────────────
    "COMPRAS_PEDIDOS": {
        "area": "Compras",
        "model": "purchase.order",
        "desc": "Pedidos de compra (cabecera).",
        "useful_fields": ["name", "partner_id", "date_order", "amount_untaxed",
                          "amount_total", "currency_id", "state", "company_id", "user_id"],
        "lines_model": "purchase.order.line",
        "notes": "state: draft, sent, purchase (confirmado), done, cancel. "
                 "Para líneas filtra purchase.order.line por order_id.",
    },
    "COMPRAS_LINEAS": {
        "area": "Compras",
        "model": "purchase.order.line",
        "desc": "Líneas de pedido de compra (producto, cantidades, importes).",
        "useful_fields": ["order_id", "product_id", "name", "product_qty", "qty_received",
                          "qty_invoiced", "product_uom", "price_unit", "price_subtotal",
                          "price_total", "date_planned", "partner_id"],
        "notes": "product_qty=pedido, qty_received=recibido, qty_invoiced=facturado. "
                 "price_subtotal=sin IVA, price_total=con IVA.",
    },

    # ─────────────────────────── VENTAS ───────────────────────────
    "VENTAS_PEDIDOS": {
        "area": "Ventas",
        "model": "sale.order",
        "desc": "Pedidos de venta (cabecera).",
        "useful_fields": ["name", "partner_id", "date_order", "amount_untaxed",
                          "amount_total", "currency_id", "state", "company_id", "user_id"],
        "lines_model": "sale.order.line",
        "notes": "state: draft, sent, sale (confirmado), done, cancel.",
    },
    "VENTAS_LINEAS": {
        "area": "Ventas",
        "model": "sale.order.line",
        "desc": "Líneas de pedido de venta.",
        "useful_fields": ["order_id", "product_id", "name", "product_uom_qty",
                          "qty_delivered", "qty_invoiced", "product_uom", "price_unit",
                          "price_subtotal", "price_total"],
    },

    # ─────────────────────────── FACTURAS / CONTABILIDAD ───────────
    "FACTURAS": {
        "area": "Facturación",
        "model": "account.move",
        "desc": "Facturas (cliente y proveedor) y asientos contables.",
        "useful_fields": ["name", "partner_id", "move_type", "invoice_date", "date",
                          "amount_untaxed", "amount_total", "amount_residual",
                          "state", "payment_state", "journal_id", "ref"],
        "lines_model": "account.move.line",
        "notes": "move_type: out_invoice=factura cliente, in_invoice=factura proveedor, "
                 "out_refund/in_refund=abonos, entry=asiento. "
                 "payment_state: not_paid, in_payment, paid, partial. "
                 "state: draft, posted, cancel. amount_residual=pendiente de cobro/pago.",
    },
    "APUNTES_CONTABLES": {
        "area": "Facturación",
        "model": "account.move.line",
        "desc": "Apuntes contables (líneas de asiento/factura).",
        "useful_fields": ["move_id", "account_id", "partner_id", "product_id", "name",
                          "debit", "credit", "balance", "date", "quantity", "price_unit"],
    },

    # ─────────────────────────── STOCK ───────────────────────────
    "STOCK_MOVIMIENTOS": {
        "area": "Stock",
        "model": "stock.move",
        "desc": "Movimientos de stock (entradas, salidas, transferencias).",
        "useful_fields": ["product_id", "name", "product_uom_qty", "quantity",
                          "location_id", "location_dest_id", "date", "state",
                          "reference", "picking_id", "origin"],
        "notes": "state: draft, confirmed, assigned, done, cancel. "
                 "quantity = cantidad realizada (Odoo 17+); en versiones previas quantity_done.",
    },
    "STOCK_ALBARANES": {
        "area": "Stock",
        "model": "stock.picking",
        "desc": "Albaranes / transferencias (recepciones y entregas).",
        "useful_fields": ["name", "partner_id", "scheduled_date", "date_done", "state",
                          "picking_type_id", "origin"],
        "notes": "state: draft, waiting, confirmed, assigned, done, cancel.",
    },
    "STOCK_ACTUAL": {
        "area": "Stock",
        "model": "stock.quant",
        "desc": "Stock actual (quants) por producto y ubicación.",
        "useful_fields": ["product_id", "location_id", "quantity", "available_quantity",
                          "reserved_quantity"],
        "notes": "Filtra por location_id de tipo interno para stock físico real.",
    },

    # ─────────────────────────── MAESTROS ───────────────────────────
    "PARTNERS": {
        "area": "Maestros",
        "model": "res.partner",
        "desc": "Empresas/contactos (clientes y proveedores).",
        "useful_fields": ["name", "vat", "country_id", "city", "email", "phone",
                          "customer_rank", "supplier_rank", "is_company"],
        "notes": "customer_rank>0 = cliente; supplier_rank>0 = proveedor. "
                 "Buscar por nombre: [['name','ilike','TELLO']].",
    },
    "PRODUCTOS": {
        "area": "Maestros",
        "model": "product.product",
        "desc": "Productos (variantes).",
        "useful_fields": ["name", "default_code", "barcode", "list_price",
                          "standard_price", "categ_id", "uom_id", "type", "active"],
        "notes": "default_code = referencia interna (p.ej. '100020'). "
                 "type: product (almacenable), consu, service. "
                 "product.template para datos a nivel plantilla.",
    },
}


# ════════════════════════════════════════════════════════════════════════════
#  MOTOR DE CONSULTA
# ════════════════════════════════════════════════════════════════════════════
def query(model, domain=None, fields=None, limit=None, order=None,
          offset=0, all_pages=False):
    """
    Ejecuta search_read sobre un modelo Odoo. Devuelve lista de dicts.

    model      p.ej. 'purchase.order'
    domain     filtro Odoo (lista de tuplas), p.ej. [['partner_id','=',1079]]
               o [['state','=','purchase'],['date_order','>=','2024-01-01']]
    fields     lista de campos a traer
    limit      máximo de registros
    order      p.ej. 'date_order desc'
    all_pages  True para paginar automáticamente (lotes de 1000)
    """
    s = _ensure()
    domain = domain or []
    kwargs = {}
    if fields:        kwargs_fields = fields
    else:             kwargs_fields = []
    if order:         kwargs['order'] = order

    def call(off, lim):
        payload = {
            'jsonrpc': '2.0', 'method': 'call',
            'params': {
                'model': model, 'method': 'search_read',
                'args': [domain, kwargs_fields],
                'kwargs': {**kwargs, 'offset': off, **({'limit': lim} if lim else {})},
            }
        }
        r = s.post(f'{ODOO_URL}/web/dataset/call_kw', json=payload, timeout=60)
        r.raise_for_status()
        res = r.json()
        if 'error' in res:
            raise RuntimeError(res['error'].get('data', {}).get('message', res['error']))
        return res['result']

    if all_pages:
        out, off = [], 0
        while True:
            batch = call(off, 1000)
            out.extend(batch)
            if len(batch) < 1000:
                break
            off += 1000
            if limit and len(out) >= limit:
                return out[:limit]
        return out
    return call(offset, limit or 80)


def fields_of(model):
    """Devuelve los campos de un modelo (fields_get)."""
    s = _ensure()
    payload = {
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'model': model, 'method': 'fields_get', 'args': [],
                   'kwargs': {'attributes': ['string', 'type']}}
    }
    r = s.post(f'{ODOO_URL}/web/dataset/call_kw', json=payload, timeout=60)
    r.raise_for_status()
    res = r.json()['result']
    return {k: (v.get('type'), v.get('string')) for k, v in res.items()}


def count(model, domain=None):
    """search_count sobre un modelo."""
    s = _ensure()
    payload = {
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'model': model, 'method': 'search_count', 'args': [domain or []],
                   'kwargs': {}}
    }
    r = s.post(f'{ODOO_URL}/web/dataset/call_kw', json=payload, timeout=60)
    r.raise_for_status()
    return r.json()['result']


# ════════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════════
def print_catalog():
    print('\n=== CATÁLOGO ODOO DISPONIBLE ===\n')
    by_area = {}
    for key, c in CATALOG.items():
        by_area.setdefault(c['area'], []).append((key, c))
    for area in by_area:
        print(f'■ {area}')
        for key, c in by_area[area]:
            print(f'    {key:22s} {c["model"]}')
            print(f'    {"":22s} → {c["desc"]}')
        print()


def main():
    if '--catalog' in sys.argv:
        print_catalog()
        return
    if '--test' in sys.argv:
        try:
            connect()
            rows = query('purchase.order', fields=['name', 'partner_id', 'amount_total', 'date_order'],
                         limit=3, order='date_order desc')
            print('Conexión OK. Últimos pedidos de compra:')
            for r in rows:
                print(' ', r['name'], r['partner_id'], r['amount_total'], r['date_order'])
            return
        except NoSessionError:
            print('NO_SESSION: no hay sesión Odoo activa. Hay que iniciar sesión.')
            sys.exit(3)
        except Exception as e:
            print(f'SESSION_INVALID: {e}')
            sys.exit(4)
    # consola interactiva
    connect(interactive=True)
    print('Conectado. Usa query(...) o consulta CATALOG. Ej:')
    print("  query('res.partner', domain=[['name','ilike','TELLO']], fields=['name','vat'], limit=5)")
    import code
    code.interact(local=globals())


if __name__ == '__main__':
    main()
