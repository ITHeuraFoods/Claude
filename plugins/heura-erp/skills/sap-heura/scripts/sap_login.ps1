# ============================================================================
#  sap_login.ps1 — Login SAP en ventana segura (Heura)
#  Claude lo lanza automáticamente con Start-Process cuando no hay sesión.
#  El usuario teclea sus credenciales AQUÍ (enmascaradas), nunca en el chat.
#  Solo se guarda el token de sesión temporal; la contraseña no se persiste.
# ============================================================================

$ErrorActionPreference = 'Stop'

# Aceptar el certificado autofirmado de SAP en PS 7 y en Windows PowerShell 5.1
$IsPS7 = $PSVersionTable.PSVersion.Major -ge 6
if (-not $IsPS7) {
    try { [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true } } catch {}
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
}

$SAP_HOST   = 'https://10.3.2.48:44300'
$SAP_VHOST  = 'vhfftps4ci.sap.heurafoods.com'
$SAP_CLIENT = '100'
$TOKEN_FILE = Join-Path $env:TEMP '.sap_session_heura.json'
$TEST_URL   = "$SAP_HOST/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder?`$top=1"

Write-Host ''
Write-Host '======================================================' -ForegroundColor DarkCyan
Write-Host '   SAP Heura - Inicio de sesion' -ForegroundColor Cyan
Write-Host '======================================================' -ForegroundColor DarkCyan
Write-Host '   Introduce tus credenciales SAP. Tu contrasena se' -ForegroundColor Gray
Write-Host '   enmascara y NO se guarda en disco ni en el chat.' -ForegroundColor Gray
Write-Host ''

# Pedir credenciales en la misma ventana PowerShell (funciona en todos los entornos)
$user = Read-Host 'Usuario SAP'
$secPass = Read-Host 'Contraseña SAP' -AsSecureString
$pass = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPass)
)
if (-not $user -or -not $pass) { Write-Host 'Cancelado.' -ForegroundColor Yellow; Start-Sleep 2; exit 1 }

Write-Host "Validando como $user contra SAP..." -ForegroundColor Gray

$headers = @{
  'sap-client' = $SAP_CLIENT
  'Host'       = $SAP_VHOST
  'Accept'     = 'application/json'
}
$pair  = "$($user):$($pass)"
$basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
$headers['Authorization'] = "Basic $basic"

try {
    $session = $null
    if ($IsPS7) {
        $resp = Invoke-WebRequest -Uri $TEST_URL -Headers $headers -SessionVariable session -TimeoutSec 30 -SkipCertificateCheck -UseBasicParsing
    } else {
        $resp = Invoke-WebRequest -Uri $TEST_URL -Headers $headers -SessionVariable session -TimeoutSec 30 -UseBasicParsing
    }
} catch {
    Write-Host "ERROR: credenciales invalidas o sin acceso ($($_.Exception.Message))" -ForegroundColor Red
    Start-Sleep 4
    exit 1
}

# Extraer cookies de sesión (SAP_SESSIONID...) — NO la contraseña
$cookies = @{}
foreach ($c in $session.Cookies.GetCookies($SAP_HOST)) {
    $cookies[$c.Name] = $c.Value
}

$hasSession = $false
foreach ($k in $cookies.Keys) { if ($k -like 'SAP_SESSIONID*') { $hasSession = $true } }
if (-not $hasSession) {
    Write-Host 'ADVERTENCIA: SAP no emitio cookie de sesion. Reintenta.' -ForegroundColor Red
    Start-Sleep 4
    exit 1
}

$payload = @{ user = $user; cookies = $cookies } | ConvertTo-Json -Compress
Set-Content -Path $TOKEN_FILE -Value $payload -Encoding UTF8

# limpiar variable de contraseña en memoria
$pass = $null; $basic = $null; $pair = $null

Write-Host ''
Write-Host "Sesion iniciada como $user. Token temporal guardado." -ForegroundColor Green
Write-Host 'Ya puedes volver a Claude y continuar con tu consulta.' -ForegroundColor Green
Write-Host ''
Start-Sleep 3
