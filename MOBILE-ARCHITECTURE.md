# JARVIS NEXUS — Android and iOS architecture proposal

Current source is a Windows localhost FastAPI prototype, not a mobile backend.

## Proposed stack
- React Native + Expo, shared Android/iOS screens and push-to-talk UI.
- Secure HTTPS FastAPI gateway with per-user auth, device sessions, rate limiting, audit logs.
- Postgres for user-owned reminders, task sync, device metadata; encrypt sensitive data.
- Cloud LLM for mobile or opt-in local Windows Ollama when safely reachable; never expose local Ollama directly to the internet.
- Platform speech-to-text and text-to-speech; avoid claiming unrestricted background wake-word support.
- Android contacts permission and ACTION_DIAL; iOS Contacts access and tel: dialer handoff.
- Gmail API via OAuth scopes and token encryption: read selected email, draft reply, show recipient/body, explicit approval, then send. No auto-send without approval.
- YouTube: supported player/API and explicit selection; search links alone are not playback.

## Suggested API contracts (NOT implemented)
- POST /v1/voice/interpret: transcript -> intent, slots, confidence, confirmation_required.
- POST /v1/actions/preview: intent -> safe proposed action, target, scope.
- POST /v1/actions/{id}/confirm: user-approved execution with idempotency key.
- GET /v1/actions/{id}: verified execution state and audit trail.
- GET /v1/tasks; POST /v1/tasks; GET /v1/reminders; POST /v1/reminders.

## Build order
1. Windows reliability metrics and fast deterministic intent routing.
2. Separate safe action contracts and automated tests.
3. Expo push-to-talk app with HTTPS auth and task sync.
4. Contacts dialer integration and permission handling.
5. Gmail OAuth read/draft/approve/send workflow.
6. Store release, security testing, privacy disclosures and device tests.
