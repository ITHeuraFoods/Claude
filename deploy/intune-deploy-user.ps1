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

    # ── Servidores MCP nuevos para quien ya hizo login ───────────────────────
    # El token que emite /register no es por servicio: identifica a la persona y
    # vale para los tres MCP. Asi que cuando se anade un servidor al hub (Odoo,
    # 2026-09-14) no hay que hacer que 30 personas repitan el login: basta con
    # copiar el token que ya tienen a la entrada nueva de ~/.claude.json.
    # Quien aun no se haya registrado no se ve afectado: el script de login ya
    # crea los tres.
    $uc = "$env:USERPROFILE\.claude.json"
    $nuevos = @{ "odoo-heura-remote" = "http://mcp.heurafoods.com:3004/mcp" }
    if (Test-Path $uc) {
        try {
            $cfg = Get-Content $uc -Raw -Encoding UTF8 | ConvertFrom-Json
            $tok = $cfg.mcpServers.'graph-heura-remote'.headers.Authorization
            if ($tok) {
                $anadidos = 0
                foreach ($n in $nuevos.Keys) {
                    if (-not $cfg.mcpServers.$n) {
                        $cfg.mcpServers | Add-Member -NotePropertyName $n -NotePropertyValue ([pscustomobject]@{
                            type    = "http"
                            url     = $nuevos[$n]
                            headers = [pscustomobject]@{ Authorization = $tok }
                        })
                        $anadidos++
                    }
                }
                if ($anadidos -gt 0) {
                    Copy-Item $uc "$uc.bak" -Force
                    # -Depth 100 (el maximo) NO es por exceso: ~/.claude.json
                    # guarda el historial por proyecto y ConvertTo-Json trunca
                    # en silencio lo que pase de la profundidad pedida. Truncar
                    # aqui seria cargarse la configuracion de la persona.
                    $json = $cfg | ConvertTo-Json -Depth 100
                    Set-Content $uc -Value $json -Encoding UTF8
                    # Verificar que lo escrito sigue siendo valido y completo;
                    # si no, volver atras y no tocar nada.
                    $sano = $false
                    try {
                        $rl = Get-Content $uc -Raw -Encoding UTF8 | ConvertFrom-Json
                        $sano = [bool]$rl.mcpServers.'graph-heura-remote'.headers.Authorization
                    } catch { $sano = $false }
                    if ($sano) {
                        Write-Output "Anadidos $anadidos servidor(es) MCP nuevos reutilizando el token existente."
                    } else {
                        Copy-Item "$uc.bak" $uc -Force
                        Write-Output "AVISO: la escritura de ~/.claude.json no quedo sana; restaurado el respaldo. El usuario tendra que lanzar el acceso directo de login."
                    }
                } else {
                    Write-Output "No hay servidores MCP nuevos que anadir."
                }
            } else {
                Write-Output "El usuario aun no tiene token; lo creara el acceso directo de login."
            }
        } catch {
            Write-Output "AVISO: no se pudo actualizar ~/.claude.json ($_)."
        }
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
