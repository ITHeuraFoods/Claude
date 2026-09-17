# Ejecutar en Intune con "Run as logged on user = No" (SYSTEM)
# Instala managed-settings.json, el script de login M365, Python 3.12 con msal y requests,
# y las fuentes corporativas.
#
# Python lo instalaba el script de junio (intune_deploy_heura_m365.ps1), ya retirado: los
# equipos enrolados o reinstalados despues se quedaban sin el y el acceso directo de login
# no arrancaba (2026-09-17). Ahora va aqui, en contexto SYSTEM, y el script de usuario solo
# tiene que comprobar que msal y requests estan.
#
# Ruta correcta en Windows para que Claude Code lea la config gestionada (v2.1.75+):
# C:\Program Files\ClaudeCode\ — la ruta legacy C:\ProgramData\ClaudeCode\ ya no se soporta.
#
# Ya no desplegamos managed-mcp.json: daba control EXCLUSIVO sobre MCP (ningún usuario podía
# añadir MCP propios en ninguna máquina de la flota). Se borra el fichero si ya existe de un
# despliegue anterior. Los servidores MCP (sap, graph, odoo) los escribe el acceso directo de
# login en el ~/.claude.json de cada persona, CON su token. El plugin no declara ninguno: una
# entrada sin token siempre recibe 401 del hub (asi fue hasta la 1.4.0; retirado en la 1.5.0).
#
# Log de despliegue: C:\ProgramData\HeuraIT\claude-deploy-system.log — primer sitio donde
# mirar si un equipo no recibe el plugin.

# Intune ejecuta los platform scripts en PowerShell de 32 bits por defecto; relanzar en 64
# bits para que el registro de fuentes en HKLM no acabe redirigido a WOW6432Node.
if ($env:PROCESSOR_ARCHITEW6432) {
    & "$env:WINDIR\SysNative\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $MyInvocation.MyCommand.Path
    exit $LASTEXITCODE
}

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$logDir = "C:\ProgramData\HeuraIT"
New-Item -ItemType Directory -Force $logDir | Out-Null
Start-Transcript -Path "$logDir\claude-deploy-system.log" -Force

$base = "https://raw.githubusercontent.com/ITHeuraFoods/Claude/main"
$dest = "C:\Program Files\ClaudeCode"

# Descarga a .tmp y mueve al final: si la descarga se corta no queda un fichero a medias.
function Get-RemoteFile($url, $outFile) {
    $tmp = "$outFile.tmp"
    Invoke-WebRequest $url -OutFile $tmp -UseBasicParsing
    Move-Item $tmp $outFile -Force
    Write-Output "OK: $outFile"
}

# ── Python 3.12 machine-wide + msal/requests ─────────────────────────────────
# Corre como SYSTEM: NUNCA el comando "python" a pelo, porque el alias de la Microsoft Store
# lo secuestra y ese stub no existe en contexto SYSTEM. Siempre la ruta real del .exe.
$PY_DIR = "C:\Program Files\Python312"
$PY_URL = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"

