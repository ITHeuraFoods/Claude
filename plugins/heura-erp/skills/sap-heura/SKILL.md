---
name: sap-heura
description: Consulta SAP S/4HANA de Heura en lenguaje natural. Úsala cuando el usuario pregunte por pedidos de compra o venta, facturas de proveedor o cliente, movimientos de stock (MB51), business partners (clientes/proveedores), materiales, asientos contables FI/CO, o cualquier dato del ERP SAP. También para generar dashboards o informes HTML a partir de datos SAP.
---

# SAP Heura — Consultas en lenguaje natural

Esta skill consulta SAP S/4HANA (sistema **PS4, mandante 100**) a través del MCP
**`sap-heura-remote`**, que corre en el hub de Heura y habla OData con el gateway.

## Cómo se consulta

**Usa siempre la tool `query_sap` del MCP `sap-heura-remote`.** No ejecutes Python
en el equipo del usuario para hablar con SAP.

```
query_sap(service=..., entity=..., filter=..., select=..., top=...)
```

Los scripts de `scripts/` son **break-glass**: solo si el hub está caído, y sabiendo
lo que se hace. Ver la sección final.

**Si `sap-heura-remote` no aparece o no responde**, no busques rodeos: dile al usuario
que compruebe que está en la red de Heura o con la VPN conectada, y que si persiste
ejecute el diagnóstico que le pasará IT. No intentes suplirlo con los scripts locales:
usan credenciales distintas y dan resultados distintos.

## Normas de negocio (convenciones Heura — aplícalas SIEMPRE)

- **Cantidades recibidas → filtra por fecha de entrada de mercancía.** Cuando pregunten
  por cantidades *recibidas* (no pedidas), filtra por la fecha de contabilización de la
  entrada de mercancía (`PostingDate` de la cabecera del documento de material,
  movimientos 101 menos 102), **no** por la fecha del pedido. Las cantidades *pedidas*
  sí usan `PurchaseOrderDate`.
- **`FI_ASIENTOS` exige filtro obligatorio**:
  `CompanyCode eq '1000' and LedgerFiscalYear eq '2026' and Ledger eq '0L'`.
- **Nunca pidas ni aceptes la contraseña de SAP por el chat.** El MCP autentica en el
  hub; el usuario no tiene que darte credenciales nunca.

## Paso 1 — Elegir servicio y entidad

Busca el área en **`references/catalogo-odata.md`**: 21 áreas de negocio con su
servicio, entidad, entidades de líneas y campos útiles. **No inventes nombres de
servicio**; si no está en el catálogo, pregunta antes de probar a ciegas.

## Paso 2 — Construir la consulta

Reglas de OData v2 en este gateway:

- Strings entre comillas simples: `Supplier eq '10000074'`
- Fechas: `PostingDate ge datetime'2026-01-01T00:00:00'`
- Texto parcial: `substringof('TELLO',SupplierFullName)`
- `select` solo con los campos necesarios: reduce el payload y acelera la respuesta.
- Si pides `top` y vuelven exactamente esas filas, **te has quedado corto**: OData
  devuelve las primeras por clave, no las últimas. Acota con `filter` en vez de subir
  el `top`, o no podrás afirmar cuál es la última.

### Los dos errores que mienten sobre su causa

Este gateway informa mal de dos cosas, y llevan a pedirle a Basis cambios que no hacen
falta:

| Síntoma | Causa real |
|---|---|
| **404**, con el cuerpo en alemán | Un campo de `$select` **no existe** en la entidad. No es que el servicio esté desactivado. |
| **403** | El **servicio no existe** en este sistema. No es falta de autorización. |

Para distinguirlo en un intento: **repite la consulta sin `select`**. Si devuelve datos,
el servicio está activo y autorizado y el problema es un nombre de campo. El conector ya
traduce este caso y te dirá qué campo falla y cuáles son válidos.

Ejemplo real: `A_PurchaseOrder` **no tiene importe de cabecera**.
`PurchaseOrderNetAmount` y `NetAmount` dan 404; los importes están en
`A_PurchaseOrderItem`.

## Paso 3 — Responder

