# Generar dashboards HTML desde datos SAP

Cuando el usuario pida un dashboard, informe visual o "algo para enseñar a compañeros",
genera un fichero HTML **autocontenido** (se abre con doble clic, sin servidor).

## Principios

1. **Datos embebidos**: vuelca los resultados de `query()` directamente como un array JS
   dentro del HTML. El dashboard NO debe llamar a SAP al abrirse (los compañeros no tienen
   VPN ni credenciales).
2. **Chart.js vía CDN**: `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>`.
3. **Estructura**: fila de KPIs arriba → gráficos → tabla de detalle.
4. **Conversión de unidades** ya resuelta en Python antes de embeber (p.ej. CS→KG).
5. Guardar y abrir: `Start-Process dashboard.html` (Windows).

## Plantilla mínima

```python
import json, scripts.sap_connector as sc
sc.connect()
rows = sc.query(...)  # tu consulta

# Pre-procesa en Python (totales, conversiones, agregados por mes, etc.)
kpis = {"pedido_kg": ..., "recibido_kg": ..., "importe": ...}
serie = [{"mes": "2026-01", "kg": 1234}, ...]

html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>Dashboard SAP</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
 body{{font-family:-apple-system,Segoe UI,sans-serif;background:#f4f6f9;margin:0;padding:24px}}
 h1{{color:#003087}}
 .kpis{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}}
 .kpi{{background:#fff;border-radius:10px;padding:18px 24px;box-shadow:0 1px 4px rgba(0,0,80,.08)}}
 .kpi .v{{font-size:28px;font-weight:700;color:#003087}}
 .kpi .l{{font-size:13px;color:#666}}
 canvas{{background:#fff;border-radius:10px;padding:16px;margin-bottom:24px;max-height:360px}}
 table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden}}
 th,td{{padding:8px 12px;text-align:left;font-size:13px;border-bottom:1px solid #eee}}
 th{{background:#003087;color:#fff}}
</style></head><body>
<h1>Dashboard SAP — Heura</h1>
<div class="kpis">
  <div class="kpi"><div class="v">{kpis['pedido_kg']:,.0f}</div><div class="l">KG pedidos</div></div>
  <div class="kpi"><div class="v">{kpis['recibido_kg']:,.0f}</div><div class="l">KG recibidos</div></div>
  <div class="kpi"><div class="v">{kpis['importe']:,.0f} €</div><div class="l">Importe</div></div>
</div>
<canvas id="c1"></canvas>
<script>
const serie = {json.dumps(serie, ensure_ascii=False)};
new Chart(document.getElementById('c1'), {{
  type:'bar',
  data:{{labels:serie.map(s=>s.mes),
         datasets:[{{label:'KG',data:serie.map(s=>s.kg),backgroundColor:'#003087'}}]}},
  options:{{responsive:true,plugins:{{legend:{{display:false}}}}}}
}});
</script>
</body></html>"""

open('dashboard.html','w',encoding='utf-8').write(html)
```

## Tipos de gráfico habituales

- **Evolución temporal** → `type:'line'` o `'bar'` por mes/semana.
- **Pedido vs recibido** → barras agrupadas (dos datasets).
- **Reparto por proveedor/cliente/material** → `'doughnut'` o barras horizontales.
- **Comparativa empresas (sociedades 1000/1100)** → barras apiladas.

Reutiliza el estilo del informe `tello_100020_analisis.html` del usuario si está disponible.
