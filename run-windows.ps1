$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$BackendEnv = Join-Path $Backend ".env"
$ModelLine = Get-Content (Join-Path $Backend ".env") |
    Where-Object { $_ -match "^OLLAMA_MODEL=" } |
    Select-Object -First 1
$Model = if ($ModelLine) { $ModelLine -replace "^OLLAMA_MODEL=", "" } else { "qwen2.5:7b-instruct" }

foreach ($CommandName in @("python", "node", "npm", "ollama", "curl.exe")) {
    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "Required command is missing: $CommandName"
    }
}

$TesseractLine = Get-Content $BackendEnv |
    Where-Object { $_ -match "^TESSERACT_CMD=" } |
    Select-Object -First 1
$TesseractSetting = if ($env:TESSERACT_CMD) {
    $env:TESSERACT_CMD
}
elseif ($TesseractLine) {
    ($TesseractLine -split "=", 2)[1].Trim().Trim('"').Trim("'")
}
else {
    ""
}
$TesseractCommand = if ($TesseractSetting) {
    Get-Command $TesseractSetting -ErrorAction SilentlyContinue
}
else {
    Get-Command "tesseract" -ErrorAction SilentlyContinue
}
if (-not $TesseractCommand) {
    throw "Tesseract OCR is required. Install Tesseract with Turkish (tur) and English (eng) language data, or set TESSERACT_CMD in backend\.env."
}
$TesseractLanguages = & $TesseractCommand.Source --list-langs 2>&1
if ($LASTEXITCODE -ne 0 -or $TesseractLanguages -notmatch "(?m)^tur$" -or $TesseractLanguages -notmatch "(?m)^eng$") {
    throw "Tesseract must have both tur and eng language data installed."
}

$OllamaReady = $false
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
    $OllamaReady = $true
}
catch {
    $OllamaLog = Join-Path $Root "ollama.log"
    $OllamaErrorLog = Join-Path $Root "ollama-error.log"
    $OllamaProcess = Start-Process -FilePath "ollama" -ArgumentList "serve" `
        -WorkingDirectory $Root -RedirectStandardOutput $OllamaLog `
        -RedirectStandardError $OllamaErrorLog -PassThru
    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
        Start-Sleep -Seconds 1
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
            $OllamaReady = $true
            break
        }
        catch {
            if ($OllamaProcess.HasExited) { break }
        }
    }
}
if (-not $OllamaReady) {
    throw "Ollama is unavailable. Check ollama.log and ensure Ollama is installed."
}

$InstalledModels = (& ollama list | Out-String)
if ($InstalledModels -notmatch [regex]::Escape($Model)) {
    & ollama pull $Model
    if ($LASTEXITCODE -ne 0) { throw "Failed to download Ollama model $Model." }
}

$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    & python -m venv (Join-Path $Backend ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Failed to create backend virtual environment." }
}
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Failed to update pip." }
& $VenvPython -m pip install -r (Join-Path $Backend "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Failed to install backend requirements." }

if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    Push-Location $Frontend
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw "Failed to install frontend dependencies." }
    }
    finally {
        Pop-Location
    }
}
Push-Location $Frontend
try {
    & npm.cmd run build -- --webpack
    if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed." }
}
finally {
    Pop-Location
}

$BackendOut = Join-Path $Root "backend.log"
$BackendErr = Join-Path $Root "backend-error.log"
$FrontendOut = Join-Path $Root "frontend.log"
$FrontendErr = Join-Path $Root "frontend-error.log"
$NodePath = (Get-Command "node.exe").Source
$NextCli = Join-Path $Frontend "node_modules\next\dist\bin\next"
$BackendProcess = Start-Process -FilePath $VenvPython `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
    -WorkingDirectory $Backend -RedirectStandardOutput $BackendOut `
    -RedirectStandardError $BackendErr -PassThru
$FrontendProcess = Start-Process -FilePath $NodePath `
    -ArgumentList @($NextCli, "start", "--hostname", "127.0.0.1", "--port", "3000") `
    -WorkingDirectory $Frontend -RedirectStandardOutput $FrontendOut `
    -RedirectStandardError $FrontendErr -PassThru

Write-Output "Frontend: http://127.0.0.1:3000"
Write-Output "Backend API: proxied through Next.js at /api/v1/clinical/*"
Write-Output "Processes: backend PID $($BackendProcess.Id), frontend PID $($FrontendProcess.Id)"
Write-Warning "Local-only bind is intentional. Do not expose clinical traffic without TLS and authentication."