- Tabla markdown, con totales y patrones destacados.
- Convierte unidades si procede: las conversiones CS/UN/KG están en
  `A_ProductUnitsOfMeasure` del material (`QuantityNumerator`/`QuantityDenominator`).
- Habla como analista de negocio. No menciones detalles técnicos de la consulta salvo
  que los pidan.

## Paso 4 — Dashboards HTML (si lo piden)

Cuando pidan un dashboard, informe visual o algo «para enseñar a compañeros», sigue
**`references/dashboard-html.md`**: HTML autocontenido, Chart.js por CDN, datos
embebidos (que no dependa de SAP al abrirlo), KPIs + gráficos + tabla de detalle.

## Notas de acceso

- Las APIs transaccionales standard (`API_*`) y las vistas `ZVCDS*_CDS` están accesibles.
- **`API_BILLING_DOCUMENT_SRV` ya está activo** (comprobado el 2026-11-23): cabeceras y
  posiciones de factura de venta. Sigue sin haber API para el **PDF** de la factura
  (`GetPDF` da `V_O2C/103`, la factura ZFRA va por salida NAST y no se archiva): si piden
  el PDF, di que no se puede sacar por aquí.
- **Detalle de apuntes FI** (el estándar `API_OPLACCTGDOCITEMCUBE`, `API_JOURNALENTRY…` y
  `API_COMPANYCODE` **no están publicados**; el 403 significa inexistente):
  - Partidas de un documento: `FAC_GLV_GL_ACCOUNT_LINE_ITEMS_SRV` / `I_OperationalAcctgDocItem`.
  - **Quién lo creó y con qué transacción**: `FAC_FINANCIAL_DOCUMENT_SRV_01` / `Headers`
    (`CreatedByUser`, `TransactionCode`, `ReferenceDocumentType`; clave
    `AccountingDocument`+`CompanyCode`+`FiscalYear`).
  - Textos de cuenta de mayor: `I_GLAccountInCompanyCodeStdVH`
    (`API_GLACCOUNTINCHARTOFACCOUNTS` tampoco está publicado).
- **`A_JournalEntryItemBasic` no admite filtrar por `AccountingDocument`, `ReferenceDocument`
  ni `Supplier`**: da 400. Para localizar una factura de proveedor o un documento concreto
  ve por `API_SUPPLIERINVOICE_PROCESS_SRV` o por `FAC_FINANCIAL_DOCUMENT_SRV_01`.
- **POD de entregas** (cantidad entregada, motivo de diferencia, fecha): solo en
  `ZVCDSSD_VENTAS_CDS` / `ZVCDSSD_VENTAS` (`POD_Quantity`, `Reason`, `Reason_Text`,
  `POD_Status`, `POD_Date`). El estándar solo da estado y fecha.
- **El nombre de servicio del catálogo del gateway lleva la `Z` prefijada** en
  `TechnicalServiceName` para los servicios propios; si un servicio sale 403, prueba el
  nombre completo (`MetadataUrl`) antes de concluir que no existe.
- **`$count` rompe `query_sap`**: cuenta paginando con `top` y `filter`, no con `$count`.
- **Salidas grandes** (cientos de filas): guárdalas en un fichero del scratchpad y
  procésalas con Python en vez de volcarlas al chat.
- Algunos APIs FI/CO sueltos (GL Line Items estándar, Cost Center API propia) no existen
  aquí y devuelven 403: usa `API_JOURNALENTRYITEMBASIC_SRV` (Universal Journal) para
  FI+CO, y `ZVCDS_VBRP_CDS` para facturas de venta.
- El hub solo es alcanzable desde la red de Heura o con la SSL-VPN conectada.

## Break-glass: los scripts locales

`scripts/sap_connector.py` y `scripts/sap_login.py` permiten hablar con SAP **sin pasar
por el hub**, ejecutándose en el equipo del usuario. Solo para cuando el hub esté caído
y con conocimiento de causa, porque:

- Usan **las credenciales SAP de quien los ejecute**, no las del hub: los permisos y por
  tanto los resultados pueden ser distintos.
- No dejan traza en el registro de auditoría del hub.
- Exigen VPN y Python con dependencias en el equipo.

Si acabas usándolos, dilo explícitamente en la respuesta para que el usuario sepa que ese
dato no vino por el camino normal.
