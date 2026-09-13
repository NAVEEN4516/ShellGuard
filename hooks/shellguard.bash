#!/usr/bin/env bash
# ShellGuard Bash Hook
# Zero-Latency Terminal Interceptor powered by Moss
# Source this file in your ~/.bashrc: source /path/to/shellguard.bash

SHELLGUARD_DAEMON_URL="http://127.0.0.1:8080/api/check"
SHELLGUARD_TIMEOUT=0.25

shellguard_preexec() {
    local cmd="$BASH_COMMAND"

    # Bypass trivial checks
    if [[ "$cmd" =~ ^(ls|cd|pwd|echo|cat|git\ status|shellguard) ]]; then
        return 0
    fi

    # Sub-10ms query to local Moss daemon
    local json_payload=$(python3 -c "import json, sys; print(json.dumps({'command': sys.argv[1], 'shell': 'bash'}))" "$cmd" 2>/dev/null)
    
    if [[ -z "$json_payload" ]]; then
        return 0
    fi

    local response=$(curl -s --max-time $SHELLGUARD_TIMEOUT -X POST "$SHELLGUARD_DAEMON_URL" \
        -H "Content-Type: application/json" \
        -d "$json_payload" 2>/dev/null)

    if [[ -z "$response" ]]; then
        return 0
    fi

    local status=$(echo "$response" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
    local latency=$(echo "$response" | grep -o '"latency_ms":[^,]*' | cut -d':' -f2)
    local incident_id=$(echo "$response" | grep -o '"matched_incident_id":"[^"]*' | cut -d'"' -f4)

    if [[ "$status" == "BLOCKED" ]]; then
        echo -e "\n\e[1;41;37m 🛑 [SHELLGUARD BLOCKED] EXECUTION HALTED \e[0m"
        echo -e "\e[1;31mMatched Incident:\e[0m $incident_id (Retrieved in ${latency}ms via Moss)"
        echo -e "\e[0;90mThis command was blocked to prevent critical production downtime.\e[0m\n"
        return 1
    fi
}

# Hook using trap DEBUG in Bash
set -o functrace
trap 'shellguard_preexec' DEBUG
