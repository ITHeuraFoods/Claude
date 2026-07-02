# Ejecutar en Intune con "Run as logged on user = No" (SYSTEM)
# Instala managed-settings.json, managed-mcp.json y fuentes corporativas.
#
# Ruta correcta en Windows para que Claude Code lea la config gestionada (v2.1.75+):
# C:\Program Files\ClaudeCode\ — la ruta legacy C:\ProgramData\ClaudeCode\ ya no se soporta.
#
# managed-mcp.json da control EXCLUSIVO sobre MCP: una vez aplicado, ningún usuario puede
# añadir otros servidores MCP propios (p.ej. MCP locales de VS Code) en ninguna máquina de la
# flota — solo cargan sap-heura-remote y graph-heura-remote.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$base = "https://raw.githubusercontent.com/ITHeuraFoods/Claude/main"
$dest = "C:\Program Files\ClaudeCode"

New-Item -ItemType Directory -Force $dest | Out-Null

Invoke-WebRequest "$base/deploy/managed-settings.json" -OutFile "$dest\managed-settings.json" -UseBasicParsing
Invoke-WebRequest "$base/deploy/managed-mcp.json"       -OutFile "$dest\managed-mcp.json"       -UseBasicParsing

$fontScript = "$dest\install-fonts.ps1"
Invoke-WebRequest "$base/deploy/install-fonts.ps1" -OutFile $fontScript -UseBasicParsing
PowerShell.exe -ExecutionPolicy Bypass -File $fontScript
