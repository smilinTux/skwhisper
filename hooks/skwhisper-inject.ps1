# SKWhisper Context Injection Hook for Claude Code (Windows)
# Injects whisper.md subconscious context on SessionStart.
#
# Hook type: SessionStart (startup, compact, resume)
# Input (stdin): JSON with session_id, source
# Output (stdout): Injected into Claude's context
# Exit 0 always

$ErrorActionPreference = "SilentlyContinue"

$Agent = @($env:SKAGENT, $env:SKCAPSTONE_AGENT, $env:SKMEMORY_AGENT, "lumina") | Where-Object { $_ } | Select-Object -First 1
$SkWhisperExe = (Get-Command skwhisper -ErrorAction SilentlyContinue).Source
$WhisperFile = Join-Path $env:USERPROFILE ".skcapstone" "agents" $Agent "skwhisper" "whisper.md"

# Search for skwhisper project
$SkWhisperDir = $null
$SearchPaths = @(
    (Join-Path $env:USERPROFILE "clawd" "projects" "skwhisper"),
    (Join-Path $env:USERPROFILE "projects" "skwhisper"),
    (Join-Path $env:USERPROFILE "skwhisper")
)
foreach ($D in $SearchPaths) {
    if (Test-Path (Join-Path $D "skwhisper" "__main__.py")) {
        $SkWhisperDir = $D
        break
    }
}

# Refresh if stale (>2h)
if ((Test-Path $WhisperFile) -and $SkWhisperExe) {
    $FileAge = (New-TimeSpan -Start (Get-Item $WhisperFile).LastWriteTime -End (Get-Date)).TotalSeconds
    if ($FileAge -gt 7200) { Start-Process -WindowStyle Hidden -FilePath $SkWhisperExe -ArgumentList "curate" }
} elseif ((Test-Path $WhisperFile) -and $SkWhisperDir) {
    $FileAge = (New-TimeSpan -Start (Get-Item $WhisperFile).LastWriteTime -End (Get-Date)).TotalSeconds
    if ($FileAge -gt 7200) {
        Start-Process -NoNewWindow -FilePath "python" -ArgumentList "-m", "skwhisper", "curate" -WorkingDirectory $SkWhisperDir -RedirectStandardOutput "NUL" -RedirectStandardError "NUL"
    }
}

# Output whisper context
if ((Test-Path $WhisperFile) -and ((Get-Item $WhisperFile).Length -gt 0)) {
    Write-Output "--- SKWHISPER SUBCONSCIOUS CONTEXT ---"
    Write-Output "Agent: $Agent"
    Write-Output "Source: $WhisperFile"
    $LastWrite = (Get-Item $WhisperFile).LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
    Write-Output "Updated: $LastWrite"
    Write-Output ""
    Get-Content $WhisperFile
    Write-Output ""
    Write-Output "--- END SKWHISPER ---"
} else {
    Write-Output "--- SKWHISPER: No whisper.md available for agent $Agent ---"
}

exit 0
