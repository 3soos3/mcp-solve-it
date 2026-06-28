# Security Policy

## Project Status

This is an **open-source project maintained on a best-effort basis**.

**Important Limitations:**
- No guaranteed response time for security issues
- No SLA for fixes
- Security patches provided when time permits
- Use at your own risk in production environments

## Reporting a Vulnerability

If you discover a security vulnerability:

### GitHub Security Advisories (Preferred)
1. Go to: https://github.com/3soos3/mcp-solve-it/security/advisories/new
2. Click "Report a vulnerability"
3. Provide details

**OR**

### Public Issue
For non-sensitive issues, you may open a public GitHub issue at
https://github.com/3soos3/mcp-solve-it/issues.

## Response Expectations

- **Acknowledgment**: Best effort, no guaranteed timeline
- **Fixes**: Provided when maintainer availability permits
- **Disclosure**: Public vulnerabilities may be disclosed immediately if no fix is planned

## Security Features

This project includes automated security scanning:

- **Dependency Scanning**: pip-audit via pre-commit / CI
- **Code Security**: Ruff (includes security-oriented rules) + mypy strict mode
- **Container Security**: Alpine-based minimal images, non-root user (uid 1000)
- **Dockerfile Hygiene**: Multi-stage build, no secrets baked in
- **Dependabot**: Automated weekly dependency updates (pip + github-actions)

## Use in Production

**For production or forensic use:**
- Perform your own security audit before deployment
- Review all dependencies (`pip-audit`, `trivy`)
- Consider forking and maintaining your own version
- Verify Docker image provenance before pulling

## Supported Versions

| Version | Status             |
|---------|--------------------|
| 0.1.x   | Best-effort support |
| < 0.1   | No support          |

---

**This project is provided "AS IS" without warranty. See [LICENSE](LICENSE) for details.**
