#!/usr/bin/env zsh
# ShellGuard Zsh Hook
# Zero-Latency Terminal Interceptor powered by Moss
# Source this file in your ~/.zshrc: source /path/to/shellguard.zsh

SHELLGUARD_DAEMON_URL="http://127.0.0.1:8080/api/check"
SHELLGUARD_TIMEOUT=0.25 # 250ms max timeout fallback so terminal never hangs if daemon is offline

# Dangerous prefix filter to prevent overhead on safe commands
SHELLGUARD_DANGER_REGEX="^(kubectl|terraform|docker|aws|gcloud|rm|git push|helm|drop|truncate)"

shellguard_preexec() {
    local cmd="$1"
    
    # 1. Quick regex filter - bypass non-destructive commands in < 0.1ms
    if [[ ! "$cmd" =~ $SHELLGUARD_DANGER_REGEX ]]; then
        return 0
    fi

    # 2. Sub-10ms call to local in-process Moss daemon
    local json_payload=$(printf '{"command": %s, "shell": "zsh"}' "$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$cmd" 2>/dev/null || printf '"%s"' "$cmd")")
    
    local response=$(curl -s --max-time $SHELLGUARD_TIMEOUT -X POST "$SHELLGUARD_DAEMON_URL" \
        -H "Content-Type: application/json" \
        -d "$json_payload" 2>/dev/null)

    if [[ -z "$response" ]]; then
        # Daemon offline - fail open safely
        return 0
    fi

    # 3. Parse JSON response status
    local status=$(echo "$response" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
    local latency=$(echo "$response" | grep -o '"latency_ms":[^,]*' | cut -d':' -f2)
    local incident_id=$(echo "$response" | grep -o '"matched_incident_id":"[^"]*' | cut -d'"' -f4)
    local title=$(echo "$response" | grep -o '"matched_incident_title":"[^"]*' | cut -d'"' -f4)
    local rec=$(echo "$response" | grep -o '"recommendation":"[^"]*' | cut -d'"' -f4)

    if [[ "$status" == "BLOCKED" ]]; then
        echo ""
        echo "\033[1;41;37m 🛑 [SHELLGUARD BLOCKED] EXECUTION HALTED \033[0m"
        echo "\033[1;31mIncident Match:\033[0m $incident_id — $title"
        echo "\033[1;33mLatency:\033[0m ${latency}ms (Moss In-Process Runtime)"
        echo "\033[1;36mRecommendation:\033[0m $rec"
        echo "\033[0;90mTo override in an extreme emergency, run: \033[1;37mFORCE=1 $cmd\033[0m"
        echo ""
        # Abort execution in Zsh by killing the subshell
        kill -s INT $$
        return 1
    elif [[ "$status" == "WARNING" ]]; then
        echo "\033[1;33m⚠️  [SHELLGUARD WARNING] (${latency}ms):\033[0m $rec"
    fi

    return 0
}

# Attach to zsh preexec hook
autoload -Uz add-zsh-hook
add-zsh-hook preexec shellguard_preexec
