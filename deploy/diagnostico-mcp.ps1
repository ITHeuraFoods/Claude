# Diagnostico de "no me aparecen los MCP de Heura".
# Solo lee, no cambia nada. Ejecutar en el equipo afectado, como el usuario.
#
#   irm https://raw.githubusercontent.com/ITHeuraFoods/Claude/main/deploy/diagnostico-mcp.ps1 | iex

$ok = "[ OK ]"; $ko = "[FALLA]"; $wr = "[ AVISO]"
$problemas = @()

function Reporta($estado, $texto) { Write-Host "$estado $texto" }

Write-Host ""
Write-Host "=== Diagnostico MCP de Heura ===" -ForegroundColor Cyan
Write-Host "Usuario: $env:USERNAME   Equipo: $env:COMPUTERNAME"
Write-Host ""

# 1. Politica de organizacion (la despliega intune-deploy-system.ps1)
# La ruta buena es Program Files; ProgramData es la legacy, sin soporte desde
# Claude Code v2.1.75, y en equipos antiguos puede quedar ahi un fichero viejo.
# Se miran las dos: buscar solo en ProgramData daba un FALLA falso en equipos
# correctamente desplegados.
$managed = @("C:\Program Files\ClaudeCode\managed-settings.json",
             "C:\ProgramData\ClaudeCode\managed-settings.json") |
           Where-Object { Test-Path $_ } | Select-Object -First 1
if ($managed) {
    if ($managed -like "C:\ProgramData\*") {
        Reporta $wr "managed-settings.json solo en la ruta legacy ($managed)"
        $problemas += "Volver a desplegar intune-deploy-system.ps1 (instala en Program Files)"
    }
    $m = Get-Content $managed -Raw | ConvertFrom-Json
    if ($m.enabledPlugins.'heura-erp@heura') {
        Reporta $ok "managed-settings.json presente y con heura-erp activado"
    } else {
        Reporta $ko "managed-settings.json presente pero SIN heura-erp activado"
        $problemas += "Volver a desplegar intune-deploy-system.ps1"
    }
} else {
    Reporta $ko "NO existe managed-settings.json en Program Files\ClaudeCode"
    $problemas += "Falta el script de sistema de Intune (intune-deploy-system.ps1)"
}

# 2. Marketplace clonado
$mk = "$env:USERPROFILE\.claude\plugins\marketplaces\heura"
if (Test-Path $mk) {
    $rev = ""
    $git = (Get-Command git -ErrorAction SilentlyContinue).Source
    if (-not $git -and (Test-Path "$env:ProgramFiles\Git\cmd\git.exe")) { $git = "$env:ProgramFiles\Git\cmd\git.exe" }
    if ($git -and (Test-Path "$mk\.git")) { $rev = (& $git -C $mk rev-parse --short HEAD 2>$null) }
    Reporta $ok "marketplace heura clonado$(if ($rev) { " (commit $rev)" })"
    $skill = "$mk\plugins\heura-erp\skills\sap-heura\SKILL.md"
    if ((Test-Path $skill) -and (Select-String -Path $skill -Pattern "sap-heura-remote" -Quiet)) {
        Reporta $ok "la skill sap-heura ya usa el MCP"
    } else {
        Reporta $wr "la skill sap-heura es la version vieja (ejecuta scripts en local)"
        $problemas += "Refrescar el marketplace: volver a lanzar el script de usuario de Intune"
    }
} else {
    Reporta $ko "el marketplace heura NO esta clonado"
    $problemas += "Claude no ha arrancado desde que llego la politica: CERRAR Claude del todo y volver a abrirlo"
}

