# ShellGuard Windows PowerShell Hook
# Zero-Latency Terminal Interceptor powered by Moss
# Usage: . .\hooks\shellguard.ps1

$Global:ShellGuardDaemonUrl = "http://127.0.0.1:8080/api/check"

function Test-ShellGuardCommand {
    param([string]$Command)

    if ([string]::IsNullOrWhiteSpace($Command)) {
        return $true
    }

    $cleanCmd = $Command.Trim()
    
    # Fast bypass for non-destructive operations
    if ($cleanCmd -match "^(ls|dir|cd|pwd|echo|cat|Get-|git status|cls|clear)") {
        return $true
    }

    try {
        $body = @{ command = $cleanCmd; shell = "powershell" } | ConvertTo-Json
        $response = Invoke-RestMethod -Uri $Global:ShellGuardDaemonUrl -Method Post -Body $body -ContentType "application/json" -TimeoutSec 1

        if ($response.status -eq "BLOCKED") {
            Write-Host "`n🛑 [SHELLGUARD BLOCKED] EXECUTION HALTED" -ForegroundColor Red -BackgroundColor Black
            Write-Host "Matched Incident: $($response.matched_incident_id) — $($response.matched_incident_title)" -ForegroundColor Yellow
            Write-Host "Retrieval Latency: $($response.latency_ms)ms (Moss In-Process Runtime)" -ForegroundColor Cyan
            Write-Host "Recommendation:   $($response.recommendation)" -ForegroundColor White
            if ($response.safe_alternative) {
                Write-Host "Safe Alternative: $($response.safe_alternative)" -ForegroundColor Green
            }
            Write-Host "`nExecution prevented. To bypass, run without ShellGuard.`n" -ForegroundColor DarkGray
            return $false
        }
        elseif ($response.status -eq "WARNING") {
            Write-Host "⚠️ [SHELLGUARD WARNING] ($($response.latency_ms)ms): $($response.recommendation)" -ForegroundColor Yellow
            return $true
        }
        else {
            return $true
        }
    }
    catch {
        # Fail open safely if daemon is temporarily offline
        return $true
    }
}

# Provide 'sg' alias to run any command with ShellGuard protection
function sg {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CmdArgs)
    $fullCmd = $CmdArgs -join ' '
    $isAllowed = Test-ShellGuardCommand -Command $fullCmd
    if ($isAllowed) {
        Invoke-Expression $fullCmd
    }
}

Write-Host "⚡ ShellGuard PowerShell Interceptor Loaded!" -ForegroundColor Cyan
Write-Host "   Usage: sg <command> (e.g. sg kubectl delete namespace ingress-nginx)" -ForegroundColor DarkGray
Write-Host "   Daemon target: $Global:ShellGuardDaemonUrl" -ForegroundColor DarkGray
