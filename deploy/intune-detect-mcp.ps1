# intune-detect-mcp.ps1 - Deteccion (Intune Remediations) del estado de Claude/MCP por equipo.
#
# Es la version no interactiva de diagnostico-mcp.ps1: NO cambia nada, imprime UNA linea y
# devuelve exit 1 si hay algo que arreglar (el equipo sale como "Con problemas" en Intune).
#
# Intune: Devices > Scripts and remediations > Remediations > Create
#   Detection script  = este fichero        Remediation script = (ninguno)
#   "Run this script using the logged-on credentials" = YES  (lee ~/.claude.json del usuario)
#   "Run script in 64-bit PowerShell"                  = YES
#   Programacion: una vez, o diaria mientras dure el despliegue.
# Resultado por equipo en el informe de la remediation, columna "Pre-remediation detection
# output" (exportable a CSV). Formato:
#   EQUIPO usuario | plugin=1.5.1 mcp-con-token=3/3 hub-alcanzable=3/3 | OK
#   EQUIPO usuario | plugin=1.4.0 mcp-con-token=0/3 hub-alcanzable=0/3 | KO: sin-login-m365 plugin-cache-vieja(1.4.0<1.5.1)

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
    $con = @(); $sin = @(); $tok = @{}
    foreach ($n in 'sap-heura-remote', 'graph-heura-remote', 'odoo-heura-remote') {
        $a = $c.mcpServers.$n.headers.Authorization
        if ($a) { $con += $n; $tok[$n] = $a } else { $sin += $n }
    }
    if ($con.Count -eq 0) { $ko += "sin-login-m365" }
    elseif ($sin.Count -gt 0) { $ko += "faltan-mcp(" + ($sin -join ',') + ")" }
    # Todos los servidores comparten el MISMO token (identifica a la persona, no al servicio).
    # Si uno difiere es que se quedo atras en un login viejo y ese MCP dara 401 mientras los
    # demas funcionan: paso con odoo, anadido al hub despues que sap y graph (2026-09-14).
    $distintos = @($tok.Values | Sort-Object -Unique)
    if ($con.Count -gt 1 -and $distintos.Count -gt 1) {
        $ko += "tokens-desincronizados(" + ($con -join ',') + ")"
    }
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
Write-Output ("{0} {1} | {2} | {3}" -f $env:COMPUTERNAME, $env:USERNAME, ($info -join ' '), $estado)
if ($ko.Count) { exit 1 } else { exit 0 }