function Test-PythonWorks($exe) {
    if (-not $exe -or -not (Test-Path $exe)) { return $false }
    if ($exe -like "*\WindowsApps\*") { return $false }          # stub de la Store
    if (-not (Test-Path (Join-Path (Split-Path $exe) "Lib\os.py"))) { return $false }  # instalacion rota
    & $exe -c "print('ok')" 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Find-Python {
    foreach ($c in @("$PY_DIR\python.exe") + (Get-ChildItem "C:\Program Files\Python3*\python.exe", "C:\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object FullName)) {
        if (Test-PythonWorks $c) { return $c }
    }
    return $null
}

function Remove-BrokenPython {
    # Desinstala Python/py-launcher previos: causa del 0x80070643 (1603) al reinstalar.
    $keys = @("HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
              "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*")
    Get-ItemProperty $keys -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -match "Python (3\.|Launcher)" -and $_.UninstallString } |
        ForEach-Object {
            try {
                if ($_.UninstallString -match "msiexec") {
                    $code = ($_.UninstallString -replace '.*({[0-9A-Fa-f\-]+}).*', '$1')
                    Start-Process msiexec.exe -ArgumentList "/x $code /quiet /norestart" -Wait -ErrorAction SilentlyContinue
                } else {
                    Start-Process $_.UninstallString -ArgumentList "/quiet /uninstall" -Wait -ErrorAction SilentlyContinue
                }
            } catch {}
        }
    Get-ChildItem "C:\Program Files\Python3*", "C:\Python3*" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

function Install-Python {
    $inst = "$env:TEMP\python312_setup.exe"
    Invoke-WebRequest $PY_URL -OutFile $inst -UseBasicParsing
    # Include_launcher=0: el py launcher huerfano es lo que provocaba el 0x80070643.
    $args = "/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=0 Include_test=0 AssociateFiles=0 TargetDir=`"$PY_DIR`""
    $p = Start-Process -FilePath $inst -ArgumentList $args -Wait -PassThru
    Remove-Item $inst -Force -ErrorAction SilentlyContinue
    return $p.ExitCode
}

function Ensure-Python {
    # Devuelve $true si al terminar hay Python operativo con msal y requests.
    $exe = Find-Python
    if (-not $exe) {
        Write-Output "Python no encontrado: instalando 3.12 para todos los usuarios..."
        $code = Install-Python
        if ($code -ne 0) {
            Write-Output "El instalador devolvio $code; limpio restos y reintento."
            Remove-BrokenPython
            $code = Install-Python
        }
        if ($code -ne 0) { Write-Output "ERROR: el instalador de Python fallo dos veces (codigo $code)."; return $false }
        $exe = Find-Python
        if (-not $exe) { Write-Output "ERROR: Python no aparece tras la instalacion."; return $false }
    }
    Write-Output "Python: $exe"
    # Dependencias machine-wide (site-packages del sistema): visibles para todos los usuarios.
    & $exe -c "import msal, requests" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Output "Instalando msal y requests..."
        # Salida visible en el transcript: si pip falla (proxy, PyPI, permisos) hay que verlo.
        & $exe -m pip install --disable-pip-version-check --no-warn-script-location --upgrade msal requests 2>&1 |
            ForEach-Object { Write-Output "  pip: $_" }
        & $exe -c "import msal, requests" 2>$null
        if ($LASTEXITCODE -ne 0) { Write-Output "ERROR: no se pudieron instalar msal y requests (ver lineas pip: arriba)."; return $false }
    }
    Write-Output "msal y requests: OK"
    return $true
}

try {
    New-Item -ItemType Directory -Force $dest | Out-Null

    Get-RemoteFile "$base/deploy/managed-settings.json" "$dest\managed-settings.json"

    Remove-Item -Force -ErrorAction SilentlyContinue "$dest\managed-mcp.json"
    Remove-Item -Force -ErrorAction SilentlyContinue "C:\ProgramData\ClaudeCode\managed-mcp.json"

    # Script de login M365 remoto — ruta fija de máquina, la misma que espera la skill m365-heura
    # (ver "Login automático" en el SKILL.md del plugin heura-erp). Va aquí, no en el script de
    # usuario, porque C:\heura-mcp requiere permisos de administrador para crearse.
    New-Item -ItemType Directory -Force "C:\heura-mcp" | Out-Null
    Get-RemoteFile "$base/scripts/graph_login_remote.py" "C:\heura-mcp\graph_login_remote.py"

    # Python + msal: si falla, se sigue con el resto y se devuelve exit 1 al final para que
    # Intune lo reintente y el equipo salga como Failed.
    $pythonOk = $false
    try { $pythonOk = Ensure-Python } catch { Write-Output "ERROR instalando Python: $_" }

    # Fuentes: si fallan no deben bloquear el despliegue del plugin/MCP.
    try {
        $fontScript = "$dest\install-fonts.ps1"
        Get-RemoteFile "$base/deploy/install-fonts.ps1" $fontScript
        & $fontScript
    }
    catch {
        Write-Warning "Fuentes no instaladas (no bloqueante): $_"
    }

    if (-not $pythonOk) {
        Write-Output "Despliegue SYSTEM completado SIN Python operativo: el login M365 no funcionara en este equipo."
        Stop-Transcript
        exit 1
    }
    Write-Output "Despliegue SYSTEM completado."
    Stop-Transcript
    exit 0
}
catch {
    Write-Output "ERROR en despliegue SYSTEM: $_"
    Stop-Transcript
    exit 1
}
