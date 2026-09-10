# Ejecutar en Intune con "Run as logged on user = Yes"
# Crea el acceso directo de login M365 para el usuario conectado.
#
# El secreto se pasa como parámetro en el comando de instalación de Intune, NUNCA se
# commitea al repo (este repo es público). Comando de ejemplo en Intune:
#   powershell.exe -ExecutionPolicy Bypass -File intune-deploy-user.ps1 -RegisterSecret "<secreto>"
param(
    [Parameter(Mandatory = $true)]
    [string]$RegisterSecret
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

try {
    # El script en sí (C:\heura-mcp\graph_login_remote.py) lo despliega intune-deploy-system.ps1,
    # ruta fija de máquina que también usa la skill m365-heura para su login automático.
    $loginScript = "C:\heura-mcp\graph_login_remote.py"
    if (-not (Test-Path $loginScript)) {
        Write-Warning "Aún no existe $loginScript (el script SYSTEM no ha corrido); el acceso directo funcionará cuando llegue."
    }

    # Misma ruta absoluta de Python que usa la skill, para evitar el alias-stub de la Microsoft
    # Store; si no existe en esta máquina, cae a "python" del PATH.
    $pythonAbs = "C:\Program Files\Python312\python.exe"
    $pythonCmd = if (Test-Path $pythonAbs) { "& '$pythonAbs'" } else { "python" }

    # Acceso directo en el escritorio
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    if (-not $desktopPath -or -not (Test-Path $desktopPath)) {
        throw "No se pudo resolver la carpeta Escritorio del usuario."
    }

    $shortcut = "$desktopPath\Conectar M365 con Claude.lnk"
    $wsh = New-Object -ComObject WScript.Shell
    $lnk = $wsh.CreateShortcut($shortcut)
    $lnk.TargetPath       = "powershell.exe"
    $lnk.Arguments        = "-ExecutionPolicy Bypass -Command `"& { `$env:HEURA_REGISTER_SECRET='$RegisterSecret'; `$env:HEURA_MCP_URL='http://mcp.heurafoods.com:3003'; $pythonCmd '$loginScript' }; pause`""
    $lnk.WorkingDirectory = Split-Path $loginScript
    $lnk.IconLocation     = "shell32.dll,144"
    $lnk.Description      = "Conectar cuenta M365 con Claude"
    $lnk.Save()

    Write-Output "Acceso directo creado: $shortcut"

    # ── Dependencias de Python ───────────────────────────────────────────────
    # No se pueden dar por supuestas: en el despliegue aparecieron equipos sin
    # msal. Se instalan en el ambito del usuario, sin necesidad de admin.
    if (Test-Path $pythonAbs) {
        if (-not (Test-Path "C:\Program Files\Python312\Lib\os.py")) {
            Write-Output "AVISO: la instalacion de Python esta incompleta (falta Lib\os.py). Hay que repararla."
        }
        else {
            & $pythonAbs -c "import msal, requests" 2>$null
            if ($LASTEXITCODE -ne 0) {
                Write-Output "Instalando msal y requests..."
                & $pythonAbs -m pip install --user --quiet --disable-pip-version-check msal requests 2>$null
                & $pythonAbs -c "import msal, requests" 2>$null
                if ($LASTEXITCODE -eq 0) { Write-Output "Dependencias instaladas." }
                else { Write-Output "AVISO: no se pudieron instalar msal y requests." }
            } else {
                Write-Output "Dependencias de Python ya presentes."
            }
        }
    } else {
        Write-Output "AVISO: no hay Python en $pythonAbs; el login no funcionara."
    }

    # ── Refrescar el marketplace de Heura ────────────────────────────────────
    # No nos fiamos de autoUpdate: el 2026-09-10 un clon llevaba 11 commits de
    # retraso pese a varios reinicios de Claude. Como el clon es un repo git
    # normal, lo forzamos aqui.
    #
    # fetch + reset --hard, NO pull: el clon acumula modificaciones locales
    # (entre otras, el token que el script de login escribe en el .mcp.json del
    # plugin) y un pull se quedaria bloqueado por el conflicto. Descartarlas es
    # seguro: la configuracion que Claude Code lee de verdad es ~/.claude.json,
    # y el login la reescribe.
    $mk = "$env:USERPROFILE\.claude\plugins\marketplaces\heura"
    $git = (Get-Command git -ErrorAction SilentlyContinue).Source
    if (-not $git) {
        foreach ($c in @("$env:ProgramFiles\Git\cmd\git.exe",
                         "${env:ProgramFiles(x86)}\Git\cmd\git.exe",
                         "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe")) {
            if (Test-Path $c) { $git = $c; break }
        }
    }

    if (-not (Test-Path "$mk\.git")) {
        Write-Output "Marketplace no clonado todavia; lo hara Claude al arrancar."
    }
    elseif (-not $git) {
        Write-Output "AVISO: no hay git en este equipo, el marketplace no se ha refrescado."
    }
    else {
        & $git -C $mk fetch --quiet origin 2>$null
        & $git -C $mk reset --hard --quiet origin/main 2>$null
        if ($LASTEXITCODE -eq 0) {
            $rev = (& $git -C $mk rev-parse --short HEAD).Trim()
            Write-Output "Marketplace heura actualizado a $rev"
        } else {
            Write-Output "AVISO: no se pudo refrescar el marketplace (revisar conectividad a GitHub)."
        }
    }

    exit 0
}
catch {
    Write-Output "ERROR: $_"
    exit 1
}
