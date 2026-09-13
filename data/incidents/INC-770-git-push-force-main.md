# Incident #770: Force Push to Protected Main Branch

- **Incident ID:** INC-770
- **Severity:** P1 (Production Code & Release History Wipe)
- **Date:** 2025-07-14
- **Author:** Release Engineering
- **Status:** Resolved & Post-Mortem Approved

---

## 1. Executive Summary
During a botched rebase on a local clone, a release engineer typed `git push --force origin main`. The branch protection rule had been temporarily disabled during a repository migration 20 minutes prior. The force-push overwrote 84 commits on the production release branch, triggering broken CI/CD deployments and deploying un-reviewed experimental code to production containers.

## 2. Triggering Command Pattern
```bash
git push --force origin main
git push -f origin master
git push --force origin release
```

## 3. Root Cause
* Using destructive `--force` flags without lease protection on default branch names.

## 4. Mandatory Safe Alternative
Always use `--force-with-lease` to prevent overwriting commits you have not seen:
```bash
git push --force-with-lease origin feature-branch
```
Never push directly to `main` or `master`. Use pull requests.

## 5. ShellGuard Interception Rule
* **Keywords:** `git push --force origin main`, `git push -f origin master`
* **Action:** HARD_BLOCK
* **Recommendation:** Force-pushing to main wipes production commit history. Use pull requests.