# 3. Configuracion de usuario: es la que Claude Code lee de verdad
$uc = "$env:USERPROFILE\.claude.json"
$tieneToken = $false
if (Test-Path $uc) {
    $c = Get-Content $uc -Raw | ConvertFrom-Json
    $srv = $c.mcpServers.'graph-heura-remote'
    if ($srv) {
        if ($srv.headers.Authorization) {
            Reporta $ok "~/.claude.json tiene los servidores CON token"
            $tieneToken = $true
            # El de Odoo llego despues (2026-09-14) y no lo tiene quien se
            # registro antes; lo anade el script de usuario de Intune.
            $faltan = @('sap-heura-remote','odoo-heura-remote') |
                      Where-Object { -not $c.mcpServers.$_.headers.Authorization }
            if ($faltan) {
                Reporta $wr "faltan servidores en ~/.claude.json: $($faltan -join ', ')"
                $problemas += "Volver a lanzar el script de usuario de Intune, o el acceso directo de login"
            }
        } else {
            Reporta $ko "~/.claude.json tiene los servidores pero SIN token"
            $problemas += "Ejecutar el acceso directo 'Conectar M365 con Claude'"
        }
    } else {
        Reporta $ko "~/.claude.json NO tiene los servidores de Heura"
        $problemas += "Ejecutar el acceso directo 'Conectar M365 con Claude'"
    }
} else {
    Reporta $wr "~/.claude.json no existe todavia (Claude Code no se ha usado en este equipo)"
    $problemas += "Abrir Claude una vez y luego ejecutar el acceso directo"
}

# 4. Acceso directo de login
$lnk = [Environment]::GetFolderPath("Desktop") + "\Conectar M365 con Claude.lnk"
if (Test-Path $lnk) {
    Reporta $ok "acceso directo de login en el escritorio"
} else {
    Reporta $ko "NO esta el acceso directo en el escritorio"
    $problemas += "Falta el script de usuario de Intune (intune-wrapper-user.ps1)"
}

# 5. Red: el hub solo se alcanza por la VPN de Heura
try {
    $ip = (Resolve-DnsName mcp.heurafoods.com -Type A -ErrorAction Stop)[0].IPAddress
    Reporta $ok "mcp.heurafoods.com resuelve a $ip"
} catch {
    Reporta $ko "mcp.heurafoods.com NO resuelve"
    $problemas += "Problema de DNS"
}
$puertos = @{ 3001 = "SAP"; 3002 = "M365"; 3004 = "Odoo" }
$caidos = @()
foreach ($p in ($puertos.Keys | Sort-Object)) {
    if (Test-NetConnection mcp.heurafoods.com -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) {
        Reporta $ok "el hub responde en el $p ($($puertos[$p]))"
    } else {
        Reporta $ko "NO se alcanza el hub en el $p ($($puertos[$p]))"
        $caidos += $p
    }
}
if ($caidos.Count -eq $puertos.Count) {
    $problemas += "Conectar la VPN de Heura (FortiClient) y reintentar"
} elseif ($caidos.Count -gt 0) {
    # Si unos responden y otros no, no es la red del usuario: es el hub.
    $problemas += "Avisar a IT: el hub no escucha en $($caidos -join ', ') (servicio parado o puerto sin abrir en el FortiGate)"
}

# 6. Python, que necesita el script de login
$py = "C:\Program Files\Python312\python.exe"
if (Test-Path $py) {
    # Primero que el interprete arranque. Si le falta la biblioteca estandar,
    # toma el directorio actual como prefijo y muere con
    # "ModuleNotFoundError: No module named 'encodings'", que no tiene nada que
    # ver con las dependencias.
    if (-not (Test-Path "C:\Program Files\Python312\Lib\os.py")) {
        Reporta $ko "la instalacion de Python esta incompleta (falta Lib\os.py)"
        $problemas += "Reparar Python 3.12: Aplicaciones > Python 3.12 > Modificar > Repair"
    }
    else {
        $mods = & $py -c "import msal, requests; print('ok')" 2>$null
        if ($mods -eq "ok") { Reporta $ok "Python 3.12 con msal y requests" }
        else {
            Reporta $ko "Python arranca, pero faltan msal o requests"
            $problemas += "Instalar dependencias: & '$py' -m pip install msal requests"
        }
    }
} else {
    Reporta $ko "no esta Python en $py"
    $problemas += "Instalar Python 3.12 para todos los usuarios"
}

Write-Host ""
if ($problemas.Count -eq 0) {
    if ($tieneToken) {
        Write-Host "Todo correcto. Si aun asi no ves los MCP, cierra Claude DEL TODO y vuelve a abrirlo." -ForegroundColor Green
    }
} else {
    Write-Host "Que hacer, en este orden:" -ForegroundColor Yellow
    $i = 1
    foreach ($p in $problemas) { Write-Host "  $i. $p"; $i++ }
}
Write-Host ""
