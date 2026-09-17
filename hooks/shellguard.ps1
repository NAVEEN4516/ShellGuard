# ShellGuard Windows PowerShell Hook
# Zero-Latency Terminal Interceptor powered by Moss
# Usage: . .\hooks\shellguard.ps1

if (-not $Global:ShellGuardDaemonUrl) {
    $Global:ShellGuardDaemonUrl = if ($env:SHELLGUARD_DAEMON_URL) { $env:SHELLGUARD_DAEMON_URL } else { "http://127.0.0.1:8080/api/check" }
}

function Test-ShellGuardCommand {
    param([string]$Command)

    if ([string]::IsNullOrWhiteSpace($Command)) {
        return $true
    }

    $cleanCmd = $Command.Trim()
    
    # Fast bypass for non-infrastructure commands (< 0.05ms)
    $dangerRegex = "(^|[;\s])(sudo\s+)?(kubectl|terraform|docker|aws|gcloud|az|rm|git|helm|drop|truncate|delete|redis-cli|vault)"
    if ($cleanCmd -notmatch $dangerRegex) {
        return $true
    }

    try {
        $currDir = (Get-Location).Path
        $body = @{ command = $cleanCmd; cwd = $currDir; shell = "powershell" } | ConvertTo-Json -Compress
        
        # Resolve auth token: Environment variable -> Windows DPAPI secure store -> Legacy fallback
        $token = if ($env:SHELLGUARD_TOKEN) { $env:SHELLGUARD_TOKEN } else { "" }
        if (-not $token) {
            $dpapiFile = Join-Path $HOME ".shellguard\token.dpapi"
            if (Test-Path $dpapiFile) {
                try {
                    Add-Type -AssemblyName System.Security -ErrorAction SilentlyContinue
                    $encBytes = [System.IO.File]::ReadAllBytes($dpapiFile)
                    $plainBytes = [System.Security.Cryptography.ProtectedData]::Unprotect($encBytes, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
                    $token = [System.Text.Encoding]::UTF8.GetString($plainBytes).Trim()
                } catch {
                    $token = ""
                }
            }
            if (-not $token) {
                $tokenFile = Join-Path $HOME ".shellguard\token"
                if (Test-Path $tokenFile) {
                    $token = (Get-Content $tokenFile -Raw).Trim()
                }
            }
        }

        $headers = @{}
        if ($token) { $headers["X-ShellGuard-Token"] = $token }
        $response = Invoke-RestMethod -Uri $Global:ShellGuardDaemonUrl -Method Post -Body $body -Headers $headers -ContentType "application/json; charset=utf-8" -TimeoutSec 1

        if ($response.status -eq "BLOCKED") {
            Write-Host ""
            Write-Host "[SHELLGUARD BLOCKED] EXECUTION HALTED" -ForegroundColor Red -BackgroundColor Black
            if ($response.env_badge) {
                Write-Host ("Environment:       " + $response.env_badge) -ForegroundColor Magenta
            }
            Write-Host ("Matched Incident:  " + $response.matched_incident_id + " - " + $response.matched_incident_title) -ForegroundColor Yellow
            Write-Host ("Retrieval Latency: " + $response.latency_ms + "ms (Moss In-Process Runtime)") -ForegroundColor Cyan
            Write-Host ("Recommendation:    " + $response.recommendation) -ForegroundColor White
            $safeAlt = if ($response.safe_alternative_cmd) { $response.safe_alternative_cmd } else { $response.safe_alternative }
            if ($safeAlt) {
                Write-Host ("Safe Alternative:  " + $safeAlt) -ForegroundColor Green
            }
            Write-Host "`nExecution prevented. To bypass, run without ShellGuard.`n" -ForegroundColor DarkGray
            return $false
        }
        elseif ($response.status -eq "WARNING") {
            $envText = if ($response.env_badge) { " " + $response.env_badge } else { "" }
            Write-Host ("[SHELLGUARD WARNING]" + $envText + " (" + $response.latency_ms + "ms): " + $response.recommendation) -ForegroundColor Yellow
            return $true
        }
        else {
            return $true
        }
    }
    catch {
        # Configurable fail policy (fail_open for dev workstations, fail_closed for enterprise zero-trust)
        $policy = if ($env:SHELLGUARD_FAIL_POLICY) { $env:SHELLGUARD_FAIL_POLICY.ToLower() } else { "fail_open" }
        if ($policy -eq "fail_closed") {
            Write-Host ""
            Write-Host "[SHELLGUARD SECURITY ALERT] EXECUTION BLOCKED (FAIL-CLOSED)" -ForegroundColor Red -BackgroundColor Black
            Write-Host "The ShellGuard daemon is unreachable. High-security enterprise policy 'fail_closed' is active." -ForegroundColor Yellow
            Write-Host "Potentially destructive command halted to prevent unmonitored execution." -ForegroundColor White
            Write-Host "To bypass on local dev, set: `$env:SHELLGUARD_FAIL_POLICY='fail_open'`n" -ForegroundColor DarkGray
            return $false
        } else {
            # Fail open safely with optional debug notice
            if ($env:SHELLGUARD_DEBUG -eq "1") {
                Write-Host "[SHELLGUARD AUDIT] Daemon unreachable, fail-open active." -ForegroundColor DarkGray
            }
            return $true
        }
    }
}

# KeyHandler for transparent Enter key interception via PSReadLine (zero Invoke-Expression risks)
if (Get-Module -ListAvailable -Name PSReadLine) {
    Import-Module PSReadLine -ErrorAction SilentlyContinue
    Set-PSReadLineKeyHandler -Chord 'Enter' -ScriptBlock {
        $line = ""
        $cursor = 0
        [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$line, [ref]$cursor)
        
        if ([string]::IsNullOrWhiteSpace($line)) {
            [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
            return
        }

        $isAllowed = Test-ShellGuardCommand -Command $line
        if ($isAllowed) {
            [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
        } else {
            # Execution halted: keep command in buffer so engineer can inspect or modify
        }
    }
}

# Backward-compatible 'sg' proxy function without Invoke-Expression risk
function sg {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CmdArgs)
    if ($CmdArgs.Count -eq 0) { return }
    $fullCmd = $CmdArgs -join ' '
    $isAllowed = Test-ShellGuardCommand -Command $fullCmd
    if ($isAllowed) {
        if ($CmdArgs.Count -eq 1) {
            & $CmdArgs[0]
        } else {
            & $CmdArgs[0] $CmdArgs[1..($CmdArgs.Length - 1)]
        }
    }
}

Write-Host "ShellGuard PowerShell Interceptor Loaded!" -ForegroundColor Cyan
Write-Host "   KeyHandler: Enter key transparent interception active (PSReadLine)" -ForegroundColor DarkGray
Write-Host ("   Daemon target: " + $Global:ShellGuardDaemonUrl) -ForegroundColor DarkGray
