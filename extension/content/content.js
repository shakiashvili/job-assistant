/**
 * AI Job Application Assistant - Semantic Content Script (Manifest V3)
 * Uses configurable api_base_url via chrome.storage.sync and semantic label/aria/placeholder DOM matching.
 * Never clicks CAPTCHAs automatically (flags HITL review instead).
 */

const DEFAULT_API_BASE_URL = "http://localhost:8000";

async function getApiBaseUrl() {
  return new Promise((resolve) => {
    if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.sync) {
      chrome.storage.sync.get({ api_base_url: DEFAULT_API_BASE_URL }, (items) => {
        resolve((items.api_base_url || DEFAULT_API_BASE_URL).replace(/\/+$/, ""));
      });
    } else {
      resolve(DEFAULT_API_BASE_URL);
    }
  });
}

class JobPortalAssistant {
  constructor() {
    this.portalType = this.detectPortal();
    this.groundTruth = null;
    this.auditResult = null;
    this.apiBaseUrl = DEFAULT_API_BASE_URL;
    this.init();
  }

  detectPortal() {
    const hostname = (window.location.hostname || "").toLowerCase();
    const boardAttr = document.body?.getAttribute("data-board");
    if (boardAttr) return boardAttr;
    if (hostname.includes("dou.ua")) return "dou.ua";
    if (hostname.includes("djinni.co")) return "djinni.co";
    if (hostname.includes("jobs.ge")) return "jobs.ge";
    if (hostname.includes("hr.ge")) return "hr.ge";
    if (hostname.includes("headhunter.ge") || hostname.includes("hh.ge")) return "headhunter.ge";
    if (hostname.includes("justjoin.it")) return "justjoin.it";
    if (hostname.includes("greenhouse.io")) return "greenhouse";
    if (hostname.includes("lever.co")) return "lever";
    if (document.querySelector("form")) return "generic";
    return "unknown";
  }

  async init() {
    if (window.location.port === "5173") return;
    this.apiBaseUrl = await getApiBaseUrl();
    await this.fetchGroundTruth();
    this.injectHUD();
    this.setupMessageListeners();
  }

  async fetchGroundTruth() {
    try {
      this.apiBaseUrl = await getApiBaseUrl();
      const res = await fetch(`${this.apiBaseUrl}/api/ground-truth`);
      if (res.ok) {
        this.groundTruth = await res.json();
      }
    } catch (err) {
      console.warn("[AI Job Assistant] Backend not reachable yet:", err);
    }
  }

  injectHUD() {
    if (document.getElementById("ai-job-assistant-hud")) return;

    const hud = document.createElement("div");
    hud.id = "ai-job-assistant-hud";
    hud.innerHTML = `
      <div class="hud-header" id="hud-toggle">
        <div class="hud-title">
          <span class="hud-status-dot"></span>
          <span>AI Job Assistant (${this.portalType.toUpperCase()})</span>
        </div>
        <span style="font-size:12px; color:#94a3b8; cursor:pointer;" id="hud-min-btn">▼</span>
      </div>
      <div class="hud-body">
        <div id="hud-audit-section">
          <button class="hud-btn-secondary" id="btn-run-audit">
            🔍 Audit Vacancy & Generate PDF CV
          </button>
        </div>

        <div id="hud-match-result" style="display:none; margin-top:8px;"></div>

        <div class="hud-row" style="margin-top:10px;">
          <label>CV Profile Variant (Skills.md Synced)</label>
          <select id="hud-variant-select">
            <option value="qa_automation">QA Automation (SDET / Playwright)</option>
            <option value="qa_manual">QA Manual (Exploratory / Quality)</option>
            <option value="tech_support">Tech Support (Tier 3 / API Debug)</option>
          </select>
        </div>

        <button class="hud-btn-primary" id="btn-autofill">
          ⚡ Semantic Autofill & HITL Stage
        </button>
      </div>
    `;

    document.body.appendChild(hud);

    document.getElementById("btn-autofill").addEventListener("click", () => this.autofill());
    document.getElementById("btn-run-audit").addEventListener("click", () => this.runPageAudit());
    document.getElementById("hud-toggle").addEventListener("click", (e) => {
      if (e.target.id === "hud-min-btn" || e.target.closest("#hud-toggle")) {
        hud.classList.toggle("minimized");
        const minBtn = document.getElementById("hud-min-btn");
        minBtn.textContent = hud.classList.contains("minimized") ? "▲" : "▼";
      }
    });
  }

