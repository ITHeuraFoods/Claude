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
    $lnk.Arguments        = "-ExecutionPolicy Bypass -Command `"& { `$env:HEURA_REGISTER_SECRET='$RegisterSecret'; $pythonCmd '$loginScript' }; pause`""
    $lnk.WorkingDirectory = "C:\heura-mcp"
    $lnk.IconLocation     = "shell32.dll,144"
    $lnk.Description      = "Conectar cuenta M365 con Claude"
    $lnk.Save()

    Write-Output "Acceso directo creado: $shortcut"
    exit 0
}
catch {
    Write-Output "ERROR: $_"
    exit 1
}
