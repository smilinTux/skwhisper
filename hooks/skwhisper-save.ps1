# SKWhisper Session Save Hook for Claude Code (Windows)
# Triggers SKWhisper digest after session ends.
#
# Hook type: SessionEnd
# Input (stdin): JSON with session_id, reason
# Exit 0 always

$ErrorActionPreference = "SilentlyContinue"

$Agent = @($env:SKAGENT, $env:SKCAPSTONE_AGENT, $env:SKMEMORY_AGENT, "lumina") | Where-Object { $_ } | Select-Object -First 1
$SkWhisperExe = (Get-Command skwhisper -ErrorAction SilentlyContinue).Source

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

if ($SkWhisperExe) {
    Start-Process -WindowStyle Hidden -FilePath $SkWhisperExe -ArgumentList "digest"
    Start-Process -WindowStyle Hidden -FilePath $SkWhisperExe -ArgumentList "curate"
    exit 0
}
if (-not $SkWhisperDir) { exit 0 }

# Run digest + curate in background
$env:PYTHONPATH = $SkWhisperDir
Start-Process -NoNewWindow -FilePath "python" -ArgumentList "-m", "skwhisper", "digest" -WorkingDirectory $SkWhisperDir -RedirectStandardOutput "NUL" -RedirectStandardError "NUL"
Start-Process -NoNewWindow -FilePath "python" -ArgumentList "-m", "skwhisper", "curate" -WorkingDirectory $SkWhisperDir -RedirectStandardOutput "NUL" -RedirectStandardError "NUL"

exit 0
