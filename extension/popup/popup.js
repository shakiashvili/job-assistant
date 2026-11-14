(() => {
  if (window.__talentFlowPopupInitialized) return;
  window.__talentFlowPopupInitialized = true;

  const el = (id) => document.getElementById(id);

  let state = {
    apiBaseUrl: "http://localhost:8000",
    authenticated: false,
    profile: null,
    activeTabId: null,
    pageContext: null,
    scannedFields: [],
    preparedApp: null,
    isInitializing: false,
    isPreparing: false,
    listenersBound: false,
  };

  function showStatus(msg, kind = "info") {
    const banner = el("status-banner");
    if (!banner) return;
    banner.textContent = msg;
    banner.className = `status-banner ${kind === "error" ? "error" : kind === "success" ? "success" : ""}`;
    banner.classList.remove("hidden");
  }

  function hideStatus() {
    el("status-banner")?.classList.add("hidden");
  }

  function sendBg(message) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(message, (res) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(res || { ok: false, error: "No response from service worker" });
      });
    });
  }

  async function ensureContentScriptAndScrape(tabId) {
    const pingTab = () =>
      new Promise((resolve) => {
        chrome.tabs.sendMessage(tabId, { type: "SCRAPE_CONTEXT" }, (res) => {
          if (chrome.runtime.lastError || !res) {
            resolve(null);
            return;
          }
          resolve(res);
        });
      });

    let scraped = await pingTab();
    if (!scraped) {
      try {
        await chrome.scripting.insertCSS({ target: { tabId }, files: ["content/content.css"] });
        await chrome.scripting.executeScript({ target: { tabId }, files: ["content/content.js"] });
        scraped = await pingTab();
      } catch (_err) {
        return null;
      }
    }
    return scraped;
  }

  function renderProfile(profile) {
    if (!profile) return;
    const name = profile.full_name || "Candidate";
    const initials = name
      .split(/\s+/)
      .filter((w) => w && !w.startsWith("("))
      .slice(0, 2)
      .map((w) => w[0].toUpperCase())
      .join("") || "TF";

    el("cand-avatar").textContent = initials;
    el("cand-name").textContent = name;
    el("cand-role").textContent = `${profile.primary_role || "Specialist"} · ${profile.years_of_experience ?? 1.5} yrs`;

    const skillsBox = el("cand-skills");
    skillsBox.innerHTML = "";
    (profile.verified_skills || []).slice(0, 7).forEach((sk) => {
      const chip = document.createElement("span");
      chip.className = "skill-chip";
      chip.textContent = sk;
      skillsBox.appendChild(chip);
    });
  }

  function renderAuthView() {
    if (state.authenticated) {
      el("auth-section").classList.add("hidden");
      el("copilot-section").classList.remove("hidden");
      renderProfile(state.profile);
    } else {
      el("auth-section").classList.remove("hidden");
      el("copilot-section").classList.add("hidden");
    }
  }

  function renderPreparedResult(data) {
    state.preparedApp = data;
    const matchBadge = el("match-badge");
    matchBadge.classList.remove("hidden", "warn");
    matchBadge.textContent = `${data.match_score}% ${data.match_tier || "FIT"}`;
    if (data.seniority_blocked) {
      matchBadge.classList.add("warn");
    }

    if (data.extraction_failed) {
      el("extraction-warn").classList.remove("hidden");
    } else {
      el("extraction-warn").classList.add("hidden");
    }

    if (data.seniority_blocked && data.seniority_warning) {
      el("seniority-warn").textContent = `⚠️ Seniority Guard: ${data.seniority_warning}`;
      el("seniority-warn").classList.remove("hidden");
    } else {
      el("seniority-warn").classList.add("hidden");
    }

    el("job-title-input").value = data.job_title || el("job-title-input").value;
    el("company-input").value = data.company_name || el("company-input").value;
    el("salary-text").textContent = data.salary_info?.display || "Not specified";

    el("results-card").classList.remove("hidden");
    el("company-intel-text").textContent = data.company_intel?.summary || "";

    const tpList = el("talking-points-list");
    tpList.innerHTML = "";
    (data.company_intel?.talking_points || []).forEach((pt) => {
      const li = document.createElement("li");
      li.textContent = pt;
      tpList.appendChild(li);
    });

    if (data.tailored_cv?.pdf_url) {
      const dlBar = el("cv-download-bar");
      dlBar.classList.remove("hidden");
      el("cv-filename-label").textContent = data.tailored_cv.pdf_filename || "Tailored_CV.pdf";
      const fullPdfUrl = data.tailored_cv.pdf_url.startsWith("http")
        ? data.tailored_cv.pdf_url
        : `${state.apiBaseUrl}${data.tailored_cv.pdf_url}`;
      el("cv-download-link").href = fullPdfUrl;
    }

    el("cover-letter-preview").textContent = data.cover_letter || "";
    el("btn-mark-applied").classList.remove("hidden");
  }

  async function initPopup() {
    if (state.isInitializing) return;
    state.isInitializing = true;
    try {
      const health = await sendBg({ type: "CHECK_HEALTH" });
      const badge = el("conn-badge");
      if (health?.ok) {
        badge.classList.add("online");
        el("conn-text").textContent = "Backend Online";
      } else {
        badge.classList.remove("online");
        el("conn-text").textContent = health?.status === 504 ? "Waking / Timeout" : "Offline";
        if (health?.error) {
          showStatus(health.error, "error");
        }
      }

      const auth = await sendBg({ type: "GET_AUTH_STATE" });
      if (auth?.apiBaseUrl) {
        state.apiBaseUrl = auth.apiBaseUrl;
        el("api-base-url").value = auth.apiBaseUrl;
      }
      state.authenticated = Boolean(auth?.authenticated);
      state.profile = auth?.profile || null;
      renderAuthView();

      const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (activeTab?.id) {
        state.activeTabId = activeTab.id;
        const scraped = await ensureContentScriptAndScrape(activeTab.id);
        if (scraped?.ok) {
          state.pageContext = scraped.context;
          state.scannedFields = scraped.fields || [];
          el("portal-badge").textContent = (scraped.context?.portal || "generic").toUpperCase();
          el("job-title-input").value = scraped.context?.job_title || "";
          el("company-input").value = scraped.context?.company_name || "";

          if (!scraped.context?.job_title || !scraped.context?.company_name) {
            el("extraction-warn").classList.remove("hidden");
          }
          if (scraped.captcha?.detected) {
            el("captcha-warn").textContent = scraped.captcha.reason;
            el("captcha-warn").classList.remove("hidden");
          }
        } else {
          el("portal-badge").textContent = "PAGE RESTRICTED";
        }
      }
    } finally {
      state.isInitializing = false;
    }
  }

  async function runPrepareAndFill(attachCv) {
    if (state.isPreparing) return;
    if (!state.activeTabId) {
      showStatus("No active browser tab found.", "error");
      return;
    }
    state.isPreparing = true;
    const btn = attachCv ? el("btn-prepare-fill") : el("btn-fill-step");
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "⏳ Working...";
    try {
      hideStatus();
      const scraped = await ensureContentScriptAndScrape(state.activeTabId);
      if (!scraped?.ok) {
        showStatus("Cannot inspect this page tab. Navigate to a job portal and try again.", "error");
        return;
      }
      if (scraped.captcha?.detected) {
        el("captcha-warn").textContent = scraped.captcha.reason;
        el("captcha-warn").classList.remove("hidden");
        showStatus("CAPTCHA detected — auto-fill paused for manual human action.", "error");
        return;
      }

      const payload = {
        url: scraped.context?.url || "",
        portal: scraped.context?.portal || "generic",
        job_title: el("job-title-input").value.trim() || scraped.context?.job_title || "",
        company_name: el("company-input").value.trim() || scraped.context?.company_name || "",
        location: scraped.context?.location || "",
        job_description: scraped.context?.job_description || "",
        raw_page_text: scraped.context?.raw_page_text || "",
        cv_language: el("lang-select").value || null,
        fields: scraped.fields || [],
      };

      const res = await sendBg({ type: "PREPARE_APPLICATION", payload });

      if (!res?.ok) {
        if (res?.status === 401) {
          state.authenticated = false;
          renderAuthView();
        }
        showStatus(res?.error || "Failed to prepare application.", "error");
        return;
      }

      const data = res.data;
      renderPreparedResult(data);

      const fillRes = await new Promise((resolve) => {
        chrome.tabs.sendMessage(
          state.activeTabId,
          { type: "APPLY_FIELD_ANSWERS", fieldAnswers: data.field_answers || [] },
          resolve
        );
      });

      if (attachCv && data.tailored_cv?.pdf_url) {
        const pdfRes = await sendBg({ type: "FETCH_CV_BLOB", pdfUrl: data.tailored_cv.pdf_url });
        if (pdfRes?.ok && pdfRes.base64) {
          await new Promise((resolve) => {
            chrome.tabs.sendMessage(
              state.activeTabId,
              {
                type: "ATTACH_PDF",
                base64: pdfRes.base64,
                filename: data.tailored_cv.pdf_filename || pdfRes.filename,
              },
              resolve
            );
          });
        }
      }

      showStatus(
        `Ready: Filled ${fillRes?.filledCount || 0} fields cleanly. Verify everything before clicking Next or Submit.`,
        "success"
      );
    } finally {
      state.isPreparing = false;
      btn.disabled = false;
      btn.textContent = origText;
    }
  }

  function bindEventListenersOnce() {
    if (state.listenersBound) return;
    state.listenersBound = true;

    el("btn-toggle-token")?.addEventListener("click", () => el("token-box")?.classList.toggle("hidden"));
    el("btn-toggle-api")?.addEventListener("click", () => el("api-settings-card")?.classList.toggle("hidden"));
    el("btn-toggle-settings")?.addEventListener("click", () => el("api-settings-card")?.classList.toggle("hidden"));

    el("btn-save-api")?.addEventListener("click", async () => {
      const url = el("api-base-url").value.trim();
      const res = await sendBg({ type: "SET_API_BASE", apiBaseUrl: url });
      if (res?.ok) {
        state.apiBaseUrl = res.apiBaseUrl;
        el("api-settings-card")?.classList.add("hidden");
        showStatus(`Synced backend URL to ${res.apiBaseUrl}`, "success");
        initPopup();
      }
    });

  el("btn-login")?.addEventListener("click", async () => {
    const email = el("login-email").value.trim();
    const password = el("login-password").value;
    if (!email || !password) {
      showStatus("Enter your email and password.", "error");
      return;
    }
    el("btn-login").disabled = true;
    const res = await sendBg({ type: "LOGIN", email, password });
    el("btn-login").disabled = false;
    if (!res?.ok) {
      showStatus(res?.error || "Login failed.", "error");
      return;
    }
    state.authenticated = true;
    state.profile = res.profile;
    hideStatus();
    renderAuthView();
  });

  el("btn-save-token")?.addEventListener("click", async () => {
    const token = el("manual-jwt").value.trim();
    const res = await sendBg({ type: "SET_TOKEN", token });
    if (!res?.ok) {
      showStatus(res?.error || "Invalid JWT token.", "error");
      return;
    }
    state.authenticated = true;
    state.profile = res.profile;
    hideStatus();
    renderAuthView();
  });

  el("btn-logout")?.addEventListener("click", async () => {
    await sendBg({ type: "LOGOUT" });
    state.authenticated = false;
    state.profile = null;
    state.preparedApp = null;
    renderAuthView();
    showStatus("Signed out.", "info");
  });

  el("btn-prepare-fill")?.addEventListener("click", () => runPrepareAndFill(true));
  el("btn-fill-step")?.addEventListener("click", () => runPrepareAndFill(false));

  el("btn-mark-applied")?.addEventListener("click", async () => {
    const app = state.preparedApp || {};
    const jobUrl = state.pageContext?.url || window.location.href;
    const payload = {
      company_name: el("company-input").value.trim() || app.company_name || "Unknown Company",
      job_title: el("job-title-input").value.trim() || app.job_title || "Unknown Title",
      job_url: jobUrl,
      portal: state.pageContext?.portal || app.portal || "custom",
      salary_offered: app.salary_info?.display || null,
      cv_pdf_path: app.tailored_cv?.pdf_filename || null,
      cover_letter_text: app.cover_letter || null,
      status: "APPLIED",
    };
    const res = await sendBg({ type: "LOG_APPLICATION", payload });
    if (res?.ok) {
      showStatus(`Saved "${payload.job_title}" at "${payload.company_name}" to your Kanban Tracker!`, "success");
    } else {
      showStatus(res?.error || "Could not save application to Kanban tracker.", "error");
    }
  });

  el("btn-copy-letter")?.addEventListener("click", async () => {
    const txt = el("cover-letter-preview").textContent || "";
    if (!txt) return;
    await navigator.clipboard.writeText(txt);
    showStatus("Copied cover letter to clipboard.", "success");
  });
  }

  function startPopup() {
    bindEventListenersOnce();
    initPopup();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startPopup, { once: true });
  } else {
    startPopup();
  }
})();
