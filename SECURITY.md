# Security and privacy notes

This repository is a hackathon demo, not a production review service.

## Do not upload

- unpublished commercial scripts;
- names, phone numbers, account identifiers or contracts;
- API keys, passwords or access tokens;
- video or audio containing people without appropriate permission.

## Storage boundary

The demo stores script versions, feedback rules and validation records in the deployment instance's SQLite database. Uploaded video is written to a temporary processing directory and is not stored in the business database; Streamlit may retain upload bytes for the active session. The app does not provide authentication, durable cloud storage, encryption-at-rest management or per-user accounts.

Each browser session receives a random project code and reset operations are project-scoped. This reduces accidental interference but is not an authorization mechanism. Use only anonymized test material.

Audio transcription runs with a locally loaded faster-whisper model. ASR can be wrong, especially with music, accents, noise and overlapping speech. Treat every reported mismatch as a review candidate, not a final factual conclusion.

## Secrets

Local environment files, Streamlit secrets, private keys, SQLite files, logs and common media formats are excluded by `.gitignore`. Never commit real credentials. If a credential is committed accidentally, revoke it before removing it from Git history.
