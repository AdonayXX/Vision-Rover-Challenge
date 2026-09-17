param(
    [string]$Port = 'COM3'
)

$ErrorActionPreference = 'Stop'

$serial = [System.IO.Ports.SerialPort]::new(
    $Port,
    115200,
    [System.IO.Ports.Parity]::None,
    8,
    [System.IO.Ports.StopBits]::One
)
$serial.ReadTimeout = 500
$serial.WriteTimeout = 1000

function Send-ReplLine {
    param([string]$Line)
    $serial.Write($Line + "`r`n")
    Start-Sleep -Milliseconds 180
}

try {
    $serial.Open()
    Start-Sleep -Milliseconds 350

    # Ensure CircuitPython is at the REPL.
    $serial.Write([char]3)
    Start-Sleep -Milliseconds 250
    $serial.Write("`r`n")
    Start-Sleep -Milliseconds 350
    [void]$serial.ReadExisting()

    $commands = @(
        'import json',
        'f=open("config_robot.json"); c=json.load(f); f.close()',
        'c["use_imu"]=False',
        'c["ask_wifi_on_boot"]=False',
        'c["control"]["turn_timeout"]=10.0',
        'c["control"]["max_duration"]=30.0',
        'c["control"]["kp"]=0.015',
        'c["control"]["ki"]=0.0005',
        'c["control"]["kd"]=0.002',
        'c["control"]["max_correction"]=0.3',
        'f=open("config_robot.json","w"); f.write(json.dumps(c)); f.close()',
        'print(c["use_imu"],c.get("ask_wifi_on_boot"),c["command_port"],c["control"]["left_sign"],c["control"]["right_sign"],c["control"]["turn_timeout"],c["control"]["max_duration"],c["control"]["kp"],c["control"]["ki"],c["control"]["kd"],c["control"]["max_correction"])'
    )

    foreach ($command in $commands) {
        Send-ReplLine $command
    }

    Start-Sleep -Milliseconds 900
    Write-Output '--- verification ---'
    Write-Output $serial.ReadExisting()

    # Reload code.py and capture startup output.
    $serial.Write([char]4)
    Start-Sleep -Seconds 4
    Write-Output '--- startup ---'
    Write-Output $serial.ReadExisting()
}
finally {
    if ($serial.IsOpen) {
        $serial.Close()
    }
    $serial.Dispose()
}
