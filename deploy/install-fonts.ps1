# install-fonts.ps1
# Instala las fuentes corporativas de Heura en el sistema.
# Ejecutar con permisos de administrador (Intune lo hace automáticamente).
#
# Instala Poppins (familia completa) como fuente de sistema.
# Fuente: Brand Kit Heura en SharePoint (00.3 Heura® Typefonts/Poppins/).
# Los archivos .ttf están en deploy/fonts/ del repo.
#
# NOTA: Las fuentes "Heura" y "Pixel Grafiti" son web-only (.woff) y el equipo
# de brand las ha marcado como "DO NOT USE" para documentos/presentaciones.
# Solo se despliega Poppins.

$base       = "https://raw.githubusercontent.com/ITHeuraFoods/Claude/main/deploy/fonts"
$fontsDir   = "C:\Windows\Fonts"
$tempDir    = "C:\ProgramData\ClaudeCode\fonts"
$regPath    = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"

$fonts = @(
    @{ file = "Poppins-Regular.ttf";      regName = "Poppins (TrueType)" },
    @{ file = "Poppins-Medium.ttf";       regName = "Poppins Medium (TrueType)" },
    @{ file = "Poppins-SemiBold.ttf";     regName = "Poppins SemiBold (TrueType)" },
    @{ file = "Poppins-Bold.ttf";         regName = "Poppins Bold (TrueType)" },
    @{ file = "Poppins-ExtraBold.ttf";    regName = "Poppins ExtraBold (TrueType)" },
    @{ file = "Poppins-Black.ttf";        regName = "Poppins Black (TrueType)" },
    @{ file = "Poppins-Italic.ttf";       regName = "Poppins Italic (TrueType)" },
    @{ file = "Poppins-BoldItalic.ttf";   regName = "Poppins Bold Italic (TrueType)" }
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
