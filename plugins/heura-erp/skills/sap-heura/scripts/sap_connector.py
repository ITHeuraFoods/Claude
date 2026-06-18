"""
============================================================================
  HEURA · SAP S/4HANA Connector
  Herramienta para consultar SAP en lenguaje natural a través de Claude
============================================================================

QUÉ ES ESTO
-----------
Este fichero es un conector a SAP S/4HANA. Ábrelo dentro de Claude (Claude Code)
y pídele cosas en lenguaje natural, por ejemplo:

    "¿Cuántos kg compramos del material 100020 al proveedor 10000074?"
    "Dame las ventas del cliente 10000581 en 2026"
    "Listado de facturas de proveedor del pedido 4500002621"
    "Movimientos de stock (MB51) del material 100020 este mes"
    "Saldo de la cuenta de mayor 1700001000 en la sociedad 1000"

Claude leerá el CATÁLOGO de abajo, construirá la consulta OData adecuada y
ejecutará la función query() para responderte con datos reales de SAP.

REQUISITOS
----------
    pip install requests
    Estar conectado a la VPN de Heura.

USO MANUAL (sin Claude)
-----------------------
    python sap_connector.py --catalog          # ver servicios disponibles
    python sap_connector.py --test             # probar conexión
    python sap_connector.py                     # consola interactiva Python

SEGURIDAD
---------
El script NO contiene credenciales. Pide tu usuario/contraseña SAP al arrancar
(o los lee de las variables de entorno SAP_USER / SAP_PASS). Cada persona usa
sus propias credenciales y ve solo lo que su rol SAP le permite.
============================================================================
"""
import os
import sys
import io
import json
import getpass
import warnings
import tempfile
from datetime import datetime, timezone

import requests

warnings.filterwarnings('ignore')
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ════════════════════════════════════════════════════════════════════════════
#  CONEXIÓN
# ════════════════════════════════════════════════════════════════════════════
SAP_HOST  = 'https://10.3.2.48:44300'
SAP_VHOST = 'vhfftps4ci.sap.heurafoods.com'
SAP_CLIENT = '100'              # mandante productivo PS4
ODATA_BASE = '/sap/opu/odata/sap'
TOKEN_FILE = os.path.join(tempfile.gettempdir(), '.sap_session_heura.json')

_session = None

class NoSessionError(Exception):
    """No hay sesión SAP activa. Claude debe lanzar sap_login.ps1."""
    pass

def connect(user=None, password=None, interactive=False):
    """
    Crea la sesión SAP. Prioridad:
      1. Token de sesión guardado por el login (recomendado, sin contraseña)
      2. Credenciales por argumento o entorno SAP_USER / SAP_PASS
      3. Input interactivo SOLO si interactive=True (consola directa del usuario)

    Si no hay token ni credenciales y interactive=False, lanza NoSessionError
    en lugar de colgarse pidiendo input() (importante cuando lo ejecuta Claude).
    """
    global _session
    s = requests.Session()
    s.verify = False
    s.headers.update({'sap-client': SAP_CLIENT, 'Host': SAP_VHOST, 'Accept': 'application/json'})

    # 1) token de sesión
    if not user and not password and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding='utf-8') as f:
            data = json.load(f)
        for name, value in data.get('cookies', {}).items():
            s.cookies.set(name, value, domain=SAP_VHOST)
        _session = s
        return s

    # 2) credenciales explícitas / entorno
    user     = user     or os.environ.get('SAP_USER')
    password = password or os.environ.get('SAP_PASS')

    # 3) sin token ni credenciales
    if not user or not password:
        if not interactive:
            raise NoSessionError(
                'No hay sesión SAP activa. Lanza la ventana de login: '
                'Start-Process pwsh -ArgumentList "-NoProfile","-File","scripts/sap_login.ps1" -Wait'
            )
        if not user:
            user = input('Usuario SAP: ')
        if not password:
            password = getpass.getpass('Contraseña SAP: ')

    s.auth = (user, password)
    _session = s
    return s

def _ensure():
    if _session is None:
        connect()
    return _session

