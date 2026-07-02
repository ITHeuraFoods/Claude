# Ejecutar en Intune con "Run as logged on user = No" (SYSTEM)
# Instala managed-settings.json y fuentes corporativas.
#
# Ruta correcta en Windows para que Claude Code lea la config gestionada (v2.1.75+):
# C:\Program Files\ClaudeCode\ — la ruta legacy C:\ProgramData\ClaudeCode\ ya no se soporta.
#
# Ya no desplegamos managed-mcp.json: daba control EXCLUSIVO sobre MCP (ningún usuario podía
# añadir MCP propios en ninguna máquina de la flota). sap-heura-remote y graph-heura-remote
# ahora se distribuyen como MCP del plugin heura-erp (plugins/heura-erp/.mcp.json), que no es
# exclusivo. Se borra el fichero si ya existe de un despliegue anterior.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$base = "https://raw.githubusercontent.com/ITHeuraFoods/Claude/main"
$dest = "C:\Program Files\ClaudeCode"

New-Item -ItemType Directory -Force $dest | Out-Null

Invoke-WebRequest "$base/deploy/managed-settings.json" -OutFile "$dest\managed-settings.json" -UseBasicParsing

Remove-Item -Force -ErrorAction SilentlyContinue "$dest\managed-mcp.json"
Remove-Item -Force -ErrorAction SilentlyContinue "C:\ProgramData\ClaudeCode\managed-mcp.json"

$fontScript = "$dest\install-fonts.ps1"
Invoke-WebRequest "$base/deploy/install-fonts.ps1" -OutFile $fontScript -UseBasicParsing
PowerShell.exe -ExecutionPolicy Bypass -File $fontScript

# Script de login M365 remoto — ruta fija de máquina, la misma que espera la skill m365-heura
# (ver "Login automático" en el SKILL.md del plugin heura-erp). Va aquí, no en el script de
# usuario, porque C:\heura-mcp requiere permisos de administrador para crearse.
New-Item -ItemType Directory -Force "C:\heura-mcp" | Out-Null
Invoke-WebRequest "$base/scripts/graph_login_remote.py" -OutFile "C:\heura-mcp\graph_login_remote.py" -UseBasicParsing
