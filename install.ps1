<#
.SYNOPSIS
Install this checkout's Windows dependencies without changing global settings.
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -DesktopShortcut
.EXAMPLE
.\install.ps1 -WithQoderSdk -Python 'C:\Path To Python\python.exe'
.NOTES
Python 3.11+ (64-bit) is required. The default install only needs requirements.txt.
The optional legacy Qoder SDK needs Node.js 20+ and npm; the standalone Qoder
App adapter does not need Node.js. Installation never starts a model task.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$DesktopShortcut,
    [switch]$WithQoderSdk,
    [string]$Python
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne 'Win32NT') { throw '额度小站目前仅支持 Windows。' }
$appRoot = $PSScriptRoot
$requirementsPath = Join-Path $appRoot 'requirements.txt'
$venvDirectory = Join-Path $appRoot '.venv'
$venvPython = Join-Path $venvDirectory 'Scripts\python.exe'
$venvPythonw = Join-Path $venvDirectory 'Scripts\pythonw.exe'
$sdkDirectory = Join-Path $appRoot 'providers\qoder_runtime'
foreach ($requiredFile in @($requirementsPath, (Join-Path $appRoot 'app.py'), (Join-Path $appRoot '额度小站.vbs'))) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) { throw '项目文件不完整，请重新下载完整项目。' }
}

function Get-PythonInfo {
    param([string]$Executable, [string[]]$Prefix = @())
    $probe = "import json,sys,struct; print(json.dumps({'executable':sys.executable,'major':sys.version_info[0],'minor':sys.version_info[1],'bits':struct.calcsize('P')*8}))"
    try {
        $output = & $Executable @Prefix -c $probe 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $info = ($output -join "`n") | ConvertFrom-Json
        if ($info.major -ne 3 -or $info.minor -lt 11 -or $info.bits -ne 64) { return $null }
        if (-not (Test-Path -LiteralPath $info.executable -PathType Leaf)) { return $null }
        return $info
    } catch { return $null }
}

function Find-Python {
    if ($Python) {
        $command = Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { throw '指定的 Python 程序不存在。请使用 python.exe 的完整路径。' }
        $info = Get-PythonInfo -Executable $command.Source
        if (-not $info) { throw '指定的 Python 不可用；需要 Windows 64 位 Python 3.11 或更高版本。' }
        return $info
    }
    foreach ($candidate in @('py.exe', 'python.exe', 'python3.exe')) {
        $command = Get-Command -Name $candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command -or $command.Source -like '*\Microsoft\WindowsApps\*') { continue }
        $prefix = @()
        if ($candidate -eq 'py.exe') { $prefix = @('-3') }
        $info = Get-PythonInfo -Executable $command.Source -Prefix $prefix
        if ($info) { return $info }
    }
    throw '未找到 Windows 64 位 Python 3.11+。安装 Python 后重试，或用 -Python 指定 python.exe 的完整路径。'
}

# -WhatIf reports the plan without launching installers or changing this checkout.
$action = '在项目 .venv 中安装 requirements.txt'
if ($WithQoderSdk) { $action += '；安装可选 Qoder SDK（有 Node.js 时）' }
if ($DesktopShortcut) { $action += '；创建桌面快捷方式' }
if (-not $PSCmdlet.ShouldProcess($appRoot, $action)) { return }

if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $pythonInfo = Get-PythonInfo -Executable $venvPython
    if (-not $pythonInfo) { throw '已有 .venv 不满足 Python 3.11+ / 64 位要求或已失效。已保留原目录，请检查后重试。' }
    Write-Host '使用项目已有的 .venv。'
} else {
    if (Test-Path -LiteralPath $venvDirectory) { throw '已有 .venv 目录不完整。已保留原目录，请检查或重命名后重试。' }
    $pythonInfo = Find-Python
    Write-Host ('使用 Python {0}.{1} 创建项目独立环境。' -f $pythonInfo.major, $pythonInfo.minor)
    & $pythonInfo.executable -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0) { throw '创建 .venv 失败；请检查 Python 的 venv 支持和项目文件夹写入权限。' }
}
if (-not (Test-Path -LiteralPath $venvPythonw -PathType Leaf)) { throw '项目环境缺少 pythonw.exe，请检查 Windows Python 安装。' }
& $venvPython -m pip install --disable-pip-version-check -r $requirementsPath
if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败，请检查上方错误及网络后重试。已有文件已保留。' }
& $venvPython -c "import PySide6, cryptography; print('Python dependencies ready')"
if ($LASTEXITCODE -ne 0) { throw 'Python 依赖验证失败，请查看上方错误。' }

if ($WithQoderSdk) {
    $nodeCommand = Get-Command -Name node.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $npmCommand = Get-Command -Name npm.cmd -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $nodeCommand -or -not $npmCommand) {
        Write-Warning '未找到 Node.js 和 npm，已跳过可选 Qoder SDK。新版 Qoder App 额度读取仍可使用；安装 Node.js 20+ 后可重跑 -WithQoderSdk。'
    } else {
        $nodeMajor = & $nodeCommand.Source -p "process.versions.node.split('.')[0]"
        if ($LASTEXITCODE -ne 0 -or [int]$nodeMajor -lt 20) { throw '可选 Qoder SDK 需要 Node.js 20+，Python 依赖已安装。' }
        if (-not (Test-Path -LiteralPath (Join-Path $sdkDirectory 'package-lock.json') -PathType Leaf)) {
            throw 'Qoder SDK 的 package-lock.json 缺失，未执行 npm 安装。'
        }
        Push-Location -LiteralPath $sdkDirectory
        try {
            & $npmCommand.Source ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw '可选 Qoder SDK 安装失败；Python 依赖已保留，请查看上方错误后重试。' }
        } finally { Pop-Location }
    }
} else {
    Write-Host '未安装可选的旧版 Qoder SDK 回退；需要时用 -WithQoderSdk 再运行。'
}

if ($DesktopShortcut) { & (Join-Path $appRoot 'setup_desktop.ps1') }
Write-Host '安装完成。双击项目中的「额度小站.vbs」启动。'
Write-Host '安装过程不会启动小组件、登录账号、设置开机启动或修改全局设置。'
