# Security and privacy notes

This repository is a hackathon demo, not a production review service.

## Do not upload

- unpublished commercial scripts;
- names, phone numbers, account identifiers or contracts;
- API keys, passwords or access tokens;
- video or audio containing people without appropriate permission.

## Storage boundary

The demo stores script versions, feedback rules and validation records in the deployment instance's SQLite database. It does not provide authentication, durable cloud storage, encryption-at-rest management or per-user accounts.

Each browser session receives a random project code and reset operations are project-scoped. This reduces accidental interference but is not an authorization mechanism. Use only anonymized test material.

## Secrets

Local environment files, Streamlit secrets, private keys, SQLite files, logs and common media formats are excluded by `.gitignore`. Never commit real credentials. If a credential is committed accidentally, revoke it before removing it from Git history.
