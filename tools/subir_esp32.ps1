param(
    [string]$Port = "COM3",
    [string[]]$Files
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$CodeDir = Join-Path $ProjectRoot "base-robots\robots\codigos"

$DefaultFiles = @(
    "code.py",
    "wifi_command_receiver.py",
    "config_robot.json",
    "wifi_config.py",
    "control_movimiento.py",
    "sesion_comandos.py",
    "command_protocol.py",
    "ideaboard.py"
) | ForEach-Object { Join-Path $CodeDir $_ }

function Require-Ampy {
    if (-not (Get-Command ampy -ErrorAction SilentlyContinue)) {
        Write-Host "No encuentro 'ampy'. Instalalo con:" -ForegroundColor Yellow
        Write-Host "python -m pip install adafruit-ampy"
        throw "ampy no esta instalado"
    }
}

function Get-RemoteName {
    param([string]$Path)

    $name = [System.IO.Path]::GetFileName($Path)

    if ($name -eq "code_banco.py") {
        return "/code.py"
    }

    return "/$name"
}

function Upload-File {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Write-Host "No existe: $Path" -ForegroundColor Red
        return
    }

    $remote = Get-RemoteName $Path
    Write-Host "Subiendo $Path -> $remote"
    & ampy --port $Port put $Path $remote
    if ($LASTEXITCODE -ne 0) {
        throw "No pude subir $Path. Revisa que $Port no este abierto en Thonny, miniterm o VS Code."
    }
    Start-Sleep -Milliseconds 300
}

Require-Ampy

if (-not $Files -or $Files.Count -eq 0) {
    Write-Host "Sin archivos arrastrados: subiendo paquete estandar a $Port..."
    $Files = $DefaultFiles
}
else {
    Write-Host "Subiendo archivos arrastrados a $Port..."
}

foreach ($file in $Files) {
    if (Test-Path -LiteralPath $file -PathType Container) {
        Get-ChildItem -LiteralPath $file -File | ForEach-Object {
            Upload-File $_.FullName
        }
    }
    else {
        Upload-File $file
    }
}

Write-Host ""
Write-Host "Listo. Reiniciando placa..."
& ampy --port $Port reset --hard
if ($LASTEXITCODE -ne 0) {
    throw "Los archivos subieron, pero no pude reiniciar la placa. Revisa que $Port no este ocupado."
}
Write-Host "Carga terminada en $Port."
