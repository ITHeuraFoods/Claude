# Ejecutar en Intune con "Run as logged on user = No" (SYSTEM)
# Instala managed-settings, managed-mcp y fuentes corporativas en ProgramData
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$base = "https://raw.githubusercontent.com/ITHeuraFoods/Claude/main"
$dest = "C:\ProgramData\ClaudeCode"

New-Item -ItemType Directory -Force $dest | Out-Null

# Dar permisos de escritura a Users para que el script de usuario pueda actualizar después
$acl = Get-Acl $dest
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("Users", "Modify", "ContainerInherit,ObjectInherit", "None", "Allow")
$acl.SetAccessRule($rule)
Set-Acl $dest $acl

Invoke-WebRequest "$base/deploy/managed-settings.json" -OutFile "$dest\managed-settings.json" -UseBasicParsing
Invoke-WebRequest "$base/deploy/managed-mcp.json"       -OutFile "$dest\managed-mcp.json"       -UseBasicParsing

$fontScript = "$dest\install-fonts.ps1"
Invoke-WebRequest "$base/deploy/install-fonts.ps1" -OutFile $fontScript -UseBasicParsing
PowerShell.exe -ExecutionPolicy Bypass -File $fontScript
