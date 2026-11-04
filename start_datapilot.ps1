# 在当前进程中设置 D 盘临时目录和缓存，不修改 Windows 全局设置。
$taskProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $taskProjectRoot
$env:TEMP = 'D:\CodexData\temp'
$env:TMP = 'D:\CodexData\temp'
$env:NPM_CONFIG_CACHE = 'D:\CodexData\caches\npm'
$env:PIP_CACHE_DIR = 'D:\CodexData\caches\pip'
$env:UV_CACHE_DIR = 'D:\CodexData\caches\uv'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\CodexData\caches\playwright'
$env:MPLCONFIGDIR = 'D:\CodexData\caches\matplotlib'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$taskPython = Join-Path $taskProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw '请先按 README 创建虚拟环境并安装依赖。'
}
& $taskPython (Join-Path $taskProjectRoot 'app.py')
