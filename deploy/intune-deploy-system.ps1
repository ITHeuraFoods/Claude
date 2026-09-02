# Ejecutar en Intune con "Run as logged on user = No" (SYSTEM)
# Instala managed-settings.json y las fuentes corporativas.
#
# Ruta correcta en Windows para que Claude Code lea la config gestionada (v2.1.75+):
# C:\Program Files\ClaudeCode\ — la ruta legacy C:\ProgramData\ClaudeCode\ ya no se soporta.
#
# Ya no desplegamos managed-mcp.json: daba control EXCLUSIVO sobre MCP (ningún usuario podía
# añadir MCP propios en ninguna máquina de la flota). sap-heura-remote y graph-heura-remote
# ahora se distribuyen como MCP del plugin heura-erp (plugins/heura-erp/.mcp.json), que no es
# exclusivo. Se borra el fichero si ya existe de un despliegue anterior.
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

try {
    New-Item -ItemType Directory -Force $dest | Out-Null

    Get-RemoteFile "$base/deploy/managed-settings.json" "$dest\managed-settings.json"

    Remove-Item -Force -ErrorAction SilentlyContinue "$dest\managed-mcp.json"
    Remove-Item -Force -ErrorAction SilentlyContinue "C:\ProgramData\ClaudeCode\managed-mcp.json"

    # Limpieza del montaje anterior del MCP de M365. El login ya no se hace con un script
    # local: se hace en el navegador contra https://mcp.heurafoods.com/auth/login, así que
    # C:\heura-mcp ya no hace falta en la flota. El acceso directo del escritorio se borra
    # porque llevaba el secreto de registro incrustado en sus argumentos.
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "C:\heura-mcp"
    Get-ChildItem "C:\Users\*\Desktop\Conectar M365 con Claude.lnk" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Write-Output "OK: limpieza del login M365 antiguo"

    # Fuentes: si fallan no deben bloquear el despliegue del plugin/MCP.
    try {
        $fontScript = "$dest\install-fonts.ps1"
        Get-RemoteFile "$base/deploy/install-fonts.ps1" $fontScript
        & $fontScript
    }
    catch {
        Write-Warning "Fuentes no instaladas (no bloqueante): $_"
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
