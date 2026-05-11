$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "../../../../../..")).Path
$RuntimeDir = Join-Path $Root ".audiagentic\runtime\goose"

# Resolve goose.exe: explicit env var > dist build > legacy cache
if ($env:GOOSE_BIN) {
  $GooseBin = $env:GOOSE_BIN
} else {
  $GooseBin = Get-ChildItem -Path (Join-Path $Root "dist") -Recurse -Filter "goose.exe" `
              -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
  if (-not $GooseBin) {
    $GooseBin = Join-Path $Root ".audiagentic\provisioning\goose\bin\goose.exe"
  }
}

if (-not (Test-Path $GooseBin)) {
  throw "Goose binary not found. Run build-release.ps1 first."
}

foreach ($sub in @("sessions","logs","config","state","data")) {
  New-Item -ItemType Directory -Force -Path (Join-Path $RuntimeDir $sub) | Out-Null
}

if (-not $env:OPENAI_HOST)             { $env:OPENAI_HOST = "http://127.0.0.1:42001/v1" }
if (-not $env:OPENAI_API_KEY)          { $env:OPENAI_API_KEY = "dummy" }
if (-not $env:GOOSE_PROVIDER)          { $env:GOOSE_PROVIDER = "openai" }
if (-not $env:GOOSE_MODEL)             { $env:GOOSE_MODEL = "qwen3.5-2b" }
if (-not $env:GOOSE_MODE)              { $env:GOOSE_MODE = "chat" }
if (-not $env:GOOSE_MAX_TURNS)         { $env:GOOSE_MAX_TURNS = "5" }
if (-not $env:GOOSE_TEMPERATURE)       { $env:GOOSE_TEMPERATURE = "0.0" }
if (-not $env:GOOSE_TELEMETRY_ENABLED) { $env:GOOSE_TELEMETRY_ENABLED = "false" }
if (-not $env:GOOSE_PATH_ROOT)         { $env:GOOSE_PATH_ROOT = $RuntimeDir }

$Prompt = "Respond with exactly: audiagentic-goose-local-ok"

Write-Host "Smoke test: $env:OPENAI_HOST model=$env:GOOSE_MODEL"

$Output = & $GooseBin run -t $Prompt 2>&1
$Status = $LASTEXITCODE

Write-Host $Output

if ($Status -ne 0) {
  throw "goose run failed (status $Status)"
}

if ($Output -notmatch "audiagentic-goose-local-ok") {
  throw "Smoke phrase not found in output"
}

Write-Host "Stage 0 smoke test passed."
