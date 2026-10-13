# Per-process execution policy is set by the reviewed native hook command.
# No profile or global execution policy is changed.
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$taskRuntime = Join-Path $PSScriptRoot '../runtime/python.exe'
$taskEntry = Join-Path $PSScriptRoot 'entry.py'
& $taskRuntime $taskEntry hook
exit $LASTEXITCODE
