---
name: odoo-heura
description: Consulta Odoo (ERP de Heura) en lenguaje natural. Úsala cuando el usuario pregunte por pedidos de compra o venta, facturas de cliente o proveedor, apuntes contables, movimientos o stock de productos, partners (clientes/proveedores), productos/referencias, o cualquier dato del ERP Odoo. También para generar dashboards o informes HTML a partir de datos de Odoo.
---

# Odoo Heura — Consultas en lenguaje natural

Esta skill conecta con Odoo (https://erp.heurafoods.com) vía JSON-RPC y permite responder
preguntas de negocio con datos reales, y generar dashboards HTML.

## Ubicación de los scripts

Los scripts están en la carpeta `scripts/` dentro del directorio de esta skill
(el mismo directorio donde se encuentra este `SKILL.md`). Ejecuta los comandos
desde ese directorio base o usa rutas absolutas a `scripts/odoo_connector.py`
y `scripts/odoo_login.ps1`.

## Paso 0 — Comprobar sesión y autologin (SIEMPRE primero)

Antes de cualquier consulta, verifica que existe sesión activa:

```bash
python scripts/odoo_connector.py --test
```

Interpreta el resultado:
- `Conexión OK` → continúa al Paso 1.
- `NO_SESSION` (exit 3) o `SESSION_INVALID` (exit 4) → no hay sesión / token caducado:
  **lanza automáticamente la ventana de login segura** (no pidas la contraseña por el chat):

  ```powershell
  Start-Process pwsh -ArgumentList '-NoProfile','-File','scripts/odoo_login.ps1' -Wait
  ```

  Si `pwsh` no existe, usa `powershell`. Abre una ventana aparte con un diálogo seguro de
  Windows donde el usuario teclea usuario (email) y contraseña Odoo. Solo se guarda el cookie
  `session_id`; la contraseña nunca se persiste ni te llega. Tras `-Wait`, repite `--test`.

REGLA DE SEGURIDAD: NUNCA pidas ni aceptes la contraseña Odoo escrita en el chat. El único
canal de credenciales es la ventana de `odoo_login.ps1`. (Alternativa manual en terminal del
usuario: `python scripts/odoo_login.py`.)

## Paso 1 — Entender qué datos hacen falta

Lee el catálogo de modelos disponibles:

```bash
python scripts/odoo_connector.py --catalog
```

El catálogo (`CATALOG` dentro de `odoo_connector.py`) documenta cada área, su modelo Odoo,
campos útiles y notas. Áreas: **Compras, Ventas, Facturación/Contabilidad, Stock, Maestros**.

**EL CATÁLOGO ES LA FUENTE DE VERDAD.** Coge el `model` y los campos de la entrada
correspondiente. No inventes nombres de campo. Para descubrir campos de un modelo concreto,
como último recurso usa `oc.fields_of('modelo')` (puede ser lento).

## Paso 2 — Construir y ejecutar la consulta (un solo proceso)

**Eficiencia: una sola ejecución de Python por pregunta.** Mete toda la lógica en un único
script que llame a `connect()` una vez y ejecute todas las `query()` necesarias.

```python
import scripts.odoo_connector as oc  # o: import odoo_connector as oc
oc.connect()

# Ejemplo: compras del producto 100020 al proveedor Tello
# 1) localizar el partner correcto (ilike puede devolver varios homónimos)
tello = oc.query('res.partner', domain=[['name','=','INDUSTRIAS CARNICAS TELLO S.A.']],
                 fields=['id','name'], limit=1)
pid = tello[0]['id']
# 2) líneas de compra (partner_id existe también en la línea)
lineas = oc.query('purchase.order.line',
    domain=[['partner_id','=',pid], ['product_id.default_code','=','100020']],
    fields=['product_qty','qty_received','price_subtotal','product_uom'],
    all_pages=True)
```

Reglas de dominio Odoo (filtros):
- Lista de tuplas: `[['campo','operador',valor], ...]` (varias condiciones = AND).
- Operadores: `=`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not in`, `like`, `ilike`, `child_of`.
- OR explícito con notación polaca: `['|', ['a','=',1], ['b','=',2]]`.
- Campos relacionales con punto: `product_id.default_code`, `order_id.partner_id`.
- Fechas como string ISO: `['date_order','>=','2024-01-01']`.
- Campos Many2one se devuelven como `[id, "nombre"]`.

Notas de negocio importantes:
- `account.move.move_type`: `out_invoice`=factura cliente, `in_invoice`=factura proveedor,
  `out_refund`/`in_refund`=abonos. `payment_state` y `amount_residual` para cobros/pagos.
- En Heura hay pedidos ES (ESPO…) y FR (FRPO…); filtra por `company_id` o por el prefijo de
  `name` si el usuario pregunta por una sociedad concreta.
- `purchase.order.line`: `product_qty`=pedido, `qty_received`=recibido, `qty_invoiced`=facturado.
  `price_subtotal`=sin IVA, `price_total`=con IVA.

## Paso 3 — Responder

- Presenta los datos en tabla markdown, destaca totales y patrones.
- Habla como analista de negocio; no menciones detalles técnicos de la query salvo que lo pidan.

## Paso 4 — Dashboards HTML (si lo piden)

Sigue la guía en **`references/dashboard-html.md`**: HTML autocontenido con Chart.js vía CDN,
datos embebidos, KPIs + gráficos + tabla. Ábrelo con `Start-Process fichero.html`.
