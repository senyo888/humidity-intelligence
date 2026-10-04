![Humidity Intelligence security policy header](assets/security.png)

# Security Policy

## Responsible disclosure

Please do not open a public GitHub issue for security vulnerabilities or exposed secrets.

If you believe you have found a security issue, check [Senyo's GitHub profile](https://github.com/senyo888) for a private contact route. If none is listed, [open a contact request](https://github.com/senyo888/humidity-intelligence/issues/new) without vulnerability details, affected identities or secrets. Share the report only once a private disclosure channel has been arranged.

## Sensitive information

Do not post sensitive Home Assistant or household information in issues, pull requests, screenshots, logs, YAML examples, or UI Gallery submissions. Sensitive information includes:

- Home Assistant tokens
- API keys
- Internal or external URLs
- Private entity IDs
- Home addresses or location details
- Device IDs and unique hardware identifiers
- Personal names or other personal data

## Secret scanning

Repository secret checks are layered:

- GitHub native secret scanning and push protection should be verified in repository Code security settings.
- Gitleaks is the primary repository scanner. The required CI status is `Gitleaks secret scan`.
- The existing custom secret-pattern scan remains as a secondary Humidity Intelligence-specific guard.

Maintainers can run a local scan before pushing:

```bash
scripts/security/scan_secrets.sh
```

The default local mode scans tracked repository files and avoids ignored local
credential files such as Home Assistant token stores.

Run the full-history scan when changing scanner configuration or before tightening
branch-protection rules:

```bash
scripts/security/scan_secrets.sh full-history
```

Scanner output must stay redacted. If a real secret is found, rotate the credential first. Removing it from git history is cleanup, not sufficient remediation.

## Reporting guidance

When reporting privately, include:

- A short description of the issue
- The affected Humidity Intelligence version
- The affected Home Assistant version, if relevant
- Steps to reproduce, with secrets redacted
- Any logs needed to understand the issue, with sensitive values removed

The maintainer will review the report and coordinate a fix or mitigation where appropriate.
