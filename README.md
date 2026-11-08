# 🚀 TalentFlow AI — Universal Multi-Industry Job Application & Bilingual (EN / KA ქართული) CV Platform

A production-ready, Human-in-the-Loop AI Job Application & CV Synthesis SaaS platform powered by **FastAPI**, **Google Gemini 2.5 Flash**, **Playwright**, **React + Vite + Tailwind CSS**, and a **Manifest V3 Chrome Extension**.

---

## 🌟 Key Capabilities (B2B & Candidate Suite)

### 1. Universal Multi-Industry Support
Works across technical and non-technical professions out of the box with 1-click `.md` profile templates:
- 💻 **QA Automation & Software Engineering** (Playwright, Cypress, Python, TypeScript, CI/CD, SDET)
- 🏨 **Hotel Receptionist & Hospitality** (Front Desk Operations, Opera PMS, Fidelio, Booking.com/Expedia Extranet, VIP Guest Relations, POS Billing)
- 🎧 **Customer Service & Client Care** (Omnichannel Support, Zendesk, Intercom, Salesforce CRM, Conflict De-escalation, CSAT/NPS)
- 🏥 **Hospital & Healthcare Administration** (Patient Registration, Medical Reception, EMR/EHR Systems, Health Insurance Verification, Triage & Scheduling)

### 2. Bilingual CV Generation: English (`🇬🇧 EN`) & Georgian (`🇬🇪 KA ქართული ენა`)
- Upload or edit your `candidate_skills.md` in **English or Georgian**.
- Click **🇬🇧 Audit & Generate English CV** or **🇬🇪 Audit & Generate ქართული CV** to synthesize a natural, human-tone PDF CV (`CV_<Company>_<Role>_EN.pdf` or `CV_<Company>_<Role>_KA.pdf`) plus a crisp printable HTML version rendered with full Georgian Unicode typography (`Sylfaen` / `Noto Sans Georgian`).

### 3. 3-Dimensional Match Audit + Employer 3+ Reviews Gate
- Returns **Skills Match (%)**, **ATS Match (%)**, **Recruiter Match (%)**, and **Identified Gaps + Bridge Strategy**.
- Validates employer reputation across job portals (**3+ verified employee reviews gate**) before staging an application.

### 4. Multi-Portal Vacancy Feed & Playwright Live Form Stager
- Supports **Jobs.ge**, **HR.ge**, **HeadHunter.ge**, **DOU.ua** (with mandatory DOU Motivational Letter), **Djinni.co**, **JustJoin.it**, **Greenhouse**, and **Lever**.
- Launches a live Chromium window to pre-fill contact info, **Applicant Summary**, **Motivational Letter**, **Salary Expectation**, **Default 1-Week Start Date** (`1 week after offer` / `1 კვირა შეთავაზებიდან`), attaches the tailored PDF CV, checks CAPTCHA, and pauses for human review.

---

## 🛠️ Quick Start

### 1. Start the FastAPI Backend (`:8000`)
```powershell
cd backend
pip install -r requirements.txt
playwright install chromium
python run.py
```
- Backend API & Swagger Docs: `http://localhost:8000/docs`

### 2. Start the React Web Dashboard (`:5173`)
```powershell
cd frontend
npm install
npm run dev -- --host
```
- Web Dashboard: `http://localhost:5173`

### 3. Load the Chrome Extension (Optional)
1. Open Chrome and navigate to `chrome://extensions/`.
2. Enable **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select the `extension/` folder.

---

## 🤝 How to Share This Repository on GitHub

Run the following commands from the project root (`C:\Users\giorg\.gemini\antigravity\scratch\job-application-assistant`):

```powershell
cd "C:\Users\giorg\.gemini\antigravity\scratch\job-application-assistant"
git init
git add .
git commit -m "feat: TalentFlow AI - Multi-Industry & Bilingual EN/KA Job Assistant"
git branch -M main

# Create a new repository at https://github.com/new (do not initialize with README), then run:
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/talentflow-ai-job-assistant.git
git push -u origin main
```

### Sharing a Live Demo Link with Businesses Instantly
To share your running local app (`http://localhost:5173`) with clients, recruiters, or businesses over HTTPS without deploying:
```powershell
npx localtunnel --port 5173
```
*(Or click the **"Share Repo"** button in the top navigation bar of the web dashboard for 1-click copyable commands!)*
