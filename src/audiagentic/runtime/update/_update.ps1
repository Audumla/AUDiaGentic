# audiagentic auto-update — do not close
Start-Sleep -Seconds 2
Write-Host ''
Write-Host '  Installing audiagentic {version}...'
& "{python_exe}" -m pip install --no-cache-dir "{wheel}"
if ($LASTEXITCODE -eq 0) {{
    Write-Host ''
    Write-Host '  audiagentic {version} installed. Run audiagentic to start.'
    Remove-Item -Force "{wheel}" -ErrorAction SilentlyContinue
}} else {{
    Write-Host ''
    Write-Host '  Install failed. Run manually:'
    Write-Host "    pip install `"{wheel}`""
}}
Remove-Item -Force $MyInvocation.MyCommand.Path -ErrorAction SilentlyContinue
Write-Host ''
Write-Host '  Press any key to close...'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