# ════════════════════════════════════════════════════════════════════════════
#  CATÁLOGO DE SERVICIOS  (lo que Claude lee para construir consultas)
#  Solo incluye servicios VERIFICADOS como accesibles con rol de negocio estándar.
# ════════════════════════════════════════════════════════════════════════════
CATALOG = {

    # ─────────────────────────── VENTAS (SD) ───────────────────────────
    "VENTAS_PEDIDOS": {
        "area": "Ventas",
        "service": "API_SALES_ORDER_SRV",
        "entity": "A_SalesOrder",
        "desc": "Pedidos de venta (cabecera). Cliente, importe, fechas, organización.",
        "key_fields": ["SalesOrder"],
        "useful_fields": ["SalesOrder", "SalesOrderType", "SoldToParty", "CreationDate",
                          "SalesOrganization", "TotalNetAmount", "TransactionCurrency",
                          "PurchaseOrderByCustomer", "RequestedDeliveryDate"],
        "lines_entity": "A_SalesOrderItem",
        "lines_fields": ["SalesOrder", "SalesOrderItem", "Material", "RequestedQuantity",
                         "RequestedQuantityUnit", "NetAmount", "TransactionCurrency"],
        "notes": "Filtrar líneas por SalesOrder eq 'XXXX'. SoldToParty = nº cliente BP.",
    },
    "VENTAS_ENTREGAS": {
        "area": "Ventas",
        "service": "API_OUTBOUND_DELIVERY_SRV",
        "entity": "A_OutbDeliveryHeader",
        "desc": "Entregas de salida (albaranes de venta).",
        "key_fields": ["DeliveryDocument"],
        "useful_fields": ["DeliveryDocument", "ActualDeliveryDate", "SoldToParty",
                          "ShipToParty", "TotalWeight", "DeliveryDocumentType"],
        "lines_entity": "A_OutbDeliveryItem",
        "lines_fields": ["DeliveryDocument", "DeliveryDocumentItem", "Material",
                         "ActualDeliveryQuantity", "DeliveryQuantityUnit"],
    },
    "VENTAS_FACTURAS": {
        "area": "Ventas",
        "service": "ZVCDS_VBRP_CDS",
        "entity": "ZVCDS_VBRP",
        "desc": "Posiciones de factura de venta (VBRP). Alternativa al API de Billing (que está restringido).",
        "key_fields": [],
        "useful_fields": [],
        "notes": "El API_BILLING_DOCUMENT_SRV standard da 403; usar esta vista CDS. "
                 "Ejecutar primero query con $top=1 para descubrir los campos disponibles.",
    },
    "VENTAS_RESUMEN": {
        "area": "Ventas",
        "service": "ZVCDSSD_VENTAS_CDS",
        "entity": "ZVCDSSD_VENTAS",
        "desc": "Vista analítica de ventas (formato Odoo-friendly).",
        "notes": "Ejecutar con $top=1 para ver campos.",
    },
    "VENTAS_DEVOLUCIONES": {
        "area": "Ventas",
        "service": "API_CUSTOMER_RETURN_SRV",
        "entity": "A_CustomerReturn",
        "desc": "Devoluciones de cliente.",
        "key_fields": ["CustomerReturn"],
    },

    # ─────────────────────────── COMPRAS (MM) ──────────────────────────
    "COMPRAS_PEDIDOS": {
        "area": "Compras",
        "service": "API_PURCHASEORDER_PROCESS_SRV",
        "entity": "A_PurchaseOrder",
        "desc": "Pedidos de compra (cabecera). Incluye subcontratación.",
        "key_fields": ["PurchaseOrder"],
        "useful_fields": ["PurchaseOrder", "PurchaseOrderType", "Supplier", "CompanyCode",
                          "PurchaseOrderDate", "DocumentCurrency", "PurchasingOrganization"],
        "lines_entity": "A_PurchaseOrderItem",
        "lines_fields": ["PurchaseOrder", "PurchaseOrderItem", "Material", "OrderQuantity",
                         "PurchaseOrderQuantityUnit", "NetPriceAmount", "Plant",
                         "IsSubcontracting"],
        "notes": "Subcontratación: A_POSubcontractingComponent lista los componentes "
                 "que se aportan al proveedor. Filtrar por Supplier eq 'XXXX'.",
    },
    "COMPRAS_SUBCONTRATACION": {
        "area": "Compras",
        "service": "API_PURCHASEORDER_PROCESS_SRV",
        "entity": "A_POSubcontractingComponent",
        "desc": "Componentes de subcontratación aportados al proveedor por cada línea de PO.",
        "key_fields": ["PurchaseOrder", "PurchaseOrderItem", "ScheduleLine", "ReservationItem"],
    },
    "COMPRAS_FACTURAS_PROV": {
        "area": "Compras",
        "service": "API_SUPPLIERINVOICE_PROCESS_SRV",
        "entity": "A_SupplierInvoice",
        "desc": "Facturas de proveedor (MIRO).",
        "key_fields": ["SupplierInvoice", "FiscalYear"],
        "useful_fields": ["SupplierInvoice", "FiscalYear", "InvoicingParty", "CompanyCode",
                          "DocumentDate", "InvoiceGrossAmount", "DocumentCurrency",
                          "PaymentTerms"],
        "lines_entity": "A_SuplrInvcItemPurOrdRef",
        "lines_fields": ["SupplierInvoice", "FiscalYear", "SupplierInvoiceItem",
                         "PurchaseOrder", "PurchaseOrderItem", "Material",
                         "QuantityInPurchaseOrderUnit", "SupplierInvoiceItemAmount"],
        "notes": "A_SuplrInvcItemPurOrdRef = facturas IMPUTADAS contra pedido de compra. "
                 "Vincula factura ↔ PO ↔ material.",
    },
    "COMPRAS_SOLICITUDES": {
        "area": "Compras",
        "service": "API_PURCHASEREQ_PROCESS_SRV",
        "entity": "A_PurchaseRequisitionHeader",
        "desc": "Solicitudes de pedido (SolPed).",
        "key_fields": ["PurchaseRequisition"],
    },

    # ───────────────────── STOCKS / MOVIMIENTOS (MB51) ─────────────────
    "MB51_MOVIMIENTOS": {
        "area": "Stocks",
        "service": "API_MATERIAL_DOCUMENT_SRV",
        "entity": "A_MaterialDocumentItem",
        "desc": "Movimientos de material (equivalente a la transacción MB51).",
        "key_fields": ["MaterialDocumentYear", "MaterialDocument", "MaterialDocumentItem"],
        "useful_fields": ["MaterialDocument", "MaterialDocumentYear", "MaterialDocumentItem",
                          "Material", "Plant", "StorageLocation", "GoodsMovementType",
                          "QuantityInEntryUnit", "EntryUnit", "PostingDate"],
        "header_entity": "A_MaterialDocumentHeader",
        "notes": "GoodsMovementType: 101=entrada mercancía, 601=salida venta, etc. "
                 "Filtrar por Material y PostingDate.",
    },
    "STOCK_ACTUAL": {
        "area": "Stocks",
        "service": "API_MATERIAL_STOCK_SRV",
        "entity": "A_MatlStkInAcctMod",
        "desc": "Stock actual por material / centro / almacén.",
        "key_fields": ["Material", "Plant", "StorageLocation"],
        "useful_fields": ["Material", "Plant", "StorageLocation",
                          "MatlWrhsStkQtyInMatlBaseUnit"],
    },
    "MB51_MOVIMIENTOS_CDS": {
        "area": "Stocks",
        "service": "ZVCDSMM_MOVIMIENTO_STOCK_CDS",
        "entity": "ZVCDSMM_MOVIMIENTO_STOCK",
        "desc": "Movimientos de stock vista CDS (Odoo-friendly). Alternativa a MB51.",
        "notes": "Ejecutar con $top=1 para ver campos.",
    },

    # ───────────────────────── FINANZAS (FI) / CO ─────────────────────
    "FI_ASIENTOS": {
        "area": "Finanzas",
        "service": "API_JOURNALENTRYITEMBASIC_SRV",
        "entity": "A_JournalEntryItemBasic",
        "desc": "Universal Journal (ACDOCA): TODAS las partidas contables FI+CO.",
        "key_fields": ["ID"],
        "useful_fields": ["CompanyCode", "LedgerFiscalYear", "Ledger", "GLAccount",
                          "GLAccountName", "CostCenter", "ProfitCenter", "FunctionalArea",
                          "AmountInCompanyCodeCurrency", "CompanyCodeCurrency",
                          "AmountInTransactionCurrency", "TransactionCurrency", "Segment"],
        "notes": "FILTRO OBLIGATORIO: CompanyCode + LedgerFiscalYear + Ledger eq '0L'. "
                 "Ej: CompanyCode eq '1000' and LedgerFiscalYear eq '2026' and Ledger eq '0L'. "
                 "Esta tabla incluye contabilidad financiera (FI) y analítica (CO) unificadas.",
    },
    "FI_SOCIEDADES": {
        "area": "Finanzas",
        "service": "API_JOURNALENTRYITEMBASIC_SRV",
        "entity": "A_CompanyCode",
        "desc": "Maestro de sociedades (company codes).",
        "key_fields": ["CompanyCode"],
    },
    "FI_CUENTAS_MAYOR": {
        "area": "Finanzas",
        "service": "API_JOURNALENTRYITEMBASIC_SRV",
        "entity": "A_GLAccountInChartOfAccounts",
        "desc": "Plan de cuentas / cuentas de mayor.",
        "key_fields": ["ChartOfAccounts", "GLAccount"],
    },
    "CO_CENTROS_COSTE": {
        "area": "Controlling",
        "service": "API_JOURNALENTRYITEMBASIC_SRV",
        "entity": "A_CostCenter",
        "desc": "Maestro de centros de coste.",
        "key_fields": ["ControllingArea", "CostCenter"],
    },
    "CO_CENTROS_BENEFICIO": {
        "area": "Controlling",
        "service": "API_JOURNALENTRYITEMBASIC_SRV",
        "entity": "A_ProfitCenter",
        "desc": "Maestro de centros de beneficio.",
        "key_fields": ["ControllingArea", "ProfitCenter"],
    },

    # ───────────────────────── MAESTROS / BP ──────────────────────────
    "BP_PARTNERS": {
        "area": "Maestros",
        "service": "API_BUSINESS_PARTNER",
        "entity": "A_BusinessPartner",
        "desc": "Business Partners (clientes y proveedores unificados).",
        "key_fields": ["BusinessPartner"],
        "useful_fields": ["BusinessPartner", "BusinessPartnerFullName", "BusinessPartnerName",
                          "BusinessPartnerCategory", "OrganizationBPName1"],
        "notes": "BusinessPartnerCategory: 1=persona, 2=organización. "
                 "A_Customer y A_Supplier dan la vista cliente/proveedor.",
    },
    "BP_CLIENTES": {
        "area": "Maestros",
        "service": "API_BUSINESS_PARTNER",
        "entity": "A_Customer",
        "desc": "Clientes.",
        "key_fields": ["Customer"],
    },
    "BP_PROVEEDORES": {
        "area": "Maestros",
        "service": "API_BUSINESS_PARTNER",
        "entity": "A_Supplier",
        "desc": "Proveedores.",
        "key_fields": ["Supplier"],
        "useful_fields": ["Supplier", "SupplierFullName", "SupplierName", "Country"],
    },
    "MAESTRO_MATERIAL": {
        "area": "Maestros",
        "service": "API_PRODUCT_SRV",
        "entity": "A_Product",
        "desc": "Maestro de materiales.",
        "key_fields": ["Product"],
        "useful_fields": ["Product", "ProductType", "BaseUnit", "ProductGroup",
                          "GrossWeight", "NetWeight", "WeightUnit"],
        "uom_entity": "A_ProductUnitsOfMeasure",
        "notes": "Conversiones de unidad (CS↔UN↔KG) en A_ProductUnitsOfMeasure: "
                 "QuantityNumerator/QuantityDenominator entre AlternativeUnit y BaseUnit.",
    },
}

