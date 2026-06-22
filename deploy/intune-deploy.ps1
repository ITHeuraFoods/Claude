$base = "https://raw.githubusercontent.com/ITHeuraFoods/Claude/main/deploy"

New-Item -ItemType Directory -Force "C:\ProgramData\ClaudeCode" | Out-Null

# Claude Code managed config
Invoke-WebRequest "$base/managed-settings.json" -OutFile "C:\ProgramData\ClaudeCode\managed-settings.json"
Invoke-WebRequest "$base/managed-mcp.json"       -OutFile "C:\ProgramData\ClaudeCode\managed-mcp.json"

# Fuentes corporativas Heura
$fontScript = "C:\ProgramData\ClaudeCode\install-fonts.ps1"
Invoke-WebRequest "$base/install-fonts.ps1" -OutFile $fontScript
PowerShell.exe -ExecutionPolicy Bypass -File $fontScript
