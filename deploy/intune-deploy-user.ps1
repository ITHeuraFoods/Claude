# Ejecutar en Intune con "Run as logged on user = Yes"
# Registra MCP en Claude Desktop y crea acceso directo de login M365
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$base       = "https://raw.githubusercontent.com/ITHeuraFoods/Claude/main"
$configDir  = "$env:APPDATA\Claude"
$configFile = "$configDir\claude_desktop_config.json"
$loginDir   = "$env:USERPROFILE\.claude\heura-m365"

# ── 1. Registrar servidores MCP en Claude Desktop ────────────────────────────
New-Item -ItemType Directory -Force $configDir | Out-Null

$mcpEntries = @{
    "sap-heura-remote"   = @{ url = "http://laptop-itadm:3001/mcp" }
    "graph-heura-remote" = @{ url = "http://laptop-itadm:3002/mcp" }
}

if (Test-Path $configFile) {
    $config = Get-Content $configFile -Raw | ConvertFrom-Json
} else {
    $config = [PSCustomObject]@{}
}

if (-not $config.PSObject.Properties["mcpServers"]) {
    $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{})
}

foreach ($key in $mcpEntries.Keys) {
    $config.mcpServers | Add-Member -NotePropertyName $key -NotePropertyValue $mcpEntries[$key] -Force
}

$config | ConvertTo-Json -Depth 10 | Set-Content $configFile -Encoding UTF8

# ── 2. Script de login M365 remoto ────────────────────────────────────────────
New-Item -ItemType Directory -Force $loginDir | Out-Null
Invoke-WebRequest "$base/scripts/graph_login_remote.py" -OutFile "$loginDir\graph_login_remote.py" -UseBasicParsing

# Acceso directo en el escritorio
$desktopPath = [Environment]::GetFolderPath("Desktop")
if ($desktopPath -and (Test-Path $desktopPath)) {
    $shortcut = "$desktopPath\Conectar M365 con Claude.lnk"
    $wsh = New-Object -ComObject WScript.Shell
    $lnk = $wsh.CreateShortcut($shortcut)
    $lnk.TargetPath       = "powershell.exe"
    $lnk.Arguments        = "-ExecutionPolicy Bypass -Command `"& { `$env:HEURA_REGISTER_SECRET='Heura2026!'; python '$loginDir\graph_login_remote.py' }; pause`""
    $lnk.WorkingDirectory = $loginDir
    $lnk.IconLocation     = "shell32.dll,144"
    $lnk.Description      = "Conectar cuenta M365 con Claude"
    $lnk.Save()
}
