"""Lanzador del MCP de SAP con la autenticacion de la fase 05 delante.

enforce_user_email=False a proposito: query_sap no recibe identidad, porque el
conector usa UNA credencial de servicio para toda la organizacion. Aqui la
autenticacion sirve para cerrar el puerto y para dejar traza de quien pregunta,
no para separar permisos. Eso lo arregla el nivel estrategico (SAP IAS + OAuth
Token Exchange), no este middleware.
"""
import logging
import sys

sys.path.insert(0, "/opt/heura-mcp/common")
sys.path.insert(0, "/opt/heura-mcp/sap")

import uvicorn
from heura_auth import HeuraAuth
import sap_mcp_server as s

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = HeuraAuth(s.mcp.streamable_http_app(), service="sap", enforce_user_email=False)
uvicorn.run(app, host="10.99.0.10", port=3001, log_level="warning", access_log=False)
