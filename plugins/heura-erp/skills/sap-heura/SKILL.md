---
name: sap-heura
description: Consulta SAP S/4HANA de Heura en lenguaje natural. Úsala cuando el usuario pregunte por pedidos de compra o venta, facturas de proveedor o cliente, movimientos de stock (MB51), business partners (clientes/proveedores), materiales, asientos contables FI/CO, o cualquier dato del ERP SAP. También para generar dashboards o informes HTML a partir de datos SAP.
---

# SAP Heura — Consultas en lenguaje natural

Esta skill conecta con SAP S/4HANA (sistema PS4, mandante 100) vía OData y permite
responder preguntas de negocio con datos reales, y generar dashboards HTML.

## Normas de negocio (convenciones Heura — aplícalas SIEMPRE)

Estas reglas son de obligado cumplimiento en cada consulta:

- **Cantidades recibidas → filtra por fecha de entrada de mercancía (Goods Receipt Date).**
  Cuando el usuario pregunte por cantidades *recibidas* (no pedidas), filtra por la fecha de
  contabilización de la entrada de mercancía (`PostingDate` de la cabecera del documento de
  material, movimientos 101 menos 102), NO por la fecha del pedido. Las cantidades *pedidas*
  sí usan `PurchaseOrderDate`.

## Ubicación de los scripts

Los scripts están en la carpeta `scripts/` dentro del directorio de esta skill
(el mismo directorio donde se encuentra este `SKILL.md`). Ejecuta los comandos
**desde ese directorio base** o usa rutas absolutas a `scripts/sap_connector.py`
y `scripts/sap_login.ps1`.

## Paso 0 — Comprobar sesión y autologin (SIEMPRE primero)

Antes de cualquier consulta, verifica que existe sesión activa (desde la carpeta de la skill):

```powershell
# Desde el directorio raíz de la skill (donde está este SKILL.md):
python scripts/sap_connector.py --test
```

Interpreta el resultado:
- `Conexión OK` → continúa al Paso 1.
- `NO_SESSION` (exit 3) o `SESSION_INVALID` (exit 4) → no hay sesión / token caducado: lanza el login.

- Si responde "Conexión OK" → continúa al Paso 1.
- Si da error de credenciales/token → **lanza automáticamente la ventana de login segura**
  (no pidas la contraseña por el chat). En Windows:

  ```powershell
  Start-Process pwsh -ArgumentList '-NoProfile','-File','scripts/sap_login.ps1' -Wait
  ```

  Si `pwsh` no existe, usa `powershell` en su lugar. Esto abre una ventana aparte con un
  diálogo seguro de Windows donde el usuario teclea usuario y contraseña SAP (enmascarada).
  Solo se guarda el token de sesión temporal; la contraseña nunca se persiste ni te llega.

- Tras `-Wait`, vuelve a ejecutar `python scripts/sap_connector.py --test` para confirmar.
  Si sigue fallando, pídele al usuario que repita el login (pudo cancelar el diálogo).

REGLA DE SEGURIDAD: NUNCA pidas ni aceptes la contraseña SAP escrita en el chat. El único
canal de credenciales es la ventana de `sap_login.ps1`. (Alternativa manual en terminal del
usuario: `python scripts/sap_login.py`.)

## Paso 1 — Entender qué datos hacen falta

Lee el catálogo de servicios disponibles:

```bash
python scripts/sap_connector.py --catalog
```

El catálogo (definido en `CATALOG` dentro de `sap_connector.py`) documenta cada área de
negocio, su servicio/entidad OData, campos útiles y notas (filtros obligatorios, etc.).
Áreas cubiertas: **Ventas, Compras (incl. subcontratación), Stocks/MB51, Finanzas FI+CO,
Maestros (BP, materiales)**.

