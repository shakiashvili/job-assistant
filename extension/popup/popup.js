const BACKEND_URL = "http://localhost:8000";
const FRONTEND_URL = "http://localhost:5173";

document.addEventListener("DOMContentLoaded", async () => {
  await checkBackendStatus();
  await inspectCurrentTab();
  setupEventListeners();
});

async function checkBackendStatus() {
  const badge = document.getElementById("backend-status");
  const text = document.getElementById("backend-text");
  try {
    const res = await fetch(`${BACKEND_URL}/api/health`);
    if (res.ok) {
      const data = await res.json();
      badge.classList.add("online");
      text.textContent = data.gemini.connected ? "Gemini Live" : "FastAPI Online";
      text.title = `Model: ${data.gemini.model} (${data.gemini.mode})`;
    } else {
      throw new Error();
    }
  } catch (e) {
    badge.classList.remove("online");
    text.textContent = "Offline (Run Backend)";
  }
}

async function inspectCurrentTab() {
  const portalPill = document.getElementById("portal-pill");
  const tabTitle = document.getElementById("tab-title");

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;

  tabTitle.textContent = tab.title || tab.url;

  const url = (tab.url || "").toLowerCase();
  let portalName = "Generic Web";

  if (url.includes("greenhouse.io") || url.includes("greenhouse_sample")) {
    portalName = "Greenhouse";
    portalPill.style.background = "#065f46";
    portalPill.style.color = "#34d399";
  } else if (url.includes("lever.co") || url.includes("lever_sample")) {
    portalName = "Lever";
    portalPill.style.background = "#1e3a8a";
    portalPill.style.color = "#60a5fa";
  }

  portalPill.textContent = portalName;

  // Attempt to communicate with content script
  try {
    chrome.tabs.sendMessage(tab.id, { action: "GET_PAGE_STATUS" }, (response) => {
      if (chrome.runtime.lastError || !response) return;
      if (response.auditResult) {
        renderAudit(response.auditResult);
      }
    });
  } catch (err) {
    // Content script not loaded or restricted page
  }
}

function renderAudit(audit) {
  if (!audit) return;
  const scoreVal = document.getElementById("score-val");
  const scoreBar = document.getElementById("score-bar");
  const pills = document.getElementById("breakdown-pills");
  const blockersDiv = document.getElementById("blockers-preview");

  scoreVal.textContent = `${audit.match_score}%`;
  scoreBar.style.width = `${audit.match_score}%`;

  if (audit.score_breakdown) {
    pills.innerHTML = `
      <span class="pill">Skills: ${audit.score_breakdown.skills_match}%</span>
      <span class="pill">Visa: ${audit.score_breakdown.visa_match}%</span>
      <span class="pill">Exp: ${audit.score_breakdown.experience_match}%</span>
    `;
  }

  if (audit.blockers && audit.blockers.length > 0) {
    blockersDiv.innerHTML = audit.blockers.map(b => `
      <div class="blocker-item">
        <strong>${b.category.toUpperCase()}:</strong> ${b.description}
      </div>
    `).join("");
  } else {
    blockersDiv.innerHTML = `<div style="font-size:10px; color:#4ade80; margin-top:4px;">No critical blockers detected.</div>`;
  }
}

function setupEventListeners() {
  // Autofill button
  document.getElementById("btn-popup-autofill").addEventListener("click", async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return;
    chrome.tabs.sendMessage(tab.id, { action: "TRIGGER_AUTOFILL" }, (res) => {
      window.close();
    });
  });

  // Audit button
  document.getElementById("btn-popup-audit").addEventListener("click", async () => {
    const btn = document.getElementById("btn-popup-audit");
    btn.innerHTML = `<span>⏳</span> Auditing...`;
    btn.disabled = true;

    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return;

    chrome.tabs.sendMessage(tab.id, { action: "TRIGGER_AUDIT" }, (res) => {
      btn.innerHTML = `<span>🔍</span> Audit Page with Gemini`;
      btn.disabled = false;
      if (res && res.auditResult) {
        renderAudit(res.auditResult);
      }
    });
  });

  // Dashboard link
  document.getElementById("btn-open-dashboard").addEventListener("click", () => {
    chrome.tabs.create({ url: FRONTEND_URL });
  });
}
