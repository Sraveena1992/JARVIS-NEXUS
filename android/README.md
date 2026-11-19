# JARVIS NEXUS Android — Capacitor packaging scaffold

This project wraps the **offline, device-local task preview** from `anna-app/index.html`, not the Windows FastAPI assistant. It does not have cloud AI, native speech, contacts, background reminders, or account sync.

## Build prerequisites
Node.js 20+, Java 17, Android Studio and SDK, valid Android signing configuration. Android Gradle build is not available from this repository alone.

From the repository root:
```powershell
cd android
npm install
npm run build:web
npx cap add android
npx cap sync android
npx cap open android
```
In Android Studio, test on a real Android device. Use **Build > Generate Signed Bundle / APK** to generate a release AAB with a signing key kept OUTSIDE Git. Upload the signed AAB to Google Play Console only after meeting the policy and testing requirements.

## Important release gates
- Verify Android package identifier and store name ownership before final release.
- Produce a privacy policy and accurate Data safety form. The current preview stores tasks in WebView storage on device.
- Verify accessibility, small screens, offline operation, clipboard permissions and Android back navigation.
- Do not expose or embed a JARVIS_TOKEN, Ollama URL or local Windows backend.
- Do not claim AAB exists until Android Studio/Gradle produces it and its signature is checked.
- Google Play submission requires the developer's own authenticated Play Console, signing and policy declarations.
