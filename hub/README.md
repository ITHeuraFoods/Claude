# Hub MCP (srv-mcp, Hetzner)

Lo que corre en el servidor que atiende `sap-heura-remote` y `graph-heura-remote`.
Se llega por el túnel IPsec del FortiGate; **no hay ningún puerto MCP expuesto a Internet**.

| Fichero | Qué es |
|---|---|
| `heura_auth.py` | Middleware ASGI de autenticación e identidad. Exige `Authorization: Bearer` y, en `tools/call`, rechaza con 403 si el `user_email` de los argumentos no coincide con la identidad del token. Emite tokens desde `/register`. |
| `run_graph.py` / `run_sap.py` | Lanzadores: importan el servidor MCP y lo envuelven en el middleware. No se toca el código de las tools. |
| `requirements.txt` | Dependencias. `mcp<2` a propósito: la 2.x renombró `FastMCP` a `MCPServer`. |
| `systemd/*.service` | Unidades endurecidas: usuario sin sudo, `ProtectSystem=strict`, sin capacidades, escritura solo en su directorio. |
| `swanctl-heura.conf.example` | Túnel IPsec (strongSwan 6, sintaxis `swanctl`; en esta versión **no existe** `ipsec.conf`). El PSK se genera en el servidor y no se versiona. |
| `heura-mcp-token` | Alta, listado y revocación de tokens manuales. El alta normal es automática vía `/register`. |

## Rutas en el servidor

```
/opt/heura-mcp/{common,graph,sap}/     codigo y venv
/etc/heura-mcp/{graph,sap}.env         secretos, 0600, NO versionados
/var/lib/heura-mcp/tokens/             cachees MSAL por usuario, 0600
/var/lib/heura-mcp/auth/issued.map     sha256(token):email, grupo mcpauth
```

## Dos trampas que costaron tiempo

1. **Un solo hijo en la SA IPsec**, con `remote_ts = 0.0.0.0/0`. Dos hijos con
   selectores solapados contra un phase 2 comodín dejan el tráfico entrante
   chocando con la política XFRM más específica, y el kernel lo descarta sin un
   solo mensaje de error.
2. **Las políticas de firewall van ANTES de que el túnel pueda levantarse.** Un
   FortiGate no negocia IPsec si ninguna política referencia la interfaz del
   túnel: dice `ignoring request to establish IPsec SA, no policy configured` y
   solo se ve con `diagnose debug application ike -1`.