# ════════════════════════════════════════════════════════════════════════════
#  MOTOR DE CONSULTA
# ════════════════════════════════════════════════════════════════════════════
def query(service, entity, filter=None, select=None, orderby=None,
          top=None, expand=None, all_pages=False, dedup_keys=None):
    """
    Ejecuta una consulta OData contra SAP y devuelve lista de dicts.

    service     p.ej. 'API_PURCHASEORDER_PROCESS_SRV'
    entity      p.ej. 'A_PurchaseOrder'
    filter      cláusula OData $filter, p.ej. "Supplier eq '10000074'"
    select      lista o string de campos
    orderby     p.ej. 'PurchaseOrderDate desc'
    top         límite de registros (None = sin límite si all_pages=True)
    expand      navegación, p.ej. 'to_PurchaseOrderItem'
    all_pages   True para paginar automáticamente (en lotes de 500)
    dedup_keys  lista de campos para deduplicar (p.ej. ['documento','id'])
    """
    s = _ensure()
    if isinstance(select, (list, tuple)):
        select = ','.join(select)

    def build(skip, page_top):
        parts = []
        if filter:  parts.append(f'$filter={filter}')
        if select:  parts.append(f'$select={select}')
        if orderby: parts.append(f'$orderby={orderby}')
        if expand:  parts.append(f'$expand={expand}')
        if page_top is not None: parts.append(f'$top={page_top}')
        if skip:    parts.append(f'$skip={skip}')
        url = f'{SAP_HOST}{ODATA_BASE}/{service}/{entity}'
        return url + ('?' + '&'.join(parts) if parts else '')

    results = []
    if all_pages:
        skip = 0
        while True:
            r = s.get(build(skip, 500), timeout=60)
            r.raise_for_status()
            batch = r.json()['d']['results']
            results.extend(batch)
            if len(batch) < 500:
                break
            skip += 500
            if top and len(results) >= top:
                results = results[:top]
                break
    else:
        r = s.get(build(0, top or 50), timeout=60)
        r.raise_for_status()
        results = r.json()['d']['results']

    # limpiar metadata y parsear fechas
    cleaned = []
    seen = set()
    for row in results:
        if dedup_keys:
            k = tuple(row.get(c) for c in dedup_keys)
            if k in seen:
                continue
            seen.add(k)
        cleaned.append({k: _parse(v) for k, v in row.items() if k != '__metadata'})
    return cleaned

