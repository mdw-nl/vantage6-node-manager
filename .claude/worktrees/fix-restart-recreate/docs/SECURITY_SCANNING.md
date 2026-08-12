# Security Scanning

This document explains the security scanning features in the Vantage6 Node Manager CI/CD pipeline.

## Overview

The project uses **Trivy** by Aqua Security to scan for vulnerabilities in:
- Dependencies (Python packages)
- Container images
- Configuration files
- Infrastructure as Code

## How It Works

### Automated Scanning

Security scans run automatically on:
- Every push to `main` or `develop` branches
- Every pull request
- Manual workflow dispatch

### Scan Process

1. **Filesystem Scan**: Trivy scans the entire repository
2. **Severity Filtering**: Focuses on CRITICAL and HIGH vulnerabilities
3. **Dual Output**:
   - **Table format**: Human-readable results in workflow logs
   - **SARIF format**: Machine-readable for GitHub Security tab

### Results Location

#### Workflow Logs (Always Available)
1. Go to **Actions** tab
2. Select a workflow run
3. Click on the `security-scan` job
4. View the Trivy output in the logs

#### GitHub Security Tab (Conditional)
Results appear in the **Security** → **Code scanning** tab if:
- Your repository is **public** (free), OR
- Your repository has **GitHub Advanced Security** enabled (paid feature for private repos)

## GitHub Advanced Security

### What is it?
GitHub Advanced Security (GHAS) is a premium feature that provides:
- Code scanning with CodeQL
- Secret scanning
- Dependency review
- Security overview

### Do I need it?
**For security scanning with Trivy:**
- ✅ **Not required** - Scans run regardless
- ❌ **Optional** - Only needed for SARIF upload to Security tab

**The workflow is designed to work with or without GHAS:**
- With GHAS: Results appear in Security tab + logs
- Without GHAS: Results appear in logs only

### How to enable (for private repos)

1. Repository must be part of an organization with GHAS
2. Go to repository **Settings** → **Code security and analysis**
3. Enable **Code scanning**

Note: This requires a GitHub Enterprise plan or Advanced Security license.

## Interpreting Results

### Severity Levels

- 🔴 **CRITICAL**: Immediate action required
- 🟠 **HIGH**: Should be addressed soon
- 🟡 **MEDIUM**: Should be reviewed
- 🟢 **LOW**: Informational

### Common Findings

1. **Outdated Dependencies**: Update packages in `requirements.txt`
2. **Base Image Vulnerabilities**: Update `Dockerfile` base image
3. **Configuration Issues**: Review security settings

## Taking Action

### If vulnerabilities are found:

1. **Review the findings** in the workflow logs
2. **Check severity** - prioritize CRITICAL and HIGH
3. **Update dependencies**:
   ```bash
   pip install --upgrade package-name
   # Update requirements.txt
   ```
4. **Update base image** in Dockerfile:
   ```dockerfile
   FROM python:3.11-slim  # Use latest stable version
   ```
5. **Commit and push** - triggers new scan
6. **Verify** the issue is resolved

### False Positives

If a finding is a false positive:
1. Document the reason in code comments
2. Consider creating a `.trivyignore` file
3. Use Trivy's ignore syntax:
   ```
   # .trivyignore
   CVE-2023-12345  # False positive: not applicable to our use case
   ```

## Customizing Scans

### Change Severity Threshold

Edit `.github/workflows/docker-test.yml`:

```yaml
- name: Run Trivy vulnerability scanner
  uses: aquasecurity/trivy-action@master
  with:
    severity: 'CRITICAL,HIGH,MEDIUM'  # Add MEDIUM
```

### Scan Docker Images

Add to workflow:

```yaml
- name: Scan Docker image
  uses: aquasecurity/trivy-action@master
  with:
    scan-type: 'image'
    image-ref: 'ghcr.io/mdw-nl/vantage6-node-manager:latest'
```

### Fail on Vulnerabilities

To fail the build if vulnerabilities are found:

```yaml
- name: Run Trivy vulnerability scanner
  uses: aquasecurity/trivy-action@master
  with:
    exit-code: '1'  # Fail on findings
    severity: 'CRITICAL,HIGH'
```

## Best Practices

1. ✅ **Run scans regularly** - automated in CI/CD
2. ✅ **Review all findings** - don't ignore warnings
3. ✅ **Update promptly** - especially CRITICAL issues
4. ✅ **Monitor logs** - even without GHAS
5. ✅ **Keep dependencies current** - use Dependabot
6. ✅ **Use official images** - from trusted sources
7. ✅ **Pin versions** - for reproducibility

## Resources

- [Trivy Documentation](https://aquasecurity.github.io/trivy/)
- [GitHub Advanced Security](https://docs.github.com/en/get-started/learning-about-github/about-github-advanced-security)
- [SARIF Format](https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/sarif-support-for-code-scanning)
- [Trivy Ignore File](https://aquasecurity.github.io/trivy/latest/docs/configuration/filtering/)

## Troubleshooting

### "Advanced Security must be enabled for this repository"

**Cause**: SARIF upload requires GHAS for private repos

**Solution**: This is expected and handled gracefully. The scan still runs and results appear in logs.

**To fix** (optional):
1. Make repository public, OR
2. Enable GitHub Advanced Security (requires license)

### Scan takes too long

**Solution**: The scan is cached. Subsequent runs will be faster.

### Too many findings

**Solution**: 
1. Update to latest versions
2. Use newer base images
3. Review and prioritize by severity

## Support

If you encounter issues:
1. Check workflow logs for detailed error messages
2. Verify Trivy action version is current
3. Review [GitHub Actions status](https://www.githubstatus.com/)
4. Open an issue with logs attached
