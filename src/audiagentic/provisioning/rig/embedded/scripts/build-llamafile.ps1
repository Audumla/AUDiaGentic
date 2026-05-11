# Build llamafile Vulkan DLL for AMD GPU + download base llamafile + model.
# Prerequisites: CMake, Vulkan SDK, MSYS2, VS Build Tools 2022
# Output: .audiagentic/provisioning/rig/embedded/bin/
param(
  [switch]$SkipPrereqs,
  [switch]$SkipBuild,
  [switch]$SkipDownload
)
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "../../../../../..")).Path
$BinDir = Join-Path $Root ".audiagentic\provisioning\rig\embedded\bin"
$BuildDir = Join-Path $Root ".audiagentic\provisioning\rig\embedded\build"
$LlamafileRepo = Join-Path $BuildDir "llamafile"

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

$VulkanSdk = $env:VULKAN_SDK
if (-not $VulkanSdk -and (Test-Path "G:\development\tools\VulkanSDK")) {
  $VulkanSdk = Get-ChildItem "G:\development\tools\VulkanSDK" -Directory | Sort-Object Name -Descending | Select-Object -First 1
  if ($VulkanSdk) { $VulkanSdk = $VulkanSdk.FullName; $env:VULKAN_SDK = $VulkanSdk }
}

##############################################
# Step 1: Check/install prerequisites
##############################################
if (-not $SkipPrereqs) {
  $NeedMsys2 = -not (Get-Command msys2.exe -ErrorAction SilentlyContinue) -and -not (Test-Path "H:\development\tools\msys64\msys2.exe")
  $NeedVsBuildTools = -not (Test-Path "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC")

  if (-not $NeedMsys2 -and -not $NeedVsBuildTools) {
    Write-Host "Prerequisites already present."
  } else {
    if ($NeedMsys2) {
      Write-Host "Installing MSYS2..."
      $MsysInstaller = Join-Path $env:TEMP "msys2-x86_64.exe"
      $ReleaseInfo = Invoke-RestMethod -UseBasicParsing "https://api.github.com/repos/msys2/msys2-installer/releases/latest"
      $Asset = $ReleaseInfo.assets | Where-Object { $_.name -match 'msys2-x86_64-latest\.exe' } | Select-Object -First 1
      if (-not $Asset) { Write-Error "Could not find MSYS2 installer asset"; exit 1 }
      Invoke-WebRequest -UseBasicParsing $Asset.browser_download_url -OutFile $MsysInstaller
      Start-Process -FilePath $MsysInstaller -ArgumentList "/silent", "/dir=C:\msys64" -Wait -NoNewWindow
      Remove-Item $MsysInstaller -ErrorAction SilentlyContinue
      Write-Host "  MSYS2 installed to C:\msys64"
    }

    if ($NeedVsBuildTools) {
      Write-Host "Installing Visual Studio Build Tools 2022..."
      $VsBootstrapper = Join-Path $env:TEMP "vs_BuildTools.exe"
      Invoke-WebRequest -UseBasicParsing "https://aka.ms/vs/17/release/vs_BuildTools.exe" -OutFile $VsBootstrapper
      Start-Process -FilePath $VsBootstrapper -ArgumentList `
        "--quiet", "--wait", "--norestart", "--nocache",
        "--add", "Microsoft.VisualStudio.Workload.VCTools",
        "--add", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
        "--add", "Microsoft.VisualStudio.Component.Windows11SDK.22621" `
        -Wait -NoNewWindow
      Remove-Item $VsBootstrapper -ErrorAction SilentlyContinue
      Write-Host "  VS Build Tools installed"
    }
  }
}