def _parse(v):
    """Convierte /Date(ts)/ a YYYY-MM-DD; deja el resto igual."""
    if isinstance(v, str) and v.startswith('/Date('):
        try:
            ts = int(v.replace('/Date(', '').replace(')/', '').split('+')[0])
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
        except Exception:
            return v
    return v

def fields(service, entity):
    """Devuelve los campos (y claves) de un EntitySet leyendo $metadata."""
    from xml.etree import ElementTree as ET
    s = _ensure()
    r = s.get(f'{SAP_HOST}{ODATA_BASE}/{service}/$metadata',
              headers={**s.headers, 'Accept': 'application/xml'}, timeout=30)
    r.raise_for_status()
    NS = 'http://schemas.microsoft.com/ado/2008/09/edm'
    root = ET.fromstring(r.text)
    # localizar el EntityType del EntitySet
    et_name = None
    for es in root.iter(f'{{{NS}}}EntitySet'):
        if es.get('Name') == entity:
            et_name = es.get('EntityType', '').split('.')[-1]
    out = []
    for et in root.iter(f'{{{NS}}}EntityType'):
        if et.get('Name') == et_name:
            keys = {k.get('Name') for k in et.iter(f'{{{NS}}}PropertyRef')}
            for p in et.findall(f'{{{NS}}}Property'):
                out.append({'name': p.get('Name'),
                            'type': p.get('Type', '').replace('Edm.', ''),
                            'key': p.get('Name') in keys})
    return out

