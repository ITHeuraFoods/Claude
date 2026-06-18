# Generar dashboards HTML desde datos de Odoo

Cuando el usuario pida un dashboard, informe visual o "algo para enseñar a compañeros",
genera un fichero HTML **autocontenido** (se abre con doble clic, sin servidor).

## Principios

1. **Datos embebidos**: vuelca los resultados de `query()` directamente como array JS en el
   HTML. El dashboard NO debe llamar a Odoo al abrirse (los compañeros pueden no tener acceso).
2. **Chart.js vía CDN**: `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>`.
3. **Estructura**: fila de KPIs arriba → gráficos → tabla de detalle.
4. **Pre-procesa en Python**: totales, agregados por mes/proveedor/producto, antes de embeber.
5. Guardar y abrir: `Start-Process dashboard.html` (Windows).

## Plantilla mínima

```python
import json, scripts.odoo_connector as oc
oc.connect()
lineas = oc.query('purchase.order.line', domain=[...], fields=[...], all_pages=True)

kpis  = {"pedido": ..., "recibido": ..., "importe": ...}
serie = [{"mes": "2024-01", "importe": 1234}, ...]

html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>Dashboard Odoo</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
 body{{font-family:-apple-system,Segoe UI,sans-serif;background:#f4f6f9;margin:0;padding:24px}}
 h1{{color:#7b2d8e}}
 .kpis{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}}
 .kpi{{background:#fff;border-radius:10px;padding:18px 24px;box-shadow:0 1px 4px rgba(80,0,80,.08)}}
 .kpi .v{{font-size:28px;font-weight:700;color:#7b2d8e}}
 .kpi .l{{font-size:13px;color:#666}}
 canvas{{background:#fff;border-radius:10px;padding:16px;margin-bottom:24px;max-height:360px}}
 table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden}}
 th,td{{padding:8px 12px;text-align:left;font-size:13px;border-bottom:1px solid #eee}}
 th{{background:#7b2d8e;color:#fff}}
</style></head><body>
<h1>Dashboard Odoo — Heura</h1>
<div class="kpis">
  <div class="kpi"><div class="v">{kpis['pedido']:,.0f}</div><div class="l">Pedido</div></div>
  <div class="kpi"><div class="v">{kpis['recibido']:,.0f}</div><div class="l">Recibido</div></div>
  <div class="kpi"><div class="v">{kpis['importe']:,.0f} €</div><div class="l">Importe</div></div>
</div>
<canvas id="c1"></canvas>
<script>
const serie = {json.dumps(serie, ensure_ascii=False)};
new Chart(document.getElementById('c1'), {{
  type:'bar',
  data:{{labels:serie.map(s=>s.mes),
         datasets:[{{label:'Importe €',data:serie.map(s=>s.importe),backgroundColor:'#7b2d8e'}}]}},
  options:{{responsive:true,plugins:{{legend:{{display:false}}}}}}
}});
</script>
</body></html>"""

open('dashboard.html','w',encoding='utf-8').write(html)
```

## Tipos de gráfico habituales

- **Evolución temporal** → `'line'`/`'bar'` por mes (agrupa por `date_order[:7]`).
- **Pedido vs recibido** → barras agrupadas (dos datasets).
- **Reparto por proveedor/cliente/producto** → `'doughnut'` o barras horizontales.
- **ES vs FR (company_id)** → barras apiladas.
