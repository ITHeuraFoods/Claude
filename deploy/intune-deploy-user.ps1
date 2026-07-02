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

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$base     = "https://raw.githubusercontent.com/ITHeuraFoods/Claude/main"
$loginDir = "$env:USERPROFILE\.claude\heura-m365"

New-Item -ItemType Directory -Force $loginDir | Out-Null
Invoke-WebRequest "$base/scripts/graph_login_remote.py" -OutFile "$loginDir\graph_login_remote.py" -UseBasicParsing

# Acceso directo en el escritorio
$desktopPath = [Environment]::GetFolderPath("Desktop")
if ($desktopPath -and (Test-Path $desktopPath)) {
    $shortcut = "$desktopPath\Conectar M365 con Claude.lnk"
    $wsh = New-Object -ComObject WScript.Shell
    $lnk = $wsh.CreateShortcut($shortcut)
    $lnk.TargetPath       = "powershell.exe"
    $lnk.Arguments        = "-ExecutionPolicy Bypass -Command `"& { `$env:HEURA_REGISTER_SECRET='$RegisterSecret'; python '$loginDir\graph_login_remote.py' }; pause`""
    $lnk.WorkingDirectory = $loginDir
    $lnk.IconLocation     = "shell32.dll,144"
    $lnk.Description      = "Conectar cuenta M365 con Claude"
    $lnk.Save()
}
