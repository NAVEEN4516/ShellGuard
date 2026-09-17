#!/usr/bin/env bash
# ShellGuard Bash Hook
# Zero-Latency Terminal Interceptor powered by Moss
# Source this file in your ~/.bashrc: source /path/to/shellguard.bash

SHELLGUARD_DAEMON_URL="${SHELLGUARD_DAEMON_URL:-http://127.0.0.1:8080/api/check}"
SHELLGUARD_TIMEOUT="${SHELLGUARD_TIMEOUT:-0.25}"

# Fast dangerous prefix filter (handles optional sudo / env wrappers)
SHELLGUARD_DANGER_REGEX="(^|[[:space:]])(sudo[[:space:]]+)?(kubectl|terraform|docker|aws|gcloud|az|rm|git|helm|drop|truncate|delete|redis-cli|vault)"

shellguard_preexec() {
    # Recursion guard to prevent nested trap execution
    if [[ "${SHELLGUARD_RUNNING:-0}" == "1" ]]; then
        return 0
    fi

    # Ignore execution inside subshells ($(cmd) or (cmd))
    if [[ "${BASH_SUBSHELL:-0}" -gt 0 ]]; then
        return 0
    fi

    # Only inspect top-level interactive commands (not internal functions)
    if [[ "${#FUNCNAME[@]}" -gt 1 ]]; then
        return 0
    fi

    local cmd="$BASH_COMMAND"

    # Fast regex filter - bypass non-destructive commands in < 0.05ms
    if [[ ! "$cmd" =~ $SHELLGUARD_DANGER_REGEX ]]; then
        return 0
    fi

    SHELLGUARD_RUNNING=1

    # Native Bash JSON escaping (zero python subprocess forks)
    local escaped_cmd="${cmd//\\/\\\\}"
    escaped_cmd="${escaped_cmd//\"/\\\"}"
    escaped_cmd="${escaped_cmd//$'\n'/\\n}"
    escaped_cmd="${escaped_cmd//$'\r'/\\r}"
    escaped_cmd="${escaped_cmd//$'\t'/\\t}"
    local json_payload="{\"command\":\"${escaped_cmd}\",\"cwd\":\"${PWD}\",\"shell\":\"bash\"}"

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

    SHELLGUARD_RUNNING=0

    if [[ -z "$response" ]]; then
        if [[ "${SHELLGUARD_FAIL_POLICY,,}" == "fail_closed" ]]; then
            echo -e "\n\033[1;41;37m[SHELLGUARD SECURITY ALERT] EXECUTION BLOCKED (FAIL-CLOSED)\033[0m" >&2
            echo -e "\033[1;33mThe ShellGuard daemon is unreachable. High-security enterprise policy 'fail_closed' is active.\033[0m" >&2
            echo -e "\033[1;37mPotentially destructive command halted to prevent unmonitored execution.\033[0m" >&2
            echo -e "\033[0;90mTo bypass on local dev, export SHELLGUARD_FAIL_POLICY=fail_open\033[0m\n" >&2
            return 1
        fi
        return 0
    fi

    # Native Bash regex parsing (zero grep/cut pipelines)
    local status="" latency="" incident_id="" safe_cmd="" env_badge=""
    if [[ "$response" =~ \"status\":[[:space:]]*\"([^\"]*)\" ]]; then
        status="${BASH_REMATCH[1]}"
    fi
    if [[ "$response" =~ \"latency_ms\":[[:space:]]*([0-9.]+) ]]; then
        latency="${BASH_REMATCH[1]}"
    fi
    if [[ "$response" =~ \"matched_incident_id\":[[:space:]]*\"([^\"]*)\" ]]; then
        incident_id="${BASH_REMATCH[1]}"
    fi
    if [[ "$response" =~ \"safe_alternative_cmd\":[[:space:]]*\"([^\"]*)\" ]]; then
        safe_cmd="${BASH_REMATCH[1]}"
    fi
    if [[ "$response" =~ \"env_badge\":[[:space:]]*\"([^\"]*)\" ]]; then
        env_badge="${BASH_REMATCH[1]}"
    fi

    if [[ "$status" == "BLOCKED" ]]; then
        echo -e "\n\e[1;41;37m 🛑 [SHELLGUARD BLOCKED] EXECUTION HALTED \e[0m"
        if [[ -n "$env_badge" ]]; then
            echo -e "\e[1;35mEnvironment:\e[0m $env_badge"
        fi
        echo -e "\e[1;31mMatched Incident:\e[0m $incident_id (Retrieved in ${latency}ms via Moss)"
        if [[ -n "$safe_cmd" ]]; then
            echo -e "\e[1;32mMandatory Safe Alternative:\e[0m $safe_cmd"
        fi
        echo -e "\e[0;90mThis command was blocked to prevent critical production downtime.\e[0m\n"
        # When shopt -s extdebug is active, returning non-zero from DEBUG trap halts execution
        return 1
    elif [[ "$status" == "WARNING" ]]; then
        local env_prefix=""
        if [[ -n "$env_badge" ]]; then
            env_prefix=" $env_badge"
        fi
        echo -e "\e[1;33m⚠️  [SHELLGUARD WARNING]${env_prefix} (${latency}ms)\e[0m"
    fi

    return 0
}

# Required in Bash so that returning 1 from DEBUG trap aborts command execution
shopt -s extdebug
set -o functrace
trap 'shellguard_preexec' DEBUG
