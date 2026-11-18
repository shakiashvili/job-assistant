# TalentFlow AI — Chrome Extension Copilot Guide

## 1. Features & Security Model (Manifest V3)
- **Permissions Used**:
  - `activeTab`: reads job posting metadata and form fields on the user's current tab only when interacted with.
  - `scripting`: injects `content.js` dynamically when syncing web session tokens or scanning SPAs.
  - `storage`: stores the synced backend API URL (`chrome.storage.sync`) and short-lived auth/refresh tokens (`chrome.storage.local`).
  - `sidePanel`: renders the Copilot side panel beside LinkedIn, Workday, Greenhouse, Lever, DOU.ua, Djinni.co, Jobs.ge, HR.ge, JustJoin.it, and HeadHunter.ge.
- **Least-Privilege Host Policy**: Unconditional wildcard `host_permissions` (`*://*/*`) are **not** requested up front. Supported job portals and local dev hosts (`http://localhost:8000/*`, `http://localhost:5173/*`) are listed explicitly in `host_permissions`, while arbitrary employer/custom ATS domains use `optional_host_permissions` granted only when the user explicitly clicks **Grant Site Access** via `chrome.permissions.request()`.
- **Human-in-the-Loop Guarantee**: The extension detects reCAPTCHA / hCaptcha / Cloudflare Turnstile and pauses immediately. It **never** auto-clicks final Submit buttons or bypasses anti-bot challenges.
- **Pre-Fill Edit Review**: Generated per-field answers are rendered inside **Editable Auto-Fill Answers** so candidates can adjust any response before clicking **Apply Edits to Page**.

## 2. Local Installation & Development
1. Open `chrome://extensions` in Google Chrome.
2. Enable **Developer mode** (top right toggle).
3. Click **Load unpacked** and select the `extension/` folder.
4. Click the extension icon to open the Side Panel.
5. Verify **Backend Online** (`http://localhost:8000` by default, or configure a hosted URL via **⚙️ API**).

## 3. Packaging for Chrome Web Store Submission
1. Bump `"version"` cleanly in `extension/manifest.json`.
2. Verify manifest and syntax:
   ```bash
   node -e "JSON.parse(require('fs').readFileSync('extension/manifest.json','utf8')); console.log('OK')"
   node --check extension/background/service_worker.js
   node --check extension/content/content.js
   node --check extension/popup/popup.js
   ```
3. Zip the contents of `extension/` (with `manifest.json` at the root of the archive).
4. Upload to the Chrome Web Store Developer Dashboard and provide the single-purpose justification above for `activeTab`, `scripting`, `storage`, and `sidePanel`.
