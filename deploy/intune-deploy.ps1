# IMPORTANTE: configurar en Intune con "Run as logged on user = Yes"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$base       = "https://raw.githubusercontent.com/ITHeuraFoods/Claude/main"
$configDir  = "$env:APPDATA\Claude"
$configFile = "$configDir\claude_desktop_config.json"
$loginDir   = "$env:USERPROFILE\.claude\heura-m365"

# ── 1. Claude Code managed config ────────────────────────────────────────────
New-Item -ItemType Directory -Force "C:\ProgramData\ClaudeCode" | Out-Null
Invoke-WebRequest "$base/deploy/managed-settings.json" -OutFile "C:\ProgramData\ClaudeCode\managed-settings.json" -UseBasicParsing
Invoke-WebRequest "$base/deploy/managed-mcp.json"       -OutFile "C:\ProgramData\ClaudeCode\managed-mcp.json"       -UseBasicParsing

# Fuentes corporativas Heura
$fontScript = "C:\ProgramData\ClaudeCode\install-fonts.ps1"
Invoke-WebRequest "$base/deploy/install-fonts.ps1" -OutFile $fontScript -UseBasicParsing
PowerShell.exe -ExecutionPolicy Bypass -File $fontScript

# ── 2. Registrar servidores MCP en Claude Desktop ────────────────────────────
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

# ── 3. Script de login M365 remoto ────────────────────────────────────────────
New-Item -ItemType Directory -Force $loginDir | Out-Null
Invoke-WebRequest "$base/scripts/graph_login_remote.py" -OutFile "$loginDir\graph_login_remote.py" -UseBasicParsing

# Acceso directo en el escritorio
$shortcut = "$env:USERPROFILE\Desktop\Conectar M365 con Claude.lnk"
$wsh = New-Object -ComObject WScript.Shell
$lnk = $wsh.CreateShortcut($shortcut)
$lnk.TargetPath       = "powershell.exe"
$lnk.Arguments        = "-ExecutionPolicy Bypass -Command `"& { `$env:HEURA_REGISTER_SECRET='Heura2026!'; python '$loginDir\graph_login_remote.py' }; pause`""
$lnk.WorkingDirectory = $loginDir
$lnk.IconLocation     = "shell32.dll,144"
$lnk.Description      = "Conectar cuenta M365 con Claude"
$lnk.Save()