##############################################
# Step 2: Setup llamafile repo
##############################################
if (-not $SkipBuild) {
  if (-not (Test-Path (Join-Path $LlamafileRepo ".git"))) {
    Write-Host "Cloning llamafile repo..."
    & git clone --depth 1 --branch 0.10.1 https://github.com/mozilla-ai/llamafile.git $LlamafileRepo
  }

  Write-Host "Running make setup (initializing submodules + patches)..."
  $RepoPathMsys = $LlamafileRepo -replace '([A-Z]):', '/$1' -replace '\\', '/'
  $MsysPath = if (Test-Path "H:\development\tools\msys64\msys2.exe") { "H:\development\tools\msys64\msys2.exe" } else { "C:\msys64\msys2.exe" }
  & $MsysPath -defterm -no-start -here -no-page -c "cd '$RepoPathMsys' && pacman -Syu --noconfirm && pacman -S --noconfirm git patch unzip wget make && make setup"

  ##############################################
  # Step 3: Build Vulkan DLL
  ##############################################
  Write-Host "Building ggml-vulkan.dll..."
  if ($VulkanSdk) { Write-Host "  Using Vulkan SDK: $VulkanSdk" }
  else { Write-Warning "VULKAN_SDK not found. Build may fail." }

  $VulkanBat = Join-Path $LlamafileRepo "llamafile\vulkan.bat"
  if (-not (Test-Path $VulkanBat)) {
    # Try root level for older versions
    $VulkanBat = Join-Path $LlamafileRepo "vulkan.bat"
  }
  Push-Location (Split-Path $VulkanBat -Parent)
  try {
    & .\vulkan.bat --output (Join-Path $BinDir "ggml-vulkan.dll")
  } finally {
    Pop-Location
  }

  if (Test-Path (Join-Path $BinDir "ggml-vulkan.dll")) {
    $DllSize = (Get-Item (Join-Path $BinDir "ggml-vulkan.dll")).Length / 1MB
    Write-Host "  ggml-vulkan.dll built successfully ($([math]::Round($DllSize, 1)) MB)"
  } else {
    Write-Error "Vulkan DLL build failed. Check output above."
    exit 1
  }

  }

##############################################
# Step 3: Download llamafile + model
##############################################
if (-not $SkipDownload) {
  $ModelUrl = if ($env:MODEL_URL) { $env:MODEL_URL } else { "https://huggingface.co/bartowski/Qwen_Qwen3.5-2B-GGUF/resolve/main/Qwen_Qwen3.5-2B-Q4_K_S.gguf" }
  $ModelFile = Join-Path $BinDir "Qwen_Qwen3.5-2B-Q4_K_S.gguf"

  $LlamafileVersion = if ($env:LLAMAFILE_VERSION) { $env:LLAMAFILE_VERSION } else { "0.10.1" }
  $LlamafileUrl = "https://github.com/mozilla-ai/llamafile/releases/download/$LlamafileVersion/llamafile-$LlamafileVersion"
  $LlamafileBin = Join-Path $BinDir "llamafile.exe"

  # Download llamafile base
  if (-not (Test-Path $LlamafileBin)) {
    Write-Host "Downloading llamafile $LlamafileVersion..."
    Invoke-WebRequest -UseBasicParsing $LlamafileUrl -OutFile $LlamafileBin
    Write-Host "  -> $LlamafileBin"
  } else {
    Write-Host "llamafile already present: $LlamafileBin"
  }

  # Download GGUF model
  if (-not (Test-Path $ModelFile)) {
    Write-Host "Downloading model (this may take a while)..."
    Write-Host "  $ModelUrl"
    Invoke-WebRequest -UseBasicParsing $ModelUrl -OutFile $ModelFile
    Write-Host "  -> $ModelFile"
  } else {
    Write-Host "Model already present: $ModelFile"
  }
}

##############################################
# Summary
##############################################
Write-Host ""
Write-Host "Rig contents:"
Get-ChildItem $BinDir -File | ForEach-Object {
  $Size = if ($_.Length -gt 1MB) { "$([math]::Round($_.Length / 1MB, 1)) MB" } else { "$([math]::Round($_.Length / 1KB, 0)) KB" }
  Write-Host "  $($_.Name)  ($Size)"
}
Write-Host ""
Write-Host "Ready. Launch with:"
Write-Host "  .\src\audiagentic\provisioning\rig\embedded\scripts\start-rig.ps1"
