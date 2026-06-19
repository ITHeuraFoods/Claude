$base = "https://raw.githubusercontent.com/ITHeuraFoods/Claude/main/deploy"

New-Item -ItemType Directory -Force "C:\ProgramData\ClaudeCode" | Out-Null

Invoke-WebRequest "$base/managed-settings.json" -OutFile "C:\ProgramData\ClaudeCode\managed-settings.json"
Invoke-WebRequest "$base/managed-mcp.json"       -OutFile "C:\ProgramData\ClaudeCode\managed-mcp.json"
