"""
Proxy stdio → HTTP para Claude Desktop.
Claude Desktop lanza este script como proceso local (stdio MCP).
El script reenvía las llamadas al servidor MCP HTTP remoto.

Uso: python heura-mcp-proxy.py <url>
"""
import sys
import json
import requests

if len(sys.argv) < 2:
    sys.exit("Uso: python heura-mcp-proxy.py <url>  (ej: http://172.6.2.2:3001/mcp)")

SERVER_URL = sys.argv[1]
session_id = None


def forward(msg: dict):
    global session_id
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    try:
        r = requests.post(SERVER_URL, json=msg, headers=headers, timeout=60)
        r.raise_for_status()
    except requests.exceptions.ConnectionError:
        return {"jsonrpc": "2.0", "error": {"code": -32603,
                "message": f"No se puede conectar al servidor MCP en {SERVER_URL}"}, "id": msg.get("id")}

    if "Mcp-Session-Id" in r.headers:
        session_id = r.headers["Mcp-Session-Id"]

    if not r.content:
        return None

    content_type = r.headers.get("Content-Type", "")
    if "text/event-stream" in content_type:
        # Leer el primer evento SSE y devolver su data
        for line in r.text.splitlines():
            if line.startswith("data:"):
                data = line[5:].strip()
                if data:
                    try:
                        return json.loads(data)
                    except json.JSONDecodeError:
                        pass
        return None

    try:
        return r.json()
    except Exception:
        return None


for raw_line in sys.stdin:
    raw_line = raw_line.strip()
    if not raw_line:
        continue
    try:
        msg = json.loads(raw_line)
        resp = forward(msg)
        if resp is not None:
            print(json.dumps(resp), flush=True)
    except json.JSONDecodeError as e:
        print(json.dumps({"jsonrpc": "2.0", "error": {"code": -32700, "message": f"Parse error: {e}"}, "id": None}), flush=True)
    except Exception as e:
        print(json.dumps({"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}, "id": None}), flush=True)
