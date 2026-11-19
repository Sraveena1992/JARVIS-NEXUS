# Anna AI OS — JARVIS NEXUS review preparation

## Suggested Listing fields (draft, not submitted)

- **Name:** JARVIS NEXUS
- **Slug:** jarvis-nexus (subject to availability)
- **Category:** Productivity (if available in Anna category menu)
- **Short description:** Voice-first AI workspace for tasks, research and everyday productivity.
- **Long description:** JARVIS NEXUS is a voice-first productivity workspace that combines conversational assistance, task tracking, reminders, web research shortcuts and an interactive dashboard. The current Windows prototype demonstrates local AI through Ollama and allowlisted desktop actions. The Anna edition will expose only approved, sandboxed capabilities compatible with the Anna host. Availability of each capability depends on the published Anna integration and permissions.

## Must complete before clicking Submit for Review

1. Create app in Developer Console and save Listing metadata.
2. Prepare approved logo and cover; use publicly reachable HTTPS image URLs if required.
3. Create an Anna-compatible Executa/manifest and register only actual supported actions.
4. Package a standalone UI Runtime; remove localhost assumptions, local token prompt and Windows desktop actions from hosted edition.
5. Use HTTPS backend with scoped authentication, rate limits, audit logging and safe multiuser data separation.
6. Host a real privacy policy and support contact/page. Do not invent URLs.
7. Test Anna preview and mobile layouts, permission denials, errors and reloading.
8. Create a version, validate, then use the console's actual review action.

**Submission status: NOT SUBMITTED.** No access to the user's authenticated Anna Console is available from this package. The Windows localhost backend must not be published publicly unchanged.
