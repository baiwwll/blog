# -*- coding: utf-8 -*-
<#
    电机选型程序 —— 一键打包脚本

    用法（在本目录下）：

      # ① 打包成文件夹（推荐：启动快、无需自解压），并直接放到桌面「工作」
      powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -Folder -OutDir "$env:USERPROFILE\Desktop\工作"

      # ② 只打包成文件夹，留在 dist\ 下
      powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -Folder

      # ③ 打包成单个 exe（拷给别人最方便，但首次启动要自解压，慢 1~3 秒）
      powershell -ExecutionPolicy Bypass -File .\build_exe.ps1

    说明：
      * -OutDir 指定的目录若已存在，只会清掉里面的 电机选型程序.exe 与 _internal，
        userdata（用户型号库/方案/报告）会保留
      * 本工程内置了绿色 PyInstaller（tools\_pylibs），断网也能打包
#>
param(
    [switch]$Folder,                 # 打包成文件夹（onedir）
    [string]$OutDir = ''             # 成品输出目录，例如 桌面\工作
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $here
$AppName = '电机选型程序'

Write-Host '=== 1/5 检查 Python ===' -ForegroundColor Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw ' 没有找到 python，请先安装 Python 3.9+ 并加入 PATH'
}
Write-Host ('  ' + (& python --version))

Write-Host '=== 2/5 准备 PyInstaller ===' -ForegroundColor Cyan
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'

# 优先使用工程内自带的绿色 PyInstaller（tools\_pylibs）：
# 适合无法联网 / pip 装不进系统目录的环境
$localLibs = Join-Path $here 'tools\_pylibs'
if (Test-Path (Join-Path $localLibs 'PyInstaller')) {
    $env:PYTHONPATH = $localLibs
    Write-Host ('  使用工程内置 PyInstaller：' + $localLibs)
}

& python -m PyInstaller --version
$piOk = ($LASTEXITCODE -eq 0)
if (-not $piOk) {
    Write-Host '  本机没有 PyInstaller，尝试用 pip 安装 ...' -ForegroundColor Yellow
    & python -m pip install pyinstaller
    & python -m PyInstaller --version
    $piOk = ($LASTEXITCODE -eq 0)
}
if (-not $piOk) {
    $ErrorActionPreference = $prevEap
    throw @'
 pyinstaller 不可用。可选方案：
   1) 联网正常时： python -m pip install pyinstaller
   2) 无法联网 / pip 写入被拒时（本工程已验证可用）：
        python tools\fetch_pyinstaller.py     # 用 HTTP 镜像抓 wheel
        python tools\unpack_wheels.py         # 直接解包到 tools\_pylibs
      然后重新运行本脚本
'@
}
$ErrorActionPreference = $prevEap

Write-Host '=== 3/5 清理旧产物 ===' -ForegroundColor Cyan
foreach ($p in @('build', 'dist', "$AppName.spec")) {
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}

Write-Host '=== 4/5 开始打包 ===' -ForegroundColor Cyan
$mode = if ($Folder) { '--onedir' } else { '--onefile' }
Write-Host ('  模式：' + $mode + '   窗口程序（无控制台）')

& python -m PyInstaller `
    --noconfirm `
    --clean `
    $mode `
    --windowed `
    --name $AppName `
    --hidden-import core `
    --hidden-import core.database `
    --hidden-import core.entities `
    --hidden-import core.mechanics `
    --hidden-import core.report `
    --hidden-import core.resources `
    --hidden-import core.selector `
    --exclude-module numpy `
    --exclude-module matplotlib `
    --exclude-module PIL `
    main.py

if ($LASTEXITCODE -ne 0) { throw ' 打包失败：PyInstaller 返回非 0' }

Write-Host '=== 5/5 整理产物 ===' -ForegroundColor Cyan
if ($Folder) {
    $source = Join-Path $here ('dist\' + $AppName)
    if (-not (Test-Path (Join-Path $source ($AppName + '.exe')))) { throw ' 打包失败：没有生成 exe' }
} else {
    $source = Join-Path $here ('dist\' + $AppName + '.exe')
    if (-not (Test-Path $source)) { throw ' 打包失败：没有生成 exe' }
    Copy-Item $source (Join-Path $here ($AppName + '.exe')) -Force
}

if ($OutDir -ne '') {
    $target = [System.IO.Path]::GetFullPath($OutDir)
    if (-not (Test-Path $target)) { New-Item -ItemType Directory -Force -Path $target | Out-Null }
    foreach ($item in @($AppName + '.exe', '_internal')) {
        $old = Join-Path $target $item
        if (Test-Path $old) { Remove-Item $old -Recurse -Force }
    }
    if ($Folder) {
        Copy-Item (Join-Path $source '*') $target -Recurse -Force
    } else {
        Copy-Item $source (Join-Path $target ($AppName + '.exe')) -Force
    }
    $sizeMb = [math]::Round(((Get-ChildItem $target -Recurse -File |
        Measure-Object -Property Length -Sum).Sum) / 1MB, 1)
    Write-Host ''
    Write-Host ('打包完成 ✔  输出目录：' + $target + '  (合计 ' + $sizeMb + ' MB)') -ForegroundColor Green
    Write-Host ('双击运行：' + (Join-Path $target ($AppName + '.exe'))) -ForegroundColor Green
} else {
    Write-Host ''
    if ($Folder) {
        Write-Host ('打包完成 ✔  文件夹：' + $source) -ForegroundColor Green
        Write-Host ('双击运行：' + (Join-Path $source ($AppName + '.exe'))) -ForegroundColor Green
    } else {
        Write-Host ('打包完成 ✔  ' + (Join-Path $here ($AppName + '.exe'))) -ForegroundColor Green
    }
}
