$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repo

python -B .\base-robots\robots\pc\prueba_transporte_cubo.py `
    --robot-ip 192.168.40.18 `
    --robot-port 5000 `
    --vision-host 127.0.0.1 `
    --vision-port 2026 `
    --robot-id 10 `
    --peer-id 11 `
    --cube red `
    --depot red `
    --max-age-ms 1200 `
    --approach-speed 0.35 `
    --push-speed 0.55 `
    --turn-speed 0.22 `
    --max-seconds 120
