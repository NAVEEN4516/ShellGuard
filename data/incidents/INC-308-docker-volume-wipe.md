# Incident #308: Production Docker Volume Prune Disaster

- **Incident ID:** INC-308
- **Severity:** P1 (Critical Local Data Wipe)
- **Date:** 2025-06-19
- **Author:** DevOps Core
- **Status:** Resolved & Post-Mortem Approved

---

## 1. Executive Summary
On host `docker-worker-prod-04`, an engineer investigating high disk usage executed `docker system prune -a --volumes -f`. This command wiped not only dangling images and dead containers, but also deleted all anonymous and named local persistent volumes, including local Redis caches and PostgreSQL persistent storage mounts.

## 2. Triggering Command Pattern
```bash
docker system prune -a --volumes
docker volume prune -f
docker volume rm $(docker volume ls -q)
```

## 3. Root Cause
* Combining `-a` (all unused images) with `--volumes` (deletes ALL unattached volumes) without inspecting which volumes were attached to temporarily stopped containers.

## 4. Blast Radius
* **Affected Services:** Worker queue jobs, local cache sessions.
* **Recovery Time:** 90 minutes to restore volume data from remote S3 snapshot.

## 5. Mandatory Safe Alternative
Never use `--volumes` on production worker nodes. Run image pruning safely:
```bash
docker image prune -a --filter "until=168h"
```
Or inspect volumes before deleting:
```bash
docker volume ls
```

## 6. ShellGuard Interception Rule
* **Keywords:** `docker system prune --volumes`, `docker volume prune`, `docker volume rm`
* **Action:** WARNING_PROMPT / BLOCK
* **Recommendation:** Strip `--volumes` flag to prevent wiping persistent disk storage.
