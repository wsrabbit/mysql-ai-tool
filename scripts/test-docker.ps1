param([string]$Image = 'mysql:8.4', [string]$ReportName = 'mysql-integration', [string]$Executable = '')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先执行 uv sync --group build。' }
if ($ReportName -notmatch '^[a-zA-Z0-9_-]+$') { throw '无效的报告名称。' }
if ($Executable) {
    $Executable = (Resolve-Path -LiteralPath $Executable).Path
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw '找不到指定的 MCP 可执行程序。' }
}
$runId = [guid]::NewGuid().ToString('N')
$testDirectory = Join-Path $projectRoot "work/docker-$runId"
$outputDirectory = Join-Path $projectRoot 'outputs'
New-Item -ItemType Directory -Path $testDirectory,$outputDirectory -Force | Out-Null
$testRootPassword = [guid]::NewGuid().ToString('N')
$testReadPassword = [guid]::NewGuid().ToString('N')
$utf8 = New-Object System.Text.UTF8Encoding($false)
$envPath = Join-Path $testDirectory 'mysql.env'
[IO.File]::WriteAllText($envPath, "MYSQL_ROOT_PASSWORD=$testRootPassword`n", $utf8)
$initPath = Join-Path $testDirectory 'init.sql'
$fixture = @"
SET NAMES utf8mb4;
CREATE DATABASE shop CHARACTER SET utf8mb4;
CREATE USER 'ai_reader'@'%' IDENTIFIED BY '$testReadPassword';
GRANT SELECT, SHOW VIEW ON shop.* TO 'ai_reader'@'%';
USE shop;
CREATE TABLE customers (id INT PRIMARY KEY, name VARCHAR(50));
CREATE TABLE orders (id BIGINT PRIMARY KEY, customer_id INT, amount DECIMAL(20,2),
status VARCHAR(20), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
FOREIGN KEY (customer_id) REFERENCES customers(id));
INSERT INTO customers VALUES (1,'测试客户');
INSERT INTO orders (id,customer_id,amount,status) VALUES
(1,1,10.10,'paid'),(2,1,20.20,'paid'),(3,1,5.00,'pending');
"@
[IO.File]::WriteAllText($initPath, $fixture, $utf8)
$containerId = $null
$testExit = 1
try {
    Write-Host "创建独立测试容器 $Image（首次需要下载镜像）..."
    $containerOutput = & docker run --detach --name "mysql-ai-test-$runId" --publish '127.0.0.1::3306' --env-file $envPath --mount "type=bind,source=$initPath,target=/docker-entrypoint-initdb.d/01-fixture.sql,readonly" $Image
    if ($LASTEXITCODE -ne 0) { throw 'Docker 启动失败；请检查引擎和镜像网络。' }
    $containerId = ($containerOutput | Select-Object -Last 1).Trim()
    if ($containerId -notmatch '^[a-f0-9]{64}$') { throw 'Docker 未返回有效容器 ID。' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        $ErrorActionPreference = 'Continue'
        & docker exec --env "MYSQL_PWD=$testReadPassword" $containerId mysql --protocol=tcp --host '127.0.0.1' --user ai_reader -N -e 'SELECT COUNT(*) FROM shop.orders' 2>$null | Out-Null
        $probeExit = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($probeExit -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw '测试数据库初始化超时。' }
    $portText = (& docker port $containerId '3306/tcp' | Select-Object -First 1).Trim()
    if ($portText -notmatch '^127\.0\.0\.1:(\d+)$') { throw '端口绑定未限制为本机。' }
    $env:MYSQL_AI_TEST_PORT = $Matches[1]
    $env:MYSQL_AI_TEST_PASSWORD = $testReadPassword
    $env:MYSQL_AI_RUN_INTEGRATION = '1'
    if ($Executable) { $env:MYSQL_AI_TEST_EXECUTABLE = $Executable }
    $env:PYTHONUTF8 = '1'
    Write-Host '执行真实 MySQL 集成测试...'
    $ErrorActionPreference = 'Continue'
    $testOutput = & $pythonPath -m pytest tests/integration -q -p no:cacheprovider -W error::pytest.PytestUnraisableExceptionWarning "--basetemp=$testDirectory/pytest" "--junitxml=$outputDirectory/$ReportName.xml" 2>&1
    $testExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $testText = ($testOutput | ForEach-Object { $_.ToString() }) -join "`n"
    [IO.File]::WriteAllText("$outputDirectory/$ReportName.txt", $testText, $utf8)
    Write-Output $testText
} finally {
    Remove-Item Env:MYSQL_AI_TEST_PASSWORD,Env:MYSQL_AI_RUN_INTEGRATION,Env:MYSQL_AI_TEST_PORT -ErrorAction SilentlyContinue
    if ($Executable) { Remove-Item Env:MYSQL_AI_TEST_EXECUTABLE -ErrorAction SilentlyContinue }
    if ($containerId -match '^[a-f0-9]{64}$') {
        & docker rm --force --volumes $containerId | Out-Null
    }
    # Delete only the two generated credential-bearing files in this exact run directory.
    foreach ($generatedFile in @($envPath, $initPath)) {
        $resolvedFile = [IO.Path]::GetFullPath($generatedFile)
        if (-not $resolvedFile.StartsWith([IO.Path]::GetFullPath($testDirectory) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '清理路径越界。' }
        Remove-Item -LiteralPath $resolvedFile -Force -ErrorAction SilentlyContinue
    }
}
exit $testExit
