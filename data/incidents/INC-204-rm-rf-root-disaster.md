# Incident #204: Accidental Root Filesystem Wipe via Unset Variable

- **Incident ID:** INC-204
- **Severity:** P0 (Total Node Destruction)
- **Date:** 2025-01-28
- **Author:** Linux Systems Engineering
- **Status:** Resolved & Post-Mortem Approved

---

## 1. Executive Summary
During a maintenance script run, an engineer executed `rm -rf $TARGET_DIR/*` in a shell session where `$TARGET_DIR` was empty/unset. The shell evaluated the command as `rm -rf /*`, unlinking root system libraries (`/bin`, `/lib`, `/usr`) on a bare-metal Kubernetes worker before the command crashed with broken dynamic linker errors.

## 2. Triggering Command Pattern
```bash
rm -rf /*
rm -rf /
rm -rf --no-preserve-root /
rm -rf /var /
```

## 3. Root Cause
* Using unquoted, unverified shell variables in `rm -rf`.
* Lack of safe deletion alias or pre-flight parser.

## 4. Mandatory Safe Alternative
Always use `set -u` in bash scripts to fail on unset variables, or use `trash-cli` / move to tmp:
```bash
mv target_directory /tmp/trash_staging
```

## 5. ShellGuard Interception Rule
* **Keywords:** `rm -rf /`, `rm -rf /*`, `rm -rf --no-preserve-root`
* **Action:** HARD_BLOCK (Immediate Execution Abort)
