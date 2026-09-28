[CmdletBinding(SupportsShouldProcess = $true)]
param([string]$ShortcutDirectory)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne 'Win32NT') { throw '桌面快捷方式仅支持 Windows。' }
$appRoot = $PSScriptRoot
$desktopDirectory = if ($ShortcutDirectory) { [IO.Path]::GetFullPath($ShortcutDirectory) } else { [Environment]::GetFolderPath('Desktop') }
if (-not $desktopDirectory -or -not (Test-Path -LiteralPath $desktopDirectory -PathType Container)) {
    throw '没有找到当前用户的桌面文件夹。'
}
$launcherPath = Join-Path $appRoot '额度小站.vbs'
$pythonPath = Join-Path $appRoot '.venv\Scripts\pythonw.exe'
$scriptPath = Join-Path $appRoot 'app.py'
$hostPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
foreach ($requiredPath in @($launcherPath, $pythonPath, $scriptPath, $hostPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw '额度小站尚未安装完整，请先运行 install.ps1。'
    }
}
$launcherArguments = '"' + $launcherPath + '"'
$legacyArguments = '"' + $scriptPath + '"'
$shortcutShell = New-Object -ComObject WScript.Shell
$shortcutPath = $null
foreach ($name in @('额度小站.lnk', '额度小站-桌面小组件.lnk')) {
    $candidate = Join-Path $desktopDirectory $name
    if (-not (Test-Path -LiteralPath $candidate)) {
        $shortcutPath = $candidate
        break
    }
    $existing = $shortcutShell.CreateShortcut($candidate)
    $isCurrentLauncher = ($existing.TargetPath -eq $hostPath -and $existing.Arguments -eq $launcherArguments)
    $isLegacyLauncher = ($existing.TargetPath -eq $pythonPath -and $existing.Arguments -eq $legacyArguments)
    if ($isCurrentLauncher -or $isLegacyLauncher) {
        $shortcutPath = $candidate
        break
    }
}
if (-not $shortcutPath) {
    throw '两个同名桌面快捷方式都属于其他位置，未覆盖；请先重命名其中一个再重试。'
}
if (-not $PSCmdlet.ShouldProcess($shortcutPath, '创建或更新本项目的桌面快捷方式')) { return }
$shortcut = $shortcutShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $hostPath
$shortcut.Arguments = $launcherArguments
$shortcut.WorkingDirectory = $appRoot
$shortcut.Description = 'Codex、Qoder、WorkBuddy 剩余额度；单击切换，双击展开。'
$iconPath = Join-Path $appRoot 'icon.ico'
if (Test-Path -LiteralPath $iconPath -PathType Leaf) { $shortcut.IconLocation = $iconPath + ',0' }
$shortcut.WindowStyle = 1
$shortcut.Save()
$verified = $shortcutShell.CreateShortcut($shortcutPath)
if ($verified.TargetPath -ne $hostPath -or $verified.Arguments -ne $launcherArguments -or $verified.WorkingDirectory -ne $appRoot) {
    throw '快捷方式验证失败。'
}
Write-Output $shortcutPath
