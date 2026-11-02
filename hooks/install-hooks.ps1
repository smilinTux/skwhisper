# Install SKWhisper hooks into Claude Code settings.json (Windows)
# Run from PowerShell: .\install-hooks.ps1

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ClaudeSettings = Join-Path $env:USERPROFILE ".claude" "settings.json"

Write-Host "═══ SKWhisper Hook Installer (Windows) ═══" -ForegroundColor Cyan
Write-Host ""

# Verify Claude Code settings exist
if (-not (Test-Path $ClaudeSettings)) {
    Write-Host "✗ Claude Code settings not found at $ClaudeSettings" -ForegroundColor Red
    Write-Host "  Run 'claude' at least once first."
    exit 1
}

# Backup
$BackupPath = "${ClaudeSettings}.bak.$(Get-Date -Format 'yyyyMMddHHmm')"
Copy-Item $ClaudeSettings $BackupPath
Write-Host "✓ Backed up current settings" -ForegroundColor Green

# Hook paths — use PowerShell scripts on Windows
$InjectHook = Join-Path $ScriptDir "skwhisper-inject.ps1"
$SaveHook = Join-Path $ScriptDir "skwhisper-save.ps1"

# Verify hooks exist
if (-not (Test-Path $InjectHook)) { Write-Host "✗ $InjectHook not found" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $SaveHook)) { Write-Host "✗ $SaveHook not found" -ForegroundColor Red; exit 1 }

# On Windows, wrap PowerShell scripts in a command Claude Code can execute
$InjectCmd = "powershell -ExecutionPolicy Bypass -NoProfile -File `"$InjectHook`""
$SaveCmd = "powershell -ExecutionPolicy Bypass -NoProfile -File `"$SaveHook`""

$Settings = Get-Content $ClaudeSettings -Raw | ConvertFrom-Json

# Ensure hooks object exists
if (-not $Settings.hooks) {
    $Settings | Add-Member -MemberType NoteProperty -Name "hooks" -Value ([PSCustomObject]@{})
}

function Add-HookEntry {
    param($HookType, $Command, $Timeout, $Matcher)

    if (-not $Settings.hooks.$HookType) {
        $Settings.hooks | Add-Member -MemberType NoteProperty -Name $HookType -Value @()
    }

    # Check if already installed (look for "skwhisper" in command)
    $Existing = $Settings.hooks.$HookType | Where-Object {
        $_.hooks | Where-Object { $_.command -like "*skwhisper*" }
    }

    if ($Existing) {
        Write-Host "→ SKWhisper already in $HookType (skipped)" -ForegroundColor Yellow
        return
    }

    $Entry = [PSCustomObject]@{
        matcher = $Matcher
        hooks = @(
            [PSCustomObject]@{
                type = "command"
                command = $Command
                timeout = $Timeout
            }
        )
    }

    $Settings.hooks.$HookType = @($Settings.hooks.$HookType) + @($Entry)
    Write-Host "✓ Added SKWhisper hook to $HookType" -ForegroundColor Green
}

# skmemory's budgeted ritual already injects a distilled whisper.md; only add
# skwhisper's own inject hook when asked (standalone skwhisper, no skmemory).
Add-HookEntry -HookType "SessionEnd"   -Command $SaveCmd   -Timeout 30 -Matcher ""
if ($args -contains "-WithInject") {
    Add-HookEntry -HookType "SessionStart" -Command $InjectCmd -Timeout 15 -Matcher ""
}

# Save
$Settings | ConvertTo-Json -Depth 10 | Set-Content $ClaudeSettings -Encoding UTF8
Write-Host "✓ Settings saved" -ForegroundColor Green

Write-Host ""
Write-Host "═══ Installation Complete ═══" -ForegroundColor Cyan
Write-Host ""
Write-Host "SKWhisper will now inject subconscious context into every Claude Code session."
Write-Host "Test: claude --print 'What does your SKWhisper subconscious say?'"
