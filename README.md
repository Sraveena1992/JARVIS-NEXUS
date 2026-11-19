# JARVIS NEXUS GLOBAL v1 — Render private beta

Original v4.5 holographic interface retained; Anna app remains a **separate** release. This package is an independent FastAPI web application.

## Deployment to Render
1. Create a **private GitHub repository** and upload these files at its root. Never upload `.env`, `.db`, tokens, or local workspaces.
2. Render Dashboard → **New → Blueprint** → connect the repository and select `render.yaml`.
3. Choose a **paid instance supporting persistent disks** (starter in the provided blueprint; verify current Render plan availability/pricing). Do not use an ephemeral filesystem for persistent tasks.
4. In Render environment settings, set `JARVIS_TOKEN` to a cryptographically random string of at least 32 characters and `OPENAI_API_KEY` to your API key. Never put secrets in GitHub or frontend code.
5. Deploy and check `/api/health`. Visit the site and click **Set access token**, paste the private token, then try `calculate 2+2`, `add task Test JARVIS`, and an AI question.
6. **Do not distribute the access token publicly.** This is a single-admin private beta, not multi-user SaaS. Public sharing of the website URL is safe only as a locked demo; authenticated features require a private token.

## Security boundaries
- No arbitrary file read/write, desktop app launch, shell access, or YouTube server-side lookup in the cloud build.
- No public sign-up, per-user accounts, email verification, billing, or tenant isolation yet. **Do not issue the shared admin token to worldwide users.**
- Chat and tasks use one SQLite database and are **not multi-tenant**. The persistent disk is single-instance oriented. Backups and retention policy must be established before production use.
- Rate limiting is process-local, not distributed. Add reverse-proxy rate limits and per-user auth before public access.
- AI calls require a valid server-side OpenAI API key and incur usage costs. Health reports configuration, not provider uptime.
- Browser voice recognition requires browser support and microphone permissions. Voice transcription may use browser-vendor services.
- Reminders are polled while the page is open, not push notifications.
- PWA installation depends on browser/device; no service worker/offline mode in v1.
- Mobile responsive CSS included, but device testing is required. Android Play Store build not included.

## Local smoke test
```
python -m pip install -r requirements.txt
# Windows PowerShell:
$env:JARVIS_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

## Rollout gate
Before public launch: implement individual accounts and sessions, CSRF protections, data isolation, distributed rate limiting, moderation/abuse protection, provider spending caps, privacy policy and terms, logging without sensitive prompts, backup/restore and security review.
