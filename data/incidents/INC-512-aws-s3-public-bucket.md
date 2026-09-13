# Incident #512: AWS S3 Public Read ACL Exposure

- **Incident ID:** INC-512
- **Severity:** P0 (Security & Data Governance Breach)
- **Date:** 2025-04-11
- **Author:** SecOps & Compliance
- **Status:** Resolved & Post-Mortem Approved

---

## 1. Executive Summary
A contractor debugging image loading issues for a frontend web app executed `aws s3api put-bucket-acl --bucket company-client-data --acl public-read`. Because bucket public access block was temporarily disabled for cross-account testing, the entire client data bucket—containing HIPAA and SOC2 sensitive files—was rendered publicly readable to the open internet for 37 minutes until automated AWS Config remediation triggered.

## 2. Triggering Command Pattern
```bash
aws s3api put-bucket-acl --bucket company-client-data --acl public-read
aws s3 rm s3://company-prod-backups --recursive
aws s3 sync . s3://company-prod-assets --delete
```

## 3. Root Cause
* Running high-privilege `s3api` ACL mutations directly against production buckets without IAM policy dry-run.

## 4. Mandatory Safe Alternative
Use CloudFront signed URLs or generate pre-signed S3 URLs with expiration:
```bash
aws s3 presign s3://company-client-data/sample.pdf --expires-in 300
```

## 5. ShellGuard Interception Rule
* **Keywords:** `aws s3api put-bucket-acl --acl public-read`, `aws s3 rm --recursive`, `aws s3 sync --delete`
* **Action:** HARD_BLOCK
* **Recommendation:** Public bucket ACLs are strictly prohibited by company security baseline SEC-004.
