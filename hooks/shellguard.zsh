#!/usr/bin/env zsh
# ShellGuard Zsh Hook
# Zero-Latency Terminal Interceptor powered by Moss
# Source this file in your ~/.zshrc: source /path/to/shellguard.zsh

SHELLGUARD_DAEMON_URL="${SHELLGUARD_DAEMON_URL:-http://127.0.0.1:8080/api/check}"
SHELLGUARD_TIMEOUT="${SHELLGUARD_TIMEOUT:-0.25}" # 250ms max timeout fallback so terminal never hangs if daemon is offline

# Fast dangerous prefix filter (handles optional sudo / env wrappers)
SHELLGUARD_DANGER_REGEX="(^|[[:space:]])(sudo[[:space:]]+)?(kubectl|terraform|docker|aws|gcloud|az|rm|git|helm|drop|truncate|delete|redis-cli|vault)"

shellguard_preexec() {
    local cmd="$1"
    
    # 1. Quick regex filter - bypass non-destructive commands in < 0.05ms
    if [[ ! "$cmd" =~ $SHELLGUARD_DANGER_REGEX ]]; then
        return 0
    fi

    # 2. Native Zsh JSON escaping (zero python subprocess forks)
    local escaped_cmd="${cmd//\\/\\\\}"
    escaped_cmd="${escaped_cmd//\"/\\\"}"
    escaped_cmd="${escaped_cmd//$'\n'/\\n}"
    escaped_cmd="${escaped_cmd//$'\r'/\\r}"
    escaped_cmd="${escaped_cmd//$'\t'/\\t}"
    local json_payload="{\"command\":\"${escaped_cmd}\",\"cwd\":\"${PWD}\",\"shell\":\"zsh\"}"
    
    # 3. Sub-10ms call to local in-process Moss daemon
    local auth_header=""
    local token="${SHELLGUARD_TOKEN:-}"
    if [[ -z "$token" && -f "$HOME/.shellguard/token" ]]; then
        token=$(cat "$HOME/.shellguard/token" 2>/dev/null | tr -d '[:space:]')
    fi
    if [[ -n "$token" ]]; then
        auth_header="-H X-ShellGuard-Token:$token"
    fi

    local response
    response=$(curl -s --max-time "$SHELLGUARD_TIMEOUT" -X POST "$SHELLGUARD_DAEMON_URL" \
        -H "Content-Type: application/json" \
        $auth_header \
        -d "$json_payload" 2>/dev/null)

    if [[ -z "$response" ]]; then
        if [[ "${(L)SHELLGUARD_FAIL_POLICY}" == "fail_closed" ]]; then
            echo -e "\n\033[1;41;37m[SHELLGUARD SECURITY ALERT] EXECUTION BLOCKED (FAIL-CLOSED)\033[0m" >&2
            echo -e "\033[1;33mThe ShellGuard daemon is unreachable. High-security enterprise policy 'fail_closed' is active.\033[0m" >&2
            echo -e "\033[1;37mPotentially destructive command halted to prevent unmonitored execution.\033[0m" >&2
            echo -e "\033[0;90mTo bypass on local dev, export SHELLGUARD_FAIL_POLICY=fail_open\033[0m\n" >&2
            return 1
        fi
        # Daemon offline - fail open safely
        return 0
    fi

    # 4. Native Zsh regex parsing via pattern variables (zero grep/cut subprocess forks)
    local status="" latency="" incident_id="" title="" rec="" safe_cmd="" env_badge=""
    local re_status='"status"[[:space:]]*:[[:space:]]*"([^"]*)"'
    local re_latency='"latency_ms"[[:space:]]*:[[:space:]]*([0-9.]+)'
    local re_incident_id='"matched_incident_id"[[:space:]]*:[[:space:]]*"([^"]*)"'
    local re_title='"matched_incident_title"[[:space:]]*:[[:space:]]*"([^"]*)"'
    local re_rec='"recommendation"[[:space:]]*:[[:space:]]*"([^"]*)"'
    local re_safe_cmd='"safe_alternative_cmd"[[:space:]]*:[[:space:]]*"([^"]*)"'
    local re_env_badge='"env_badge"[[:space:]]*:[[:space:]]*"([^"]*)"'

    if [[ "$response" =~ $re_status ]]; then
        status="${match[1]:-${BASH_REMATCH[1]}}"
    fi
    if [[ "$response" =~ $re_latency ]]; then
        latency="${match[1]:-${BASH_REMATCH[1]}}"
    fi
    if [[ "$response" =~ $re_incident_id ]]; then
        incident_id="${match[1]:-${BASH_REMATCH[1]}}"
    fi
    if [[ "$response" =~ $re_title ]]; then
        title="${match[1]:-${BASH_REMATCH[1]}}"
    fi
    if [[ "$response" =~ $re_rec ]]; then
        rec="${match[1]:-${BASH_REMATCH[1]}}"
    fi
    if [[ "$response" =~ $re_safe_cmd ]]; then
        safe_cmd="${match[1]:-${BASH_REMATCH[1]}}"
    fi
    if [[ "$response" =~ $re_env_badge ]]; then
        env_badge="${match[1]:-${BASH_REMATCH[1]}}"
    fi

    if [[ "$status" == "BLOCKED" ]]; then
        echo ""
        echo "\033[1;41;37m 🛑 [SHELLGUARD BLOCKED] EXECUTION HALTED \033[0m"
        if [[ -n "$env_badge" ]]; then
            echo "\033[1;35mEnvironment:\033[0m $env_badge"
        fi
        echo "\033[1;31mIncident Match:\033[0m $incident_id — $title"
        echo "\033[1;33mLatency:\033[0m ${latency}ms (Moss In-Process Runtime)"
        echo "\033[1;36mRecommendation:\033[0m $rec"
        if [[ -n "$safe_cmd" ]]; then
            echo "\033[1;32mSafe Alternative:\033[0m $safe_cmd"
        fi
        echo "\033[0;90mTo override in an extreme emergency, run: \033[1;37mFORCE=1 $cmd\033[0m"
        echo ""
        # Abort execution in Zsh by killing the subshell
        kill -s INT $$
        return 1
    elif [[ "$status" == "WARNING" ]]; then
        local env_prefix=""
        if [[ -n "$env_badge" ]]; then
            env_prefix=" $env_badge"
        fi
        echo "\033[1;33m⚠️  [SHELLGUARD WARNING]${env_prefix} (${latency}ms):\033[0m $rec"
    fi

    return 0
}

# Attach to zsh preexec hook
autoload -Uz add-zsh-hook
add-zsh-hook preexec shellguard_preexec
