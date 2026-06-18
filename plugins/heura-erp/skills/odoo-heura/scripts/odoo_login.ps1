# ============================================================================
#  odoo_login.ps1 — Login Odoo en ventana segura (Heura)
#  Claude lo lanza con Start-Process cuando no hay sesion.
#  El usuario teclea sus credenciales AQUI; solo se guarda el cookie session_id.
# ============================================================================

$ErrorActionPreference = 'Stop'
$IsPS7 = $PSVersionTable.PSVersion.Major -ge 6
if (-not $IsPS7) {
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
}

$ODOO_URL   = 'https://erp.heurafoods.com'
$ODOO_DB    = 'heura_2024_06_28'
$TOKEN_FILE = Join-Path $env:TEMP '.odoo_session_heura.json'

Write-Host ''
Write-Host '======================================================' -ForegroundColor DarkCyan
Write-Host '   Odoo Heura - Inicio de sesion' -ForegroundColor Cyan
Write-Host '======================================================' -ForegroundColor DarkCyan
Write-Host '   Introduce tus credenciales Odoo. Tu contrasena se' -ForegroundColor Gray
Write-Host '   enmascara y NO se guarda en disco ni en el chat.' -ForegroundColor Gray
Write-Host ''

$cred = Get-Credential -Message 'Credenciales Odoo (usuario = email)'
if (-not $cred) { Write-Host 'Cancelado.' -ForegroundColor Yellow; Start-Sleep 2; exit 1 }

$user = $cred.UserName
$pass = $cred.GetNetworkCredential().Password

Write-Host "Validando como $user contra Odoo..." -ForegroundColor Gray

$body = @{
    jsonrpc = '2.0'; method = 'call'
    params  = @{ db = $ODOO_DB; login = $user; password = $pass }
} | ConvertTo-Json

try {
    if ($IsPS7) {
        $resp = Invoke-WebRequest -Uri "$ODOO_URL/web/session/authenticate" -Method Post `
                -Body $body -ContentType 'application/json' -SessionVariable session -TimeoutSec 30 -SkipCertificateCheck
    } else {
        $resp = Invoke-WebRequest -Uri "$ODOO_URL/web/session/authenticate" -Method Post `
                -Body $body -ContentType 'application/json' -SessionVariable session -TimeoutSec 30 -UseBasicParsing
    }
} catch {
    Write-Host "ERROR: no se pudo conectar ($($_.Exception.Message))" -ForegroundColor Red
    Start-Sleep 4; exit 1
}

$result = ($resp.Content | ConvertFrom-Json).result
if (-not $result -or -not $result.uid) {
    Write-Host 'ERROR: credenciales invalidas.' -ForegroundColor Red
    Start-Sleep 4; exit 1
}

# Extraer cookie session_id (NO la contrasena)
$cookies = @{}
foreach ($c in $session.Cookies.GetCookies($ODOO_URL)) { $cookies[$c.Name] = $c.Value }
if (-not $cookies.ContainsKey('session_id')) {
    Write-Host 'ADVERTENCIA: Odoo no devolvio session_id. Reintenta.' -ForegroundColor Red
    Start-Sleep 4; exit 1
}

$payload = @{ user = $user; uid = $result.uid; cookies = $cookies } | ConvertTo-Json -Compress
Set-Content -Path $TOKEN_FILE -Value $payload -Encoding UTF8
$pass = $null

Write-Host ''
Write-Host "Sesion iniciada como $user (uid $($result.uid)). Token guardado." -ForegroundColor Green
Write-Host 'Ya puedes volver a Claude y continuar con tu consulta.' -ForegroundColor Green
Write-Host ''
Start-Sleep 3
