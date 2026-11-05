# 尊重已有进程缓存配置；未设置时使用项目目录，不修改Windows全局设置。
$taskProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $taskProjectRoot
$taskCache = Join-Path $taskProjectRoot '.cache'
foreach ($taskName in @('NPM_CONFIG_CACHE','PIP_CACHE_DIR','UV_CACHE_DIR','PLAYWRIGHT_BROWSERS_PATH','MPLCONFIGDIR')) {
    if (-not [Environment]::GetEnvironmentVariable($taskName,'Process')) {
        [Environment]::SetEnvironmentVariable($taskName,(Join-Path $taskCache $taskName.ToLower()),'Process')
    }
}
if (-not $env:TEMP) { $env:TEMP = Join-Path $taskCache 'temp' }
if (-not $env:TMP) { $env:TMP = $env:TEMP }
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$taskPython = Join-Path $taskProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw '请先按 README 创建虚拟环境并安装依赖。'
}
& $taskPython (Join-Path $taskProjectRoot 'app.py')
exit $LASTEXITCODE
