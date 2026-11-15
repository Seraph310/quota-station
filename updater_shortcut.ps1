param([Parameter(Mandatory=$true)][string]$JobFile)
$ErrorActionPreference = 'Stop'
$job = Get-Content -LiteralPath $JobFile -Raw -Encoding UTF8 | ConvertFrom-Json
$binary = Join-Path $job.target 'QuotaStation.exe'
if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) { throw 'Installed app missing' }
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$appName = -join ([char[]](0x989D, 0x5EA6, 0x5C0F, 0x7AD9))
$widgetName = -join ([char[]](0x684C, 0x9762, 0x5C0F, 0x7EC4, 0x4EF6))
$sourceVbs = '"' + (Join-Path $job.source_root ($appName + '.vbs')) + '"'
$sourcePython = '"' + (Join-Path $job.source_root 'app.py') + '"'
foreach ($name in @(($appName + '.lnk'), ($appName + '-' + $widgetName + '.lnk'))) {
    $path = Join-Path $desktop $name
    if (Test-Path -LiteralPath $path) {
        $link = $shell.CreateShortcut($path)
        if ($link.Arguments -ne $sourceVbs -and $link.Arguments -ne $sourcePython -and $link.TargetPath -ne $binary) { continue }
    } else { $link = $shell.CreateShortcut($path) }
    $link.TargetPath = $binary
    $link.Arguments = ''
    $link.WorkingDirectory = $job.target
    $link.IconLocation = $binary + ',0'
    $link.Description = $appName
    $link.Save()
    break
}
