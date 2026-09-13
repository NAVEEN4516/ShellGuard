# Incident #619: Terraform State Resource Removal Outage

- **Incident ID:** INC-619
- **Severity:** P1 (Infrastructure Desynchronization)
- **Date:** 2025-09-05
- **Author:** Cloud Platform Core
- **Status:** Resolved & Post-Mortem Approved

---

## 1. Executive Summary
An engineer troubleshooting state drift executed `terraform state rm module.vpc.aws_nat_gateway.main`. Removing the managed NAT Gateway from the Terraform state without tearing down downstream routes caused Terraform to believe the resource no longer existed. During the next automated apply, Terraform attempted to provision a duplicate NAT Gateway with conflicting CIDRs, triggering VPC route table collisions and isolating private subnet microservices for 52 minutes.

## 2. Triggering Command Pattern
```bash
terraform state rm module.vpc
terraform state rm aws_nat_gateway
terraform state rm aws_internet_gateway
```

## 3. Root Cause
* Modifying core networking state objects without calculating downstream route dependencies.

## 4. Mandatory Safe Alternative
Never remove VPC or routing resources from Terraform state in production. Always refresh state and inspect plans:
```bash
terraform refresh
terraform plan -detailed-exitcode
```

## 5. ShellGuard Interception Rule
* **Keywords:** `terraform state rm module.vpc`, `terraform state rm aws_nat_gateway`
* **Action:** HARD_BLOCK
* **Recommendation:** State deletion on networking modules causes route table collisions.
