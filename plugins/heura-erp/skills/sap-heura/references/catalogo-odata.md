# Catálogo OData de PS4 (mandante 100)

Áreas de negocio con su servicio y entidad OData, para construir llamadas a
`query_sap` sin adivinar. Generado desde el `CATALOG` de `scripts/sap_connector.py`;
si cambia allí, regenerar aquí.

**Antes de inventarte un nombre de servicio, busca en esta tabla.** Un servicio que
no existe devuelve **403** en este gateway, no 404, y parece falta de permisos.

## VENTAS_PEDIDOS

Pedidos de venta (cabecera). Cliente, importe, fechas, organización.

- **Servicio**: `API_SALES_ORDER_SRV`
- **Entidad**: `A_SalesOrder`
- **Entidad de líneas**: `A_SalesOrderItem`
- **Campos clave**: `SalesOrder`
- **Campos útiles**: `SalesOrder, SalesOrderType, SoldToParty, CreationDate, SalesOrganization, TotalNetAmount, TransactionCurrency, PurchaseOrderByCustomer, RequestedDeliveryDate`
- **Campos de línea**: `SalesOrder, SalesOrderItem, Material, RequestedQuantity, RequestedQuantityUnit, NetAmount, TransactionCurrency`

> Filtrar líneas por SalesOrder eq 'XXXX'. SoldToParty = nº cliente BP.

## VENTAS_ENTREGAS

Entregas de salida (albaranes de venta).

- **Servicio**: `API_OUTBOUND_DELIVERY_SRV`
- **Entidad**: `A_OutbDeliveryHeader`
- **Entidad de líneas**: `A_OutbDeliveryItem`
- **Campos clave**: `DeliveryDocument`
- **Campos útiles**: `DeliveryDocument, ActualDeliveryDate, SoldToParty, ShipToParty, TotalWeight, DeliveryDocumentType`
- **Campos de línea**: `DeliveryDocument, DeliveryDocumentItem, Material, ActualDeliveryQuantity, DeliveryQuantityUnit`

## VENTAS_FACTURAS

Posiciones de factura de venta (VBRP). Alternativa al API de Billing (que está restringido).

- **Servicio**: `ZVCDS_VBRP_CDS`
- **Entidad**: `ZVCDS_VBRP`

> El API_BILLING_DOCUMENT_SRV standard da 403; usar esta vista CDS. Ejecutar primero query con $top=1 para descubrir los campos disponibles.

## VENTAS_RESUMEN

Vista analítica de ventas (formato Odoo-friendly).

- **Servicio**: `ZVCDSSD_VENTAS_CDS`
- **Entidad**: `ZVCDSSD_VENTAS`

> Ejecutar con $top=1 para ver campos.

## VENTAS_DEVOLUCIONES

Devoluciones de cliente.

- **Servicio**: `API_CUSTOMER_RETURN_SRV`
- **Entidad**: `A_CustomerReturn`
- **Campos clave**: `CustomerReturn`

## COMPRAS_PEDIDOS

Pedidos de compra (cabecera). Incluye subcontratación.

- **Servicio**: `API_PURCHASEORDER_PROCESS_SRV`
- **Entidad**: `A_PurchaseOrder`
- **Entidad de líneas**: `A_PurchaseOrderItem`
- **Campos clave**: `PurchaseOrder`
- **Campos útiles**: `PurchaseOrder, PurchaseOrderType, Supplier, CompanyCode, PurchaseOrderDate, DocumentCurrency, PurchasingOrganization`
- **Campos de línea**: `PurchaseOrder, PurchaseOrderItem, Material, OrderQuantity, PurchaseOrderQuantityUnit, NetPriceAmount, Plant, IsSubcontracting`

> Subcontratación: A_POSubcontractingComponent lista los componentes que se aportan al proveedor. Filtrar por Supplier eq 'XXXX'.

## COMPRAS_SUBCONTRATACION

Componentes de subcontratación aportados al proveedor por cada línea de PO.

- **Servicio**: `API_PURCHASEORDER_PROCESS_SRV`
- **Entidad**: `A_POSubcontractingComponent`
- **Campos clave**: `PurchaseOrder, PurchaseOrderItem, ScheduleLine, ReservationItem`

## COMPRAS_FACTURAS_PROV

Facturas de proveedor (MIRO).

- **Servicio**: `API_SUPPLIERINVOICE_PROCESS_SRV`
- **Entidad**: `A_SupplierInvoice`
- **Entidad de líneas**: `A_SuplrInvcItemPurOrdRef`
- **Campos clave**: `SupplierInvoice, FiscalYear`
- **Campos útiles**: `SupplierInvoice, FiscalYear, InvoicingParty, CompanyCode, DocumentDate, InvoiceGrossAmount, DocumentCurrency, PaymentTerms`
- **Campos de línea**: `SupplierInvoice, FiscalYear, SupplierInvoiceItem, PurchaseOrder, PurchaseOrderItem, Material, QuantityInPurchaseOrderUnit, SupplierInvoiceItemAmount`

> A_SuplrInvcItemPurOrdRef = facturas IMPUTADAS contra pedido de compra. Vincula factura ↔ PO ↔ material.

## COMPRAS_SOLICITUDES

Solicitudes de pedido (SolPed).

