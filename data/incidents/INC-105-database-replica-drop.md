# Incident #105: Terraform Primary Database Deletion

- **Incident ID:** INC-105
- **Severity:** P0 (Catastrophic Data Availability Failure)
- **Date:** 2025-08-02
- **Author:** Platform Infrastructure & Data Engineering
- **Status:** Resolved & Post-Mortem Approved

---

## 1. Executive Summary
During a routine cleanup of unused staging resources, an engineer ran `terraform destroy -target=aws_db_instance.primary` while pointed to the production workspace (`production-useast1`). The RDS Aurora Postgres primary database instance was immediately scheduled for deletion. Despite multi-AZ redundancy, the direct destroy signal triggered immediate storage detachment, dropping 14,000 active database client connections and causing global transaction failures for 1 hour and 45 minutes.

## 2. Triggering Command Pattern
```bash
terraform destroy -target=aws_db_instance.primary
terraform apply -destroy -auto-approve
terraform state rm aws_db_instance.primary
```

## 3. Root Cause
1. Missing workspace validation: The Terraform CLI session was in `production` workspace instead of `staging`.
2. `-auto-approve` / forced execution without manual impact verification.
3. No pre-execution terminal interceptor to calculate resource blast radius before the Terraform plan was accepted.

## 4. Blast Radius
* **Affected Services:** Core billing, auth tokens, checkout services.
* **Data Loss:** Restored to Point-In-Time recovery (5-minute transaction delta).
* **Financial Impact:** $185,000 in lost transaction volume.

## 5. Mandatory Safe Alternative
Never destroy stateful production database resources directly via Terraform CLI:
1. Always verify active workspace:
```bash
terraform workspace show
```
2. Enable deletion protection in Terraform HCL:
```hcl
deletion_protection = true
```
3. To safely scale or modify:
```bash
terraform plan -out=tfplan.binary
```

## 6. ShellGuard Interception Rule
* **Keywords:** `terraform destroy`, `terraform apply -destroy`, `terraform state rm aws_db`
* **Action:** HARD_BLOCK
* **Recommendation:** Verify workspace with `terraform workspace show` and ensure `-target` does not match stateful resources.
