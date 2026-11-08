/**
 * AI Job Application Assistant - Content Script
 * Detects DOU.ua, Djinni, Jobs.ge, HR.ge, HeadHunter.ge, JustJoin.it, Greenhouse, and Lever fields.
 */

const BACKEND_URL = "http://localhost:8000";

class JobPortalAssistant {
  constructor() {
    this.portalType = this.detectPortal();
    this.groundTruth = null;
    this.auditResult = null;
    this.init();
  }

  detectPortal() {
    const url = window.location.href.toLowerCase();
    const boardAttr = document.body?.getAttribute("data-board");
    if (boardAttr) return boardAttr;
    if (url.includes("dou.ua") || url.includes("dou_sample")) return "dou.ua";
    if (url.includes("djinni.co") || url.includes("djinni_sample")) return "djinni.co";
    if (url.includes("jobs.ge") || url.includes("jobs_ge_sample")) return "jobs.ge";
    if (url.includes("hr.ge")) return "hr.ge";
    if (url.includes("headhunter.ge") || url.includes("hh.ge")) return "headhunter.ge";
    if (url.includes("justjoin.it") || url.includes("justjoin_sample")) return "justjoin.it";
    if (url.includes("greenhouse.io") || url.includes("greenhouse_sample")) return "greenhouse";
    if (url.includes("lever.co") || url.includes("lever_sample")) return "lever";
    if (document.querySelector("form")) return "generic";
    return "unknown";
  }

  async init() {
    if (window.location.port === "5173") return; // Do not inject HUD onto the React dashboard itself
    await this.fetchGroundTruth();
    this.injectHUD();
    this.setupMessageListeners();
  }

  async fetchGroundTruth() {
    try {
      const res = await fetch(`${BACKEND_URL}/api/ground-truth`);
      if (res.ok) {
        this.groundTruth = await res.json();
      }
    } catch (err) {
      console.warn("[AI Job Assistant] Local backend not reachable yet:", err);
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
          ⚡ Autofill All, CAPTCHA & Stage
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
      const pageText = document.body.innerText.slice(0, 10000);
      const variant = document.getElementById("hud-variant-select").value;

      const res = await fetch(`${BACKEND_URL}/api/audit-job`, {
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
      alert("Could not audit job. Ensure local backend is running at http://localhost:8000");
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

    container.innerHTML = `
      <div class="match-badge">
        <span>Overall: <strong>${data.match_score}%</strong></span>
        <span style="font-size:11px;">Skills: ${sb.skills_match}% | ATS: ${sb.ats_match}% | Recruiter: ${sb.recruiter_match}%</span>
      </div>
      <div style="font-size:11px; padding:6px 8px; border-radius:6px; margin-bottom:8px; background:${compVal.passed_gate ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.2)'}; color:${compVal.passed_gate ? '#34d399' : '#f87171'};">
        ${compVal.verdict || 'Company validated'}
      </div>
      ${cv.pdf_url ? `
        <a href="${BACKEND_URL}${cv.pdf_url}" target="_blank" style="display:block; text-align:center; font-size:11px; background:#0284c7; color:#fff; padding:6px; border-radius:6px; text-decoration:none; margin-bottom:8px; font-weight:600;">
          📄 Download Tailored Human-Tone CV (${cv.pdf_filename})
        </a>
      ` : ''}
    `;
  }

  async autofill() {
    if (!this.groundTruth) {
      await this.fetchGroundTruth();
    }
    if (!this.groundTruth) {
      alert("Unable to connect to local backend at http://localhost:8000. Start the backend first.");
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

    // 1. Names, Email, Phone
    setVal(document.querySelector("#first_name, input[name*='first_name']"), candidate.first_name);
    setVal(document.querySelector("#last_name, input[name*='last_name']"), candidate.last_name);
    setVal(document.querySelector("#full_name, #full-name, input[name='name']"), candidate.full_name);
    setVal(document.querySelector("#email, input[name='email'], input[type='email']"), candidate.email);
    setVal(document.querySelector("#phone, input[name='phone'], input[type='tel']"), candidate.phone);
    setVal(document.querySelector("#org, input[name='org']"), this.groundTruth.work_history?.[0]?.company);

    // 2. Social Links
    setVal(document.querySelector("#linkedin, #linkedin-url, input[name='urls[LinkedIn]'], input[autocomplete='custom-question-linkedin-profile']"), links.linkedin);
    setVal(document.querySelector("#github-url, input[name='urls[GitHub]']"), links.github);
    setVal(document.querySelector("#portfolio-url, input[name='urls[Portfolio]'], input[autocomplete='custom-question-website']"), links.portfolio || links.github);

    // 3. Human-Tone Applicant Summary, DOU.ua Motivational Letter, Salary, and Start Date (1 week after offer)
    const summaryText = cv.applicant_summary || "Senior QA Automation Engineer with 5+ years building reliable Playwright, Cypress, and Python test suites. Available 1 week after offer.";
    const douLetter = cv.dou_motivational_letter || cv.motivation_statement || "Hi team! I would love to bring my 5+ years of Playwright & Python automation experience to your engineering team. Available to start 1 week after offer.";
    const salaryText = cv.expected_salary || `€${comp.expected_salary_eur || 85000} / yr ($4,500/mo remote)`;

    setVal(document.querySelector("#applicant_summary, textarea[name*='summary'], #additional-comments"), summaryText);
    setVal(document.querySelector("#dou_motivational_letter, textarea[name*='motivational_letter']"), douLetter);
    setVal(document.querySelector("#motivation, #custom-question-motivation, textarea[name*='motivation'], textarea[name='message']"), douLetter);
    setVal(document.querySelector("#salary, #salary_expectation, #custom-question-salary, input[name*='salary']"), salaryText);
    setVal(document.querySelector("#start_date, #custom-question-notice, input[name*='start_date'], input[name*='notice']"), "1 week after offer");

    // 4. Check CAPTCHA checkbox if present
    const captchaBox = document.querySelector("#captcha-checkbox, input[name*='captcha'], input[type='checkbox'][id*='captcha']");
    if (captchaBox && !captchaBox.checked) {
      captchaBox.click();
      captchaBox.checked = true;
      captchaBox.dispatchEvent(new Event("change", { bubbles: true }));
      filledCount++;
    }

    this.showToast(`✅ ${filledCount} fields + CAPTCHA staged! Start date set to '1 week after offer'.`);
  }

  showToast(msg) {
    const toast = document.createElement("div");
    toast.className = "ai-toast-banner";
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4500);
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
