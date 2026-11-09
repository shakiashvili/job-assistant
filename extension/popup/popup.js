const DEFAULT_API_BASE_URL = "http://localhost:8000";
const DEFAULT_FRONTEND_URL = "http://localhost:5173";

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

document.addEventListener("DOMContentLoaded", async () => {
  const apiUrl = await getApiBaseUrl();
  const inputEl = document.getElementById("api-base-url-input");
  if (inputEl) inputEl.value = apiUrl;

  await checkBackendStatus(apiUrl);
  await inspectCurrentTab();
  setupEventListeners();
});

async function checkBackendStatus(apiBaseUrl) {
  const badge = document.getElementById("backend-status");
  const text = document.getElementById("backend-text");
  const baseUrl = apiBaseUrl || (await getApiBaseUrl());
  try {
    const res = await fetch(`${baseUrl}/api/health`);
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

  if (url.includes("greenhouse.io")) {
    portalName = "Greenhouse";
    portalPill.style.background = "#065f46";
    portalPill.style.color = "#34d399";
  } else if (url.includes("lever.co")) {
    portalName = "Lever";
    portalPill.style.background = "#1e3a8a";
    portalPill.style.color = "#60a5fa";
  } else if (url.includes("dou.ua")) {
    portalName = "DOU.ua";
  } else if (url.includes("djinni.co")) {
    portalName = "Djinni.co";
  } else if (url.includes("jobs.ge")) {
    portalName = "Jobs.ge";
  } else if (url.includes("hr.ge")) {
    portalName = "HR.ge";
  }

  portalPill.textContent = portalName;

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
  const saveApiBtn = document.getElementById("btn-save-api-url");
  if (saveApiBtn) {
    saveApiBtn.addEventListener("click", async () => {
      const inputEl = document.getElementById("api-base-url-input");
      const newUrl = (inputEl?.value || DEFAULT_API_BASE_URL).trim().replace(/\/+$/, "");
      if (chrome.storage && chrome.storage.sync) {
        chrome.storage.sync.set({ api_base_url: newUrl }, async () => {
          saveApiBtn.textContent = "Saved!";
          await checkBackendStatus(newUrl);
          setTimeout(() => {
            saveApiBtn.textContent = "Save";
          }, 1500);
        });
      }
    });
  }

  document.getElementById("btn-popup-autofill").addEventListener("click", async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return;
    chrome.tabs.sendMessage(tab.id, { action: "TRIGGER_AUTOFILL" }, () => {
      window.close();
    });
  });

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

  document.getElementById("btn-open-dashboard").addEventListener("click", () => {
    chrome.tabs.create({ url: DEFAULT_FRONTEND_URL });
  });
}
