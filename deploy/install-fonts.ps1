# install-fonts.ps1
# Instala las fuentes corporativas de Heura en el sistema.
# Ejecutar con permisos de administrador (Intune lo hace automáticamente).
#
# Requiere que los archivos .ttf estén en deploy/fonts/ del repo.
# Fuentes necesarias:
#   - Heura.ttf        (custom brand font, headings)
#   - Pixel-Grafiti.ttf (custom decorative font)
#
# Para obtener los .ttf: pedir al equipo de diseño los archivos originales
# (los .woff de heurafoods.com no son instalables como fuentes de sistema).

$base       = "https://raw.githubusercontent.com/ITHeuraFoods/Claude/main/deploy/fonts"
$fontsDir   = "C:\Windows\Fonts"
$tempDir    = "C:\ProgramData\ClaudeCode\fonts"
$regPath    = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"

$fonts = @(
    @{ file = "Heura.ttf";         regName = "Heura (TrueType)" },
    @{ file = "Pixel-Grafiti.ttf"; regName = "Pixel Grafiti (TrueType)" }
)

New-Item -ItemType Directory -Force $tempDir | Out-Null

foreach ($font in $fonts) {
    $dest = Join-Path $fontsDir $font.file

    if (Test-Path $dest) {
        Write-Output "Ya instalada: $($font.file)"
        continue
    }

    $tmp = Join-Path $tempDir $font.file
    try {
        Write-Output "Descargando $($font.file)..."
        Invoke-WebRequest "$base/$($font.file)" -OutFile $tmp -ErrorAction Stop

        Copy-Item $tmp $dest -Force
        New-ItemProperty -Path $regPath -Name $font.regName -Value $font.file `
            -PropertyType String -Force | Out-Null

        Write-Output "Instalada: $($font.file)"
    }
    catch {
        Write-Warning "No se pudo instalar $($font.file): $_"
    }
}

Write-Output "Instalacion de fuentes completada."
