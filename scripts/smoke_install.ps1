param([Parameter(Mandatory=$true)][string]$ReleaseDirectory)
$ErrorActionPreference = 'Stop'
$releasePath = (Resolve-Path -LiteralPath $ReleaseDirectory).Path
$version = (Get-Content -LiteralPath (Join-Path $releasePath 'release.json') -Raw | ConvertFrom-Json).version
$testRoot = Join-Path (Split-Path -Parent $PSScriptRoot) ('work/install-smoke-' + [guid]::NewGuid().ToString('N'))
$installRoot = Join-Path $testRoot '安装 目录'
$codexRoot = Join-Path $testRoot 'codex'
$skillsRoot = Join-Path $testRoot 'skills'
New-Item -ItemType Directory -Path $codexRoot -Force | Out-Null
$config = Join-Path $codexRoot 'config.toml'
[IO.File]::WriteAllText($config, "model = 'fixture-model'`n", (New-Object System.Text.UTF8Encoding($false)))
foreach ($attempt in 1..2) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $releasePath 'install.ps1') -InstallRoot $installRoot -CodexHome $codexRoot -SkillsDirectory $skillsRoot
    if ($LASTEXITCODE -ne 0) { throw "Install attempt $attempt failed" }
}
if (-not (Test-Path -LiteralPath (Join-Path $skillsRoot 'mysql-assistant/SKILL.md'))) { throw 'Skill missing' }
$content = [IO.File]::ReadAllText($config)
if (-not $content.Contains('fixture-model') -or -not $content.Contains('[mcp_servers.mysql-ai]')) { throw 'Registration or configuration preservation failed' }
$versionPath = Join-Path $installRoot "versions/$version"
$programPath = Join-Path $versionPath 'app/mysql-ai.exe'
& $programPath config wizard --help
if ($LASTEXITCODE -ne 0) { throw 'Frozen wizard command missing' }
$wizardHome = Join-Path $testRoot 'noninteractive-wizard'
$wizardOutput = '' | & $programPath --home $wizardHome config wizard
if ($LASTEXITCODE -ne 1 -or -not (($wizardOutput -join '') -match 'INTERACTIVE_REQUIRED')) { throw 'Frozen wizard must refuse pipe input' }
if (Test-Path -LiteralPath (Join-Path $wizardHome 'config/connections.json')) { throw 'Noninteractive wizard wrote configuration' }

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $versionPath 'uninstall.ps1') -CodexHome $codexRoot -RemoveProgramFiles
if ($LASTEXITCODE -ne 0) { throw 'Uninstall failed' }
$content = [IO.File]::ReadAllText($config)
if (Test-Path -LiteralPath $versionPath) { throw 'Version directory remains' }
if (-not $content.Contains('fixture-model') -or $content.Contains('[mcp_servers.mysql-ai]')) { throw 'Unregister changed unrelated configuration or retained MCP entry' }
Write-Host 'PASS: isolated install, repeat install, Skill, config preservation and uninstall'