  async runPageAudit() {
    const btn = document.getElementById("btn-run-audit");
    btn.textContent = "⏳ Auditing & Generating PDF...";
    btn.disabled = true;

    try {
      this.apiBaseUrl = await getApiBaseUrl();
      const pageText = document.body.innerText.slice(0, 10000);
      const variant = document.getElementById("hud-variant-select").value;

      const res = await fetch(`${this.apiBaseUrl}/api/audit-job`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          raw_text: pageText,
          job_url: window.location.href,
          variant: variant
        })
      });

      if (!res.ok) throw new Error("Backend audit failed");
      const data = await res.json();
      this.auditResult = data;
      this.renderAuditResult(data);
    } catch (e) {
      console.error(e);
      alert(`Could not audit job. Ensure backend is running at ${this.apiBaseUrl}`);
    } finally {
      btn.textContent = "🔍 Audit Vacancy & Generate PDF CV";
      btn.disabled = false;
    }
  }

  renderAuditResult(data) {
    const container = document.getElementById("hud-match-result");
    container.style.display = "block";

    const compVal = data.company_validation || {};
    const cv = data.tailored_cv || {};
    const sb = data.score_breakdown || {};

    // Detect direct email application (Jobs.ge, HR.ge, or raw email in text)
    const pageText = document.body.innerText;
    const emailMatch = pageText.match(/[\w.+-]+@[\w-]+\.[\w.-]+/);
    const targetEmail = emailMatch ? emailMatch[0] : null;
    let emailBannerHtml = '';
    if (targetEmail) {
      const candName = this.groundTruth?.candidate?.full_name || 'Candidate';
      const roleTitle = data.job_details?.title || 'QA Automation Engineer';
      const subject = encodeURIComponent(`Application: ${roleTitle} - ${candName}`);
      const body = encodeURIComponent(
        `Dear Hiring Team,\n\n${cv.applicant_summary || ''}\n\n${cv.motivation_statement || ''}\n\nAvailability: 1 week after offer.\nExpected Salary: ${cv.expected_salary || 'Market Rate'}\n\nPlease find my single-column ATS CV attached.\n\nBest regards,\n${candName}`
      );
      const gmailUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(targetEmail)}&su=${subject}&body=${body}`;
      emailBannerHtml = `
        <div class="ai-email-banner">
          <div>📧 <strong>Direct Email Vacancy:</strong> ${targetEmail}</div>
          <div style="font-size:10px; margin-top:2px;">Opens Gmail draft with prefilled cover note & subject. Remember to attach your downloaded ATS PDF resume!</div>
          <a href="${gmailUrl}" target="_blank">✉️ Prepare Application Email</a>
        </div>
      `;
    }

    container.innerHTML = `
      <div class="match-badge">
        <span>Overall: <strong>${data.match_score}%</strong></span>
        <span style="font-size:11px;">Skills: ${sb.skills_match}% | ATS: ${sb.ats_match}% | Recruiter: ${sb.recruiter_match}%</span>
      </div>
      <div style="font-size:11px; padding:6px 8px; border-radius:6px; margin-bottom:8px; background:${compVal.passed_gate ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.2)'}; color:${compVal.passed_gate ? '#34d399' : '#f87171'};">
        ${compVal.verdict || 'Company validated'}
      </div>
      ${cv.pdf_url ? `
        <a href="${this.apiBaseUrl}${cv.pdf_url}" target="_blank" style="display:block; text-align:center; font-size:11px; background:#0284c7; color:#fff; padding:6px; border-radius:6px; text-decoration:none; margin-bottom:8px; font-weight:600;">
          📄 Download Single-Column ATS CV (${cv.pdf_filename})
        </a>
      ` : ''}
      ${emailBannerHtml}
    `;
  }

  async solveScreeningQuestions() {
    const textareasAndInputs = Array.from(document.querySelectorAll("form textarea, form input[type='text']"));
    const questionsToSolve = [];
    for (const el of textareasAndInputs) {
      if (el.value) continue;
      let label = "";
      if (el.id) {
        const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (lbl) label = lbl.innerText;
      }
      if (!label && el.closest("label")) label = el.closest("label").innerText;
      if (!label) label = el.getAttribute("placeholder") || el.getAttribute("name") || "";
      label = label.trim();
      if (label && label.length > 5 && !/name|email|phone|linkedin|github|website|salary|start_date/i.test(label)) {
        questionsToSolve.push({ el, question: label });
      }
    }

    if (questionsToSolve.length === 0) return 0;

    try {
      const res = await fetch(`${this.apiBaseUrl}/api/answers/solve-screening`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          questions: questionsToSolve.map(q => ({ question: q.question })),
          job_title: this.auditResult?.job_details?.title,
          company: this.auditResult?.job_details?.company,
          job_description: this.auditResult?.job_details?.summary,
        })
      });
      if (!res.ok) return 0;
      const data = await res.json();
      let filled = 0;
      (data.answers || []).forEach((ans, idx) => {
        if (questionsToSolve[idx] && ans.answer) {
          const el = questionsToSolve[idx].el;
          el.focus();
          el.value = ans.answer;
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
          el.dispatchEvent(new Event("blur", { bubbles: true }));
          el.classList.add("ai-autofilled-field");
          filled++;
        }
      });
      return filled;
    } catch (err) {
      console.warn("[AI Job Assistant] Screening solve warning:", err);
      return 0;
    }
  }

  /**
   * Semantic DOM Locator:
   * 1. Associated <label> text or aria-label
   * 2. placeholder text
   * 3. Fallback semantic name/type attributes
   */
  findSemanticField(labelPatterns, fallbackSelector) {
    const inputs = Array.from(document.querySelectorAll("input:not([type='hidden']), textarea, select"));
    for (const pattern of labelPatterns) {
      const regex = new RegExp(pattern, "i");
      for (const el of inputs) {
        // Check explicit <label for="id"> or wrapping <label>
        let labelText = "";
        if (el.id) {
          const explicitLabel = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
          if (explicitLabel) labelText += " " + explicitLabel.innerText;
        }
        const parentLabel = el.closest("label");
        if (parentLabel) labelText += " " + parentLabel.innerText;
        const ariaLabel = el.getAttribute("aria-label") || "";
        const placeholder = el.getAttribute("placeholder") || "";

        if (regex.test(labelText) || regex.test(ariaLabel) || regex.test(placeholder)) {
          return el;
        }
      }
    }
    if (fallbackSelector) {
      return document.querySelector(fallbackSelector);
    }
    return null;
  }

  async autofill() {
    if (!this.groundTruth) {
      await this.fetchGroundTruth();
    }
    if (!this.groundTruth) {
      alert(`Unable to connect to backend at ${this.apiBaseUrl}. Start the backend first.`);
      return;
    }

    if (!this.auditResult) {
      await this.runPageAudit();
    }

    if (this.auditResult?.company_validation && !this.auditResult.company_validation.passed_gate) {
      const proceed = confirm(`${this.auditResult.company_validation.verdict}\n\nDo you still want to proceed?`);
      if (!proceed) return;
    }

    const candidate = this.groundTruth.candidate;
    const links = candidate.links || {};
    const comp = candidate.compensation || {};
    const cv = this.auditResult?.tailored_cv || {};
    let filledCount = 0;

    const setVal = (el, val) => {
      if (!el || !val) return false;
      el.focus();
      el.value = val;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      el.dispatchEvent(new Event("blur", { bubbles: true }));
      el.classList.add("ai-autofilled-field");
      filledCount++;
      return true;
    };

    // 1. Semantic Name, Email, Phone, Organization
    setVal(this.findSemanticField(["first name", "given name"], "input[name*='first_name']"), candidate.first_name);
    setVal(this.findSemanticField(["last name", "surname", "family name"], "input[name*='last_name']"), candidate.last_name);
    setVal(this.findSemanticField(["^full name", "^your name", "candidate name"], "input[name='name']"), candidate.full_name);
    setVal(this.findSemanticField(["email", "e-mail"], "input[type='email'], input[name*='email']"), candidate.email);
    setVal(this.findSemanticField(["phone", "mobile", "telephone"], "input[type='tel'], input[name*='phone']"), candidate.phone);
    setVal(this.findSemanticField(["current company", "organization", "employer"], "input[name='org']"), this.groundTruth.work_history?.[0]?.company);

    // 2. Semantic Social Links
    setVal(this.findSemanticField(["linkedin"], "input[name*='linkedin' i]"), links.linkedin);
    setVal(this.findSemanticField(["github"], "input[name*='github' i]"), links.github);
    setVal(this.findSemanticField(["portfolio", "website", "personal site"], "input[name*='portfolio' i]"), links.portfolio || links.github);

    // 3. Semantic Summary, Motivational Letter, AI Salary, and Start Date
    const summaryText = cv.applicant_summary || "QA Automation Engineer with 1.5 years of experience building reliable Playwright, Cypress, and Python test suites. Available 1 week after offer.";
    const douLetter = cv.dou_motivational_letter || cv.motivation_statement || "Hi team! I would love to bring my 1.5+ years of Playwright & Python automation experience to your engineering team. Available to start 1 week after offer.";
    const salaryText = cv.expected_salary || `€${comp.expected_salary_eur || 85000} / yr ($4,500/mo remote)`;

    setVal(this.findSemanticField(["applicant summary", "introduce yourself", "additional information", "summary"], "textarea[name*='summary'], textarea[name*='comments']"), summaryText);
    setVal(this.findSemanticField(["motivational letter", "cover letter", "why are you interested", "motivation", "message to recruiter"], "textarea[name*='motivation'], textarea[name='message']"), douLetter);
    setVal(this.findSemanticField(["salary", "compensation", "remuneration"], "input[name*='salary']"), salaryText);
    setVal(this.findSemanticField(["start date", "notice period", "when can you start"], "input[name*='start_date'], input[name*='notice']"), "1 week after offer");

    // 4. Solve Custom Screening Questions if any exist
    const screeningFilled = await this.solveScreeningQuestions();
    filledCount += screeningFilled;

    // 5. Non-Clicking HITL Anti-Bot / CAPTCHA Detection (Never auto-click CAPTCHAs)
    const captchaChallenge = document.querySelector(
      "iframe[src*='recaptcha'], iframe[src*='turnstile'], iframe[src*='hcaptcha'], .g-recaptcha, .cf-turnstile, .h-captcha, #captcha-checkbox, input[name*='captcha']"
    );
    if (captchaChallenge) {
      this.showToast(`⚠️ ${filledCount} fields staged! CAPTCHA detected — paused for Human-in-the-Loop (HITL) manual verification.`);
    } else {
      this.showToast(`✅ ${filledCount} fields semantically staged! Ready for Human-in-the-Loop review.`);
    }
  }

  showToast(msg) {
    const toast = document.createElement("div");
    toast.className = "ai-toast-banner";
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
  }

  setupMessageListeners() {
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
      if (request.action === "GET_PAGE_STATUS") {
        sendResponse({
          portalType: this.portalType,
          pageTitle: document.title,
          url: window.location.href,
          auditResult: this.auditResult
        });
      } else if (request.action === "TRIGGER_AUTOFILL") {
        this.autofill().then(() => sendResponse({ status: "success" }));
        return true;
      } else if (request.action === "TRIGGER_AUDIT") {
        this.runPageAudit().then(() => sendResponse({ status: "success", auditResult: this.auditResult }));
        return true;
      }
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => new JobPortalAssistant());
} else {
  new JobPortalAssistant();
}
