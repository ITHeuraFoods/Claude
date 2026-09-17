# intune-diag-user.ps1 - Diagnostico de Claude/MCP por equipo, como Platform script de Intune.
#
# Sin licencia de Remediations, Intune solo recoge exito/fallo por equipo. Este script:
#   1. Comprueba lo mismo que diagnostico-mcp.ps1 (solo lee, no cambia nada).
#   2. Devuelve exit 1 si hay algo que arreglar -> el equipo sale como "Failed" en Intune.
#   3. Manda su linea de estado al hub (POST /diag, puerto 3003) para tener el detalle por
#      equipo; si no alcanza el hub (sin VPN) la deja solo en el log local.
#   4. Escribe la linea en %LOCALAPPDATA%\HeuraIT\claude-diag.log.
#
# Intune: Devices > Scripts and remediations > Platform scripts, via el wrapper local
# intune-wrapper-diag.ps1 (lleva el secreto, gitignored), "Run this script using the logged
# on credentials" = YES, 64 bits = YES.
#
# Formato de la linea:
#   EQUIPO usuario | plugin=1.5.1 mcp-con-token=3/3 hub-alcanzable=3/3 | OK
#   EQUIPO usuario | plugin=1.4.0 mcp-con-token=0/3 hub-alcanzable=0/3 | KO: sin-login-m365 ...
param(
    [string]$RegisterSecret = "",
    [string]$HubUrl = "http://mcp.heurafoods.com:3003"
)
$ErrorActionPreference = 'SilentlyContinue'
$ko = @(); $info = @()

# 1. Politica de organizacion (la instala intune-deploy-system.ps1)
$managed = "C:\Program Files\ClaudeCode\managed-settings.json"
if (Test-Path $managed) {
    $m = Get-Content $managed -Raw | ConvertFrom-Json
    if (-not $m.enabledPlugins.'heura-erp@heura') { $ko += "policy-sin-heura-erp" }
} else {
    $ko += "sin-managed-settings"
}

# 2. Marketplace clonado y version del plugin que Claude carga (la cache, no el clon)
$mk = "$env:USERPROFILE\.claude\plugins\marketplaces\heura"
$pj = "$mk\plugins\heura-erp\.claude-plugin\plugin.json"
$ip = "$env:USERPROFILE\.claude\plugins\installed_plugins.json"
if (-not (Test-Path $mk)) { $ko += "marketplace-no-clonado" }
$vInst = ""; $vMk = ""
if (Test-Path $pj) { $vMk = (Get-Content $pj -Raw | ConvertFrom-Json).version }
if (Test-Path $ip) {
    $inst = (Get-Content $ip -Raw | ConvertFrom-Json).plugins.'heura-erp@heura'
    if ($inst) { $vInst = @($inst)[0].version }
}
if (-not $vInst) { $ko += "plugin-no-instalado" }
elseif ($vMk -and $vInst -ne $vMk) { $ko += "plugin-cache-vieja($vInst<$vMk)" }
$info += "plugin=$(if ($vInst) { $vInst } else { '-' })"

# 3. ~/.claude.json: los servidores CON token (los escribe el acceso directo de login)
$uc = "$env:USERPROFILE\.claude.json"
if (Test-Path $uc) {
    $c = Get-Content $uc -Raw | ConvertFrom-Json
    $con = @(); $sin = @()
    foreach ($n in 'sap-heura-remote', 'graph-heura-remote', 'odoo-heura-remote') {
        if ($c.mcpServers.$n.headers.Authorization) { $con += $n } else { $sin += $n }
    }
    if ($con.Count -eq 0) { $ko += "sin-login-m365" }
    elseif ($sin.Count -gt 0) { $ko += "faltan-mcp(" + ($sin -join ',') + ")" }
    $info += "mcp-con-token=$($con.Count)/3"
} else {
    $ko += "claude-nunca-abierto"
    $info += "mcp-con-token=0/3"
}

# 4. Acceso directo de login (lo crea intune-deploy-user.ps1)
$lnk = [Environment]::GetFolderPath("Desktop") + "\Conectar M365 con Claude.lnk"
if (-not (Test-Path $lnk)) { $ko += "sin-acceso-directo" }

# 5. Python 3.12 con msal y requests (lo necesita el login)
$py = "C:\Program Files\Python312\python.exe"
if (-not (Test-Path $py)) { $ko += "sin-python" }
elseif (-not (Test-Path "C:\Program Files\Python312\Lib\os.py")) { $ko += "python-roto" }
else {
    $mods = & $py -c "import msal, requests; print('ok')" 2>$null
    if ($mods -ne "ok") { $ko += "python-sin-msal" }
}

# 6. Red: solo informativo, sin VPN es normal que de 0/3
$red = 0
foreach ($p in 3001, 3002, 3004) {
    if (Test-NetConnection mcp.heurafoods.com -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) { $red++ }
}
$info += "hub-alcanzable=$red/3"

$estado = if ($ko.Count) { "KO: " + ($ko -join ' ') } else { "OK" }
$detalle = ($info -join ' ') + " | " + $estado
$linea = "{0} {1} | {2}" -f $env:COMPUTERNAME, $env:USERNAME, $detalle

# Log local
$logDir = "$env:LOCALAPPDATA\HeuraIT"
New-Item -ItemType Directory -Force $logDir | Out-Null
Add-Content -Path "$logDir\claude-diag.log" -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $linea)

# Informe al hub (si hay secreto y lo alcanzamos)
$enviado = "no"
if ($RegisterSecret) {
    try {
        $body = @{ computer = $env:COMPUTERNAME; user = $env:USERNAME; ok = ($ko.Count -eq 0); detail = $detalle } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri "$HubUrl/diag" -Method Post -ContentType "application/json; charset=utf-8" `
            -Headers @{ "X-Heura-Secret" = $RegisterSecret } -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 10 | Out-Null
        $enviado = "si"
    } catch { $enviado = "no ($($_.Exception.Message))" }
}

Write-Output "$linea | informe-al-hub=$enviado"
if ($ko.Count) { exit 1 } else { exit 0 }
