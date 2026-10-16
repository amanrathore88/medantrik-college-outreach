$ErrorActionPreference = 'Stop'
$url = 'http://127.0.0.1:5050'

# Stop any running instance on port 5050 so that latest code and 217 colleges are loaded
$existing = Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    foreach ($conn in $existing) {
        if ($conn.OwningProcess -gt 0) {
            Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Milliseconds 400
}

$pythonCommand = Get-Command python -ErrorAction Stop
$process = Start-Process -FilePath $pythonCommand.Source -ArgumentList 'dashboard.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput "$PSScriptRoot/dashboard-output.log" -RedirectStandardError "$PSScriptRoot/dashboard-error.log" -PassThru
for ($attempt = 0; $attempt -lt 15; $attempt++) {
    Start-Sleep -Milliseconds 300
    $process.Refresh()
    if ($process.HasExited) { throw 'Dashboard stopped. Check dashboard-error.log and whether port 5050 is occupied.' }
    try {
        $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 1
        if ($health.application -eq 'medantrik-outreach' -and $health.status -eq 'ok') {
            Start-Process $url
            exit 0
        }
    } catch { }
}
throw 'Dashboard did not become ready. Check dashboard-error.log.'