# ════════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════════
def print_catalog():
    print('\n=== CATÁLOGO SAP DISPONIBLE ===\n')
    by_area = {}
    for key, c in CATALOG.items():
        by_area.setdefault(c['area'], []).append((key, c))
    for area in by_area:
        print(f'■ {area}')
        for key, c in by_area[area]:
            print(f'    {key:28s} {c["service"]}/{c["entity"]}')
            print(f'    {"":28s} → {c["desc"]}')
        print()

def main():
    if '--catalog' in sys.argv:
        print_catalog()
        return
    if '--test' in sys.argv:
        try:
            connect()
            rows = query('API_PURCHASEORDER_PROCESS_SRV', 'A_PurchaseOrder',
                         orderby='PurchaseOrderDate desc', top=3,
                         select=['PurchaseOrder', 'Supplier', 'PurchaseOrderDate'])
            print('Conexión OK. Últimos pedidos:')
            for r in rows:
                print(' ', r)
            return
        except NoSessionError:
            print('NO_SESSION: no hay sesión SAP activa. Hay que iniciar sesión.')
            sys.exit(3)
        except Exception as e:
            # token caducado u otro error de auth
            print(f'SESSION_INVALID: {e}')
            sys.exit(4)
    # consola interactiva (usuario en su terminal) -> sí permite input
    connect(interactive=True)
    print('Conectado. Usa query(...) o consulta CATALOG. Ej:')
    print("  query('API_BUSINESS_PARTNER','A_Supplier',filter=\"substringof('TELLO',SupplierFullName)\",top=5)")
    import code
    code.interact(local=globals())

if __name__ == '__main__':
    main()
