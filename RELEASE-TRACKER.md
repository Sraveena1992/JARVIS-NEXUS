# JARVIS NEXUS — release gates

## Existing local Windows edition
- Local FastAPI and token auth exist; bind only to 127.0.0.1.
- Unit tests include mocked integrations. Re-run tests on target Windows machine and test live Ollama separately.
- Do not deploy the current Windows backend to a public server: it has desktop and local workspace privileges.

## Anna AI OS (App 973)
- [x] Create standalone, responsive, safe Anna/mobile-web preview in anna-app/index.html
- [ ] Browser/device smoke tests performed and recorded
- [ ] Create independent JARVIS Executa with verified real tool ID
- [ ] Configure Anna manifest to match actual console schema and UI Runtime capabilities
- [ ] Build/upload UI bundle using Anna's supported flow
- [ ] Validate preview in Anna host; check storage and host permission failures
- [ ] Create immutable version and submit for review
- [ ] Confirm review status and public listing URL

## Android / Google Play
- [ ] Build Android application package (AAB) using a native wrapper or Expo project
- [ ] Decide backend strategy: secure hosted multiuser API or explicitly offline-only edition
- [ ] Test on physical Android devices, accessibility, offline behavior, privacy, app lifecycle
- [ ] Prepare Play Console account, package identifier, signing, privacy policy, data safety, screenshots, content rating and testing requirements
- [ ] Upload AAB and submit for Google review
- [ ] Confirm publication and Play Store listing URL

## Performance / security
- [ ] Measure real median/p95 chat response times on target machine
- [ ] Audit dependencies and secrets; verify no tokens in client bundles
- [ ] Add API rate limiting, per-user isolation, HTTPS gateway and threat tests before cloud hosting
- [ ] Verify platform-specific privacy disclosures and permission flows

This tracker documents **pending** gates, not completed submission or publication.
