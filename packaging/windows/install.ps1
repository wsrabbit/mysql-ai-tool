param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'mysql-ai-tools'),
    [string]$CodexHome = (Join-Path $env:USERPROFILE '.codex'),
    [string]$SkillsDirectory = (Join-Path $env:USERPROFILE '.agents/skills')
)
$ErrorActionPreference = 'Stop'
$bundleRoot = $PSScriptRoot
$sourceProgram = Join-Path $bundleRoot 'app/mysql-ai.exe'
if (-not (Test-Path -LiteralPath $sourceProgram)) { throw '请从完整发布包目录运行安装脚本。' }
$manifest = Get-Content -LiteralPath (Join-Path $bundleRoot 'release.json') -Raw | ConvertFrom-Json
if ($manifest.version -notmatch '^\d+\.\d+\.\d+$') { throw '发布版本无效。' }
foreach ($file in $manifest.files) {
    $filePath = [IO.Path]::GetFullPath((Join-Path $bundleRoot $file.path))
    if (-not $filePath.StartsWith([IO.Path]::GetFullPath($bundleRoot) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '校验清单路径越界。' }
    if ((Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash -ne $file.sha256) { throw "发布文件校验失败：$($file.path)" }
}
$installPath = [IO.Path]::GetFullPath($InstallRoot)
$versionPath = Join-Path $installPath "versions/$($manifest.version)"
if (-not (Test-Path -LiteralPath $versionPath)) {
    $versionsRoot = [IO.Path]::GetFullPath((Join-Path $installPath 'versions'))
    $stagePath = [IO.Path]::GetFullPath((Join-Path $versionsRoot ('.install-' + [guid]::NewGuid().ToString('N'))))
    if (-not $stagePath.StartsWith($versionsRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or -not ([IO.Path]::GetFullPath($versionPath)).StartsWith($versionsRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '安装暂存路径越界。' }
    New-Item -ItemType Directory -Path $stagePath -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $bundleRoot 'app') -Destination $stagePath -Recurse
    Copy-Item -LiteralPath (Join-Path $bundleRoot 'plugins') -Destination $stagePath -Recurse
    Copy-Item -LiteralPath (Join-Path $bundleRoot 'uninstall.ps1') -Destination $stagePath
    Set-Content -LiteralPath (Join-Path $stagePath '.mysql-ai-version') -Value $manifest.version -Encoding utf8
    & (Join-Path $stagePath 'app/mysql-ai.exe') --home $installPath doctor
    if ($LASTEXITCODE -ne 0) { throw '暂存程序自检失败；原安装和注册保持不变。' }
    # Both absolute move paths above are checked to remain under this installation's versions directory.
    Move-Item -LiteralPath $stagePath -Destination $versionPath
}
$targetProgram = Join-Path $versionPath 'app/mysql-ai.exe'
# Verify the installed app against this exact release, including repeat installations.
foreach ($file in $manifest.files | Where-Object { $_.path.StartsWith('app/') }) {
    $targetFile = Join-Path $versionPath $file.path
    if (-not (Test-Path -LiteralPath $targetFile)) { throw '已安装版本不完整，请恢复该版本发布包。' }
    if ((Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash -ne $file.sha256) { throw '已安装的同名版本内容不同；未覆盖。' }
}
& $targetProgram --home $installPath doctor
if ($LASTEXITCODE -ne 0) { throw '新版本自检失败；未切换 Codex 注册。' }
$skillPath = Join-Path $versionPath 'plugins/mysql-ai-tools/skills/mysql-assistant'
# The optional plugin artifact points to this computer's installed executable.
$mcpDefinition = @{ mcpServers = @{ 'mysql-ai' = @{ command = $targetProgram; args = @('serve'); env = @{ MYSQL_AI_HOME = $installPath } } } }
$mcpDefinition | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $versionPath 'plugins/mysql-ai-tools/.mcp.json') -Encoding utf8
& $targetProgram --home $installPath register --codex-home $CodexHome --skill-source $skillPath --skills-dir $SkillsDirectory
if ($LASTEXITCODE -ne 0) { throw '注册失败，请查看错误；已保留程序文件。' }
Write-Host "安装完成。配置连接：& '$targetProgram' --home '$installPath' config add dev --host 127.0.0.1 --user ai_reader --database shop"
Write-Host '配置后运行 doctor --connection dev，并新建 Codex 会话。'
