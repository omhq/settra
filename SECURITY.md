# Security policy

Settra touches app credentials, model provider keys, generated SQL, and business data. Please treat security issues carefully.

## Reporting a vulnerability

Please report security issues here https://www.outermeasure.com/contact.

Include as much detail as you can:

- Affected version or commit.
- Deployment mode.
- Reproduction steps.
- Logs or screenshots if safe to share.
- Potential impact.
- Suggested fix if you have one.

## Scope

Relevant security issues may include:

- Credential exposure.
- Unsafe secret storage.
- Authentication or authorization bypass.
- Prompt-to-query behavior that exposes unintended data.
- SQL execution issues.
- Webhook abuse.
- Insecure default deployment settings.
- Container or dependency vulnerabilities.

## Deployment responsibility

Settra is self-hosted. Operators are responsible for securing their own deployment, including:

- Network exposure.
- TLS termination.
- Authentication.
- Model provider selection.
- Secrets management.
- Backups.
- Firewall rules.
- Host updates.
- Access control.

Before using with sensitive production data, review the code, deployment configuration, model provider settings, and connector permissions.

## Recommended production practices

- Use a strong `SECRET_KEY`.
- Prefer read-only app credentials where possible.
- Restrict access to the Settra web UI and API.
- Protect messaging webhooks.
- Use HTTPS.
- Review generated SQL during early usage.
- Keep logs, prompts, and query history private.
- Rotate credentials if a deployment is exposed.
