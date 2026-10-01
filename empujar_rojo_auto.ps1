param(
    [string]$RobotIp,
    [switch]$SoloVerificar,
    [switch]$SensorMiraCubo,
    [ValidateSet(-1, 1)]
    [int]$SignoGiro = 1  # medido 2026-09-30: con -1 el rover giraba al reves
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $repo "vision-system\.venv\Scripts\python.exe"
$prueba = Join-Path $repo "base-robots\robots\pc\prueba_transporte_cubo.py"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Falta el entorno Python de vision-system\.venv."
}

# Conserva velocidades, frescura de vision, sensores y limites del controlador.
$opciones = @("-X", "utf8", "-B", "-u", $prueba,
              "--robot-id", "10", "--cube", "red", "--depot", "red",
              "--turn-sign", "$SignoGiro",
              # Un resultado de color (4 barridos) tarda ~6-8 s y el primero
              # suele descartarse; se exige uno nuevo antes de cada empuje.
              "--color-timeout-seconds", "30",
              "--max-seconds", "300")
if (-not $SoloVerificar -and -not $SensorMiraCubo) {
    throw "Indica -SensorMiraCubo cuando el sensor de color mire hacia la cara del cubo."
}

# Primero comprueba la escena actual sin abrir la conexion de motores.
& $python @opciones --solo-verificar
if ($LASTEXITCODE -ne 0 -or $SoloVerificar) {
    exit $LASTEXITCODE
}
if ($RobotIp) {
    $opciones += @("--robot-ip", $RobotIp)
}
Write-Host "Prueba de un cubo: rojo a zona roja. Ctrl+C detiene el rover."
& $python @opciones --usar-sensores --sensor-mira-cubo
exit $LASTEXITCODE
