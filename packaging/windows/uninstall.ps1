param(
    [string]$CodexHome = (Join-Path $env:USERPROFILE '.codex'),
    [switch]$RemoveProgramFiles
)
$ErrorActionPreference = 'Stop'
$versionPath = [IO.Path]::GetFullPath($PSScriptRoot)
$program = Join-Path $versionPath 'app/mysql-ai.exe'
if (-not (Test-Path -LiteralPath (Join-Path $versionPath '.mysql-ai-version'))) { throw '请运行已安装版本目录内的卸载脚本。' }
& $program unregister --codex-home $CodexHome
if ($LASTEXITCODE -ne 0) { throw '注册配置存在冲突，未删除程序。' }
if ($RemoveProgramFiles) {
    $parent = Split-Path -Parent $versionPath
    if ((Split-Path -Leaf $parent) -ne 'versions' -or (Split-Path -Leaf $versionPath) -notmatch '^\d+\.\d+\.\d+$') { throw '安装目录结构不符合要求。' }
    if (-not $versionPath.StartsWith($parent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '删除路径越界。' }
    if ((Get-Item -LiteralPath $versionPath).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '不删除重解析目录。' }
    if (Get-ChildItem -LiteralPath $versionPath -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw '安装目录含重解析点，未删除。' }
    Remove-Item -LiteralPath $versionPath -Recurse -Force
}
Write-Host 'MCP 已移除；数据库配置、凭据、日志和 Skill 保留。'