**EL CATÁLOGO ES LA FUENTE DE VERDAD.** Coge el `service`/`entity` y los campos directamente
de la entrada del catálogo correspondiente. Para datos de líneas/posiciones usa
`lines_entity` + `lines_fields` (p. ej. un pedido de compra → `A_PurchaseOrderItem`). **No
inventes nombres de entidad ni de campo, y no llames a `sc.fields(...)` por defecto:** descargar
los metadatos es lento y casi nunca hace falta. Reserva `sc.fields('SERVICIO','ENTIDAD')` solo
para entidades que el catálogo marca como "ejecutar con `$top=1` para ver campos" (vistas CDS)
o cuando una consulta falle por un campo desconocido.

## Paso 2 — Construir y ejecutar la consulta (un solo proceso)

**Eficiencia: una sola ejecución de Python por pregunta.** Cada invocación de `python -c` o
`python script.py` paga arranque en frío del intérprete + nueva sesión TLS. No encadenes varias
llamadas (una para campos, otra para datos): mete toda la lógica de la pregunta en **un único
script** que llame a `connect()` una vez y ejecute todas las `query()` necesarias.

Escribe un pequeño script Python que importe el conector y llame a `query()`:

```python
import scripts.sap_connector as sc  # o: import sap_connector as sc
sc.connect()

# Ejemplo: materiales (líneas) de un pedido de compra concreto.
# service/entity/campos salen de COMPRAS_PEDIDOS → lines_entity / lines_fields.
rows = sc.query(
    'API_PURCHASEORDER_PROCESS_SRV', 'A_PurchaseOrderItem',
    filter="PurchaseOrder eq '4500002621'",
    select=['PurchaseOrderItem','Material','PurchaseOrderItemText',
            'OrderQuantity','PurchaseOrderQuantityUnit','NetPriceAmount','Plant'],
    all_pages=True,
)
```

Para traer cabecera + líneas en **un solo viaje a SAP**, usa `$expand`:

```python
rows = sc.query('API_PURCHASEORDER_PROCESS_SRV', 'A_PurchaseOrder',
    filter="PurchaseOrder eq '4500002621'", expand='to_PurchaseOrderItem')
```

Reglas OData v2 importantes:
- Strings entre comillas simples: `Supplier eq '10000074'`
- Fechas: `PostingDate ge datetime'2026-01-01T00:00:00'`
- Texto parcial: `substringof('TELLO',SupplierFullName)`
- `FI_ASIENTOS` exige filtro: `CompanyCode eq '1000' and LedgerFiscalYear eq '2026' and Ledger eq '0L'`
- `$select` siempre solo los campos necesarios (reduce el payload).
- Campos desconocidos de una entidad: como último recurso `sc.fields('SERVICIO','ENTIDAD')`
  (lento — solo si el catálogo no los documenta).

## Paso 3 — Responder

- Presenta los datos en tabla markdown, destaca totales y patrones.
- Convierte unidades si procede (las conversiones CS/UN/KG están en `A_ProductUnitsOfMeasure`
  del material; QuantityNumerator/QuantityDenominator).
- Habla como analista de negocio, no menciones detalles técnicos de la query salvo que lo pidan.

## Paso 4 — Dashboards HTML (si lo piden)

Cuando el usuario pida un dashboard, informe visual o algo "para enseñar a compañeros",
sigue la guía completa en **`references/dashboard-html.md`**: fichero HTML autocontenido
con Chart.js vía CDN, datos embebidos (sin dependencia de SAP al abrir), KPIs + gráficos +
tabla de detalle. Guárdalo y ábrelo con `Start-Process fichero.html`.

## Notas de acceso

- Las APIs transaccionales standard (`API_*`) y las vistas `ZVCDS*_CDS` están accesibles.
- Algunos APIs FI/CO sueltos (Billing, GL Line Items, Cost Center API propia) dan 403:
  usa `API_JOURNALENTRYITEMBASIC_SRV` (Universal Journal) para FI+CO, y `ZVCDS_VBRP_CDS`
  para facturas de venta.
- Requiere VPN de Heura activa.
