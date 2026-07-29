# scripts/build.ps1: Windows PowerShell 打包入口（等价 PYTHON=python bash scripts/build.sh）
#
# build.sh 是跨平台 bash 脚本（mac/linux/windows CI 共用），Windows 下只是 bash 不一定在
# PowerShell 的 PATH。本脚本自动定位 Git for Windows 的 bash，设好 PYTHON=python（绕开
# python3 stub），再跑 build.sh。打包逻辑仍由 build.sh 单一维护，这里只做入口包装。
#
# 用法（PowerShell，在项目根）:
#   .\scripts\build.ps1
#   .\scripts\build.ps1 --mode standalone
#
# 若被执行策略拦截:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1

$ErrorActionPreference = "Stop"
$env:PYTHON = "python"

# 定位 bash：PATH 优先，否则常见 Git for Windows 安装路径
$bash = (Get-Command bash -ErrorAction SilentlyContinue).Source
if (-not $bash) {
    $candidates = @(
        "C:\Program Files\Git\bin\bash.exe",
        "C:\Program Files (x86)\Git\bin\bash.exe",
        "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe"
    )
    $bash = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $bash) {
    Write-Error @"
找不到 bash。build.sh 是 bash 脚本，需要 Git for Windows（含 bash）。
  - 若已装 Git for Windows：开始菜单搜 "Git Bash" 打开，在其中跑 bash scripts/build.sh
  - 若未装：https://git-scm.com/download/win
"@
    exit 1
}

$buildSh = Join-Path $PSScriptRoot "build.sh"
if (-not (Test-Path $buildSh)) {
    Write-Error "找不到 build.sh: $buildSh"
    exit 1
}

Write-Host "==> bash: $bash"
Write-Host "==> PYTHON=$env:PYTHON"
& $bash $buildSh @args
