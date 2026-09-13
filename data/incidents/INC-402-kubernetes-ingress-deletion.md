# Incident #402: Production Ingress Namespace Deletion

- **Incident ID:** INC-402
- **Severity:** P0 (Total Service Outage)
- **Date:** 2025-11-14
- **Author:** Infrastructure Reliability Team
- **Status:** Resolved & Post-Mortem Approved

---

## 1. Executive Summary
At 14:22 UTC, an on-call engineer attempting to clear a stuck staging ingress controller executed `kubectl delete namespace ingress-nginx` without setting the proper kubeconfig context. The command targeted the primary production Kubernetes cluster (`prod-us-east-1`), terminating all ingress controllers, SSL cert-manager pods, and edge load-balancing routing. 100% of public customer traffic returned HTTP 502/503 for 4 hours and 12 minutes.

## 2. Triggering Command Pattern
```bash
kubectl delete namespace ingress-nginx
kubectl delete deployment ingress-nginx-controller -n ingress-nginx
kubectl delete all --all -n ingress-nginx
```

## 3. Root Cause
1. Context confusion: The active terminal session was pointing to `prod-cluster` while the engineer intended to debug `staging-cluster`.
2. Lack of pre-flight interceptor: No verification step intercepted the destructive namespace deletion command before it reached the Kubernetes API server.

## 4. Blast Radius
* **Affected Services:** All 48 microservices routing through edge ingress.
* **Data Loss:** Zero data loss, but 100% external traffic drop.
* **Recovery Time:** 252 minutes (re-provisioning ingress, re-issuing Let's Encrypt certificates).

## 5. Mandatory Safe Alternative
Never delete the ingress namespace or controller directly. If ingress pods are unhealthy or misbehaving, perform a zero-downtime rolling restart:
```bash
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```
If configuration needs re-applying, use:
```bash
kubectl apply -f ingress-config.yaml --dry-run=server
```

## 6. ShellGuard Interception Rule
* **Keywords:** `kubectl delete namespace`, `kubectl delete deployment ingress`, `kubectl delete svc -n ingress-nginx`
* **Action:** HARD_BLOCK
* **Recommendation:** Use `kubectl rollout restart` or check active context with `kubectl config current-context`.
