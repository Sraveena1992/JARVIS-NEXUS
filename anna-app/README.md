# JARVIS NEXUS — standalone Anna/mobile-web preview

This directory is a self-contained static SPA with no build dependencies. Its entry is `index.html`. It offers bilingual task entry, local task storage, task completion/deletion, local date/time, and clipboard export. It has no backend access, Windows desktop controls, Ollama connection, or unverified Anna host API calls.

## Local verification
Run `python -m http.server 8080 --directory anna-app` from the repository root and open http://127.0.0.1:8080 on a desktop browser. Test at 320px, 375px, 768px and desktop widths using browser device emulation. Confirm add, complete, delete, reload persistence, keyboard operation, storage-disabled behavior and clipboard fallback.

## Anna submission
Use the real Developer Console at https://anna.partners/developer?app=973 . Do not copy the Windows localhost app into an Anna bundle. The Anna UI Runtime must accept a static SPA with entry `index.html`. A separate, real JARVIS Executa must be created and its actual tool ID referenced using the **schema shown by the live Console**, not a fabricated ID. This directory is an honest safe preview, not an Anna-approved published bundle. Obtain any required bundle format from the Console before uploading.

## Limitations
Browser localStorage is device-local and not account-sync or secure server storage. No login, push reminders, AI chat, voice recognition, mobile native integrations, or payments. Do not represent it as a full mobile assistant or as production multi-user software.
