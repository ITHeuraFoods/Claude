---
name: odoo-heura
description: Consulta Odoo (ERP de Heura) en lenguaje natural. Úsala cuando el usuario pregunte por pedidos de compra o venta, facturas de cliente o proveedor, apuntes contables, movimientos o stock de productos, partners (clientes/proveedores), productos/referencias, o cualquier dato del ERP Odoo. También para generar dashboards o informes HTML a partir de datos de Odoo.
---

# Odoo Heura — Consultas en lenguaje natural

Esta skill consulta Odoo (`https://erp.heurafoods.com`) a través del MCP
**`odoo-heura-remote`**, que corre en el hub de Heura y habla JSON-RPC con el ERP.

## Cómo se consulta

**Usa siempre las tools del MCP `odoo-heura-remote`.** No ejecutes Python en el equipo
del usuario para hablar con Odoo.

| Tool | Para qué |
|---|---|
| `catalogo_odoo()` | Áreas de negocio, modelos y campos útiles. **Empieza aquí.** |
| `query_odoo(model, domain, fields, limit, order)` | Traer registros (`search_read`) |
| `count_odoo(model, domain)` | Cuántos hay, sin traerlos |
| `fields_odoo(model, filtro)` | Campos de un modelo, cuando el catálogo no llega |

El MCP es de **solo lectura**: no hay forma de crear ni modificar nada en Odoo desde
aquí, por diseño. Si alguien pide un cambio en Odoo, dile que lo haga en la aplicación.

**No hay que iniciar sesión.** El hub guarda la única cuenta de Odoo de la organización;
el usuario no tiene que dar credenciales nunca. Si alguien te ofrece su contraseña de
Odoo, no la aceptes ni la uses.

**Si `odoo-heura-remote` no aparece o no responde**, dile al usuario que conecte la VPN
de Heura (FortiClient) y lo reintente; el hub no se alcanza desde fuera. Si persiste, que
ejecute el diagnóstico que le pasará IT. No intentes suplirlo con los scripts locales:
ver la sección final.

## Odoo o SAP: cuál tiene el dato

Los dos ERP conviven y contienen cosas distintas:

- **Hasta el 29/02/2024** la contabilidad está en **Odoo**.
- **Desde marzo de 2024** está en **SAP** (skill `sap-heura`).

Si la pregunta cruza esa fecha, hay que consultar los dos y decirlo en la respuesta. Si
no está claro en qué sistema vive el dato, pregunta antes de dar una cifra: responder
con medio ejercicio es peor que preguntar.

## Paso 1 — Elegir modelo

Llama a `catalogo_odoo()`. Cubre **Compras, Ventas, Facturación/Contabilidad, Stock y
Maestros**. **El catálogo es la fuente de verdad**: coge de ahí el `model` y los campos.
No inventes nombres de campo; si el que necesitas no está, usa `fields_odoo`.

## Paso 2 — Construir la consulta

Reglas de dominio Odoo:

- Lista de condiciones en JSON: `[["campo","operador",valor], ...]` (varias = AND).
- Operadores: `=`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not in`, `like`, `ilike`, `child_of`.
- OR explícito, notación polaca: `["|",["a","=",1],["b","=",2]]`.
- Relacionales con punto: `product_id.default_code`, `order_id.partner_id`.
- Fechas como texto ISO: `["date_order",">=","2024-01-01"]`.
- Los campos Many2one vuelven como `[id, "nombre"]`.
- Pide solo los `fields` que necesites: sin ellos vuelve el registro entero.
- Si vuelven exactamente las filas del `limit`, **te has quedado corto**: acota el
  `domain` en vez de subir el `limit`, o no podrás afirmar cuál es el último.

Buscar un partner por nombre suele devolver homónimos. Localízalo primero y quédate con
el `id`:

```
query_odoo("res.partner", domain='[["name","ilike","TELLO"]]', fields="id,name,vat", limit=10)
query_odoo("purchase.order.line",
           domain='[["partner_id","=",1079],["product_id.default_code","=","100020"]]',
           fields="product_qty,qty_received,price_subtotal,product_uom")
```

## Normas de negocio (convenciones Heura — aplícalas SIEMPRE)

- `account.move.move_type`: `out_invoice`=factura cliente, `in_invoice`=factura
  proveedor, `out_refund`/`in_refund`=abonos, `entry`=asiento.
  `payment_state` y `amount_residual` para pendiente de cobro/pago.
- Hay pedidos **ES** (`ESPO…`) y **FR** (`FRPO…`): filtra por `company_id` o por el
  prefijo de `name` si preguntan por una sociedad concreta.
- `purchase.order.line`: `product_qty`=pedido, `qty_received`=recibido,
  `qty_invoiced`=facturado. `price_subtotal`=sin IVA, `price_total`=con IVA.
- `default_code` es la referencia interna del producto (p. ej. `100020`).
- **Nunca pidas ni aceptes la contraseña de Odoo por el chat.**

## Paso 3 — Responder

- Tabla markdown, con totales y patrones destacados.
- Habla como analista de negocio. No menciones detalles técnicos de la consulta salvo
  que los pidan.

## Paso 4 — Dashboards HTML (si lo piden)

Sigue **`references/dashboard-html.md`**: HTML autocontenido, Chart.js por CDN, datos
embebidos (que no dependa de Odoo al abrirlo), KPIs + gráficos + tabla de detalle.

## Break-glass: los scripts locales

`scripts/odoo_connector.py` y `scripts/odoo_login.ps1` hablan con Odoo **sin pasar por el
hub**, desde el equipo del usuario. Solo para cuando el hub esté caído, y con
conocimiento de causa:

- Exigen que el usuario teclee las credenciales de la cuenta compartida en la ventana de
  login, que es justo lo que la migración al hub vino a eliminar.
- No dejan traza en el registro de auditoría del hub.
- Exigen Python con dependencias en el equipo.

Si acabas usándolos, dilo explícitamente en la respuesta para que el usuario sepa que ese
dato no vino por el camino normal.
