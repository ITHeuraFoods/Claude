"""Lanzador del MCP de Graph con la autenticacion de la fase 05 delante.

No se toca graph_mcp_server.py: se importa como modulo (su bloque __main__ no
se ejecuta) y se replica aqui lo que hacia, envolviendo la app en el middleware.
"""
import logging
import os
import sys
import threading

sys.path.insert(0, "/opt/heura-mcp/common")
sys.path.insert(0, "/opt/heura-mcp/graph")

import uvicorn
from heura_auth import HeuraAuth
import graph_mcp_server as g

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

os.makedirs(g.TOKEN_DIR, exist_ok=True)
threading.Thread(target=g._start_register_server, daemon=True).start()
logging.info("endpoint /register escuchando en 10.99.0.10:3003")

app = HeuraAuth(g.mcp.streamable_http_app(), service="graph", enforce_user_email=True)
uvicorn.run(app, host="10.99.0.10", port=3002, log_level="warning", access_log=False)