- **Servicio**: `API_PURCHASEREQ_PROCESS_SRV`
- **Entidad**: `A_PurchaseRequisitionHeader`
- **Campos clave**: `PurchaseRequisition`

## MB51_MOVIMIENTOS

Movimientos de material (equivalente a la transacción MB51).

- **Servicio**: `API_MATERIAL_DOCUMENT_SRV`
- **Entidad**: `A_MaterialDocumentItem`
- **Entidad de cabecera**: `A_MaterialDocumentHeader`
- **Campos clave**: `MaterialDocumentYear, MaterialDocument, MaterialDocumentItem`
- **Campos útiles**: `MaterialDocument, MaterialDocumentYear, MaterialDocumentItem, Material, Plant, StorageLocation, GoodsMovementType, QuantityInEntryUnit, EntryUnit, PostingDate`

> GoodsMovementType: 101=entrada mercancía, 601=salida venta, etc. Filtrar por Material y PostingDate.

## STOCK_ACTUAL

Stock actual por material / centro / almacén.

- **Servicio**: `API_MATERIAL_STOCK_SRV`
- **Entidad**: `A_MatlStkInAcctMod`
- **Campos clave**: `Material, Plant, StorageLocation`
- **Campos útiles**: `Material, Plant, StorageLocation, MatlWrhsStkQtyInMatlBaseUnit`

## MB51_MOVIMIENTOS_CDS

Movimientos de stock vista CDS (Odoo-friendly). Alternativa a MB51.

- **Servicio**: `ZVCDSMM_MOVIMIENTO_STOCK_CDS`
- **Entidad**: `ZVCDSMM_MOVIMIENTO_STOCK`

> Ejecutar con $top=1 para ver campos.

## FI_ASIENTOS

Universal Journal (ACDOCA): TODAS las partidas contables FI+CO.

- **Servicio**: `API_JOURNALENTRYITEMBASIC_SRV`
- **Entidad**: `A_JournalEntryItemBasic`
- **Campos clave**: `ID`
- **Campos útiles**: `CompanyCode, LedgerFiscalYear, Ledger, GLAccount, GLAccountName, CostCenter, ProfitCenter, FunctionalArea, AmountInCompanyCodeCurrency, CompanyCodeCurrency, AmountInTransactionCurrency, TransactionCurrency, Segment`

> FILTRO OBLIGATORIO: CompanyCode + LedgerFiscalYear + Ledger eq '0L'. Ej: CompanyCode eq '1000' and LedgerFiscalYear eq '2026' and Ledger eq '0L'. Esta tabla incluye contabilidad financiera (FI) y analítica (CO) unificadas.

## FI_SOCIEDADES

Maestro de sociedades (company codes).

- **Servicio**: `API_JOURNALENTRYITEMBASIC_SRV`
- **Entidad**: `A_CompanyCode`
- **Campos clave**: `CompanyCode`

## FI_CUENTAS_MAYOR

Plan de cuentas / cuentas de mayor.

- **Servicio**: `API_JOURNALENTRYITEMBASIC_SRV`
- **Entidad**: `A_GLAccountInChartOfAccounts`
- **Campos clave**: `ChartOfAccounts, GLAccount`

## CO_CENTROS_COSTE

Maestro de centros de coste.

- **Servicio**: `API_JOURNALENTRYITEMBASIC_SRV`
- **Entidad**: `A_CostCenter`
- **Campos clave**: `ControllingArea, CostCenter`

## CO_CENTROS_BENEFICIO

Maestro de centros de beneficio.

- **Servicio**: `API_JOURNALENTRYITEMBASIC_SRV`
- **Entidad**: `A_ProfitCenter`
- **Campos clave**: `ControllingArea, ProfitCenter`

## BP_PARTNERS

Business Partners (clientes y proveedores unificados).

- **Servicio**: `API_BUSINESS_PARTNER`
- **Entidad**: `A_BusinessPartner`
- **Campos clave**: `BusinessPartner`
- **Campos útiles**: `BusinessPartner, BusinessPartnerFullName, BusinessPartnerName, BusinessPartnerCategory, OrganizationBPName1`

> BusinessPartnerCategory: 1=persona, 2=organización. A_Customer y A_Supplier dan la vista cliente/proveedor.

## BP_CLIENTES

Clientes.

- **Servicio**: `API_BUSINESS_PARTNER`
- **Entidad**: `A_Customer`
- **Campos clave**: `Customer`

## BP_PROVEEDORES

Proveedores.

- **Servicio**: `API_BUSINESS_PARTNER`
- **Entidad**: `A_Supplier`
- **Campos clave**: `Supplier`
- **Campos útiles**: `Supplier, SupplierFullName, SupplierName, Country`

## MAESTRO_MATERIAL

Maestro de materiales.

- **Servicio**: `API_PRODUCT_SRV`
- **Entidad**: `A_Product`
- **Entidad de unidades**: `A_ProductUnitsOfMeasure`
- **Campos clave**: `Product`
- **Campos útiles**: `Product, ProductType, BaseUnit, ProductGroup, GrossWeight, NetWeight, WeightUnit`

> Conversiones de unidad (CS↔UN↔KG) en A_ProductUnitsOfMeasure: QuantityNumerator/QuantityDenominator entre AlternativeUnit y BaseUnit.

