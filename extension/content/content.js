(() => {
  if (window.__talentFlowCopilotLoaded) return;
  window.__talentFlowCopilotLoaded = true;

  function detectPortal() {
    const host = (window.location.hostname || "").toLowerCase();
    const url = (window.location.href || "").toLowerCase();
    if (host.includes("linkedin.com")) return "linkedin.com";
    if (host.includes("myworkdayjobs.com")) return "workday";
    if (host.includes("greenhouse.io") || url.includes("/mock-portals/greenhouse")) return "greenhouse";
    if (host.includes("lever.co") || url.includes("/mock-portals/lever")) return "lever";
    if (host.includes("djinni.co")) return "djinni.co";
    if (host.includes("dou.ua") || url.includes("/mock-portals/dou")) return "dou.ua";
    if (host.includes("vacancy.hr.gov.ge") || host.includes("hr.gov.ge")) return "hr.gov.ge";
    if (host.includes("jobs.ge")) return "jobs.ge";
    if (host.includes("headhunter.ge")) return "headhunter.ge";
    if (host.includes("hr.ge")) return "hr.ge";
    if (host.includes("justjoin.it")) return "justjoin.it";
    return "generic";
  }

  function cleanText(el) {
    return el ? (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim() : "";
  }

  function firstText(selectors, root = document) {
    for (const sel of selectors) {
      const el = root.querySelector(sel);
      const txt = cleanText(el);
      if (txt) return txt;
    }
    return "";
  }

  function detectCaptcha() {
    const iframe = document.querySelector(
      'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], iframe[title*="reCAPTCHA"]'
    );
    const widget = document.querySelector(".g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]");
    const bodyLow = (document.body?.innerText || "").slice(0, 2500).toLowerCase();
    const challengeText =
      bodyLow.includes("verify you are human") ||
      bodyLow.includes("i am not a robot") ||
      bodyLow.includes("security verification challenge");

    if (iframe || widget || challengeText) {
      return {
        detected: true,
        reason: "CAPTCHA or anti-bot challenge detected on page. Please complete verification manually.",
      };
    }
    return { detected: false, reason: "" };
  }

  function extractJobContext() {
    const portal = detectPortal();
    let jobTitle = "";
    let companyName = "";
    let location = "";
    let jobDescription = "";

    if (portal === "linkedin.com") {
      jobTitle = firstText([
        ".job-details-jobs-unified-top-card__job-title h1",
        ".job-details-jobs-unified-top-card__job-title",
        ".jobs-unified-top-card__job-title",
        "h1.t-24",
        ".jobs-easy-apply-modal #jobs-apply-header",
      ]);
      // Easy Apply header often reads "Apply to <Company>"
      const applyHdr = firstText(["#jobs-apply-header", ".jobs-easy-apply-modal h2"]);
      companyName = firstText([
        ".job-details-jobs-unified-top-card__company-name a",
        ".job-details-jobs-unified-top-card__company-name",
        ".jobs-unified-top-card__company-name a",
        ".jobs-unified-top-card__company-name",
        ".topcard__org-name-link",
      ]);
      if (!companyName && applyHdr && /^apply to\s+/i.test(applyHdr)) {
        companyName = applyHdr.replace(/^apply to\s+/i, "").trim();
      }
      location = firstText([
        ".job-details-jobs-unified-top-card__primary-description-container .tvm__text",
        ".jobs-unified-top-card__bullet",
        ".topcard__flavor--bullet",
      ]);
      jobDescription = firstText([
        "#job-details",
        ".jobs-description__content",
        ".jobs-description-content__text",
        ".show-more-less-html__markup",
      ]);
    } else if (portal === "workday") {
      jobTitle = firstText([
        '[data-automation-id="jobPostingHeader"] h2',
        '[data-automation-id="jobPostingHeader"]',
        "h1",
        "h2",
      ]);
      const metaSite = document.querySelector('meta[property="og:site_name"]')?.getAttribute("content") || "";
      const subHost = window.location.hostname.split(".")[0] || "";
      companyName = metaSite || (subHost && !subHost.startsWith("wd") ? subHost : "");
      location = firstText(['[data-automation-id="locations"] dd', '[data-automation-id="locations"]']);
      jobDescription = firstText(['[data-automation-id="jobPostingDescription"]']);
    } else if (portal === "greenhouse" || portal === "lever") {
      jobTitle = firstText(["h1.app-title", ".posting-headline h2", "h1"]);
      companyName = firstText([".company-name", ".main-header-logo img[alt]"]) ||
        (document.querySelector('meta[property="og:site_name"]')?.getAttribute("content") || "");
      location = firstText([".location", ".posting-categories .location"]);
      jobDescription = firstText(["#content", ".posting-page", ".section-wrapper"]);
    } else if (portal === "dou.ua") {
      jobTitle = firstText(["h1.g-h2", ".b-vacancy h1", "h1"]);
      companyName = firstText([
        ".b-compinfo .l-n a",
        ".b-compinfo .l-n",
        ".comp-name a",
        ".company-name",
      ]) || "";
      location = firstText([".place", ".b-vacancy .place", ".location"]);
      jobDescription = firstText([".b-typo.vacancy-section", ".b-vacancy", "article", "main"]);
    } else if (portal === "djinni.co") {
      jobTitle = firstText(["header h1", "h1"]);
      companyName = firstText([
        ".job-details--title a",
        "a.text-reset[href*='/jobs/company-']",
        ".company-name",
      ]) || "";
      location = firstText([".location-text", ".job-additional-info--item"]);
      jobDescription = firstText([".job-post__description", ".profile-page-section", "main"]);
    } else {
      jobTitle = firstText(["h1.job-title", "h1", ".vacancy-title", "h2"]);
      const metaSite = (document.querySelector('meta[property="og:site_name"]')?.getAttribute("content") || "").trim();
      const genericPortalSites = new Set(["dou", "dou.ua", "djinni", "djinni.co", "jobs.ge", "hr.ge", "hr.gov.ge", "linkedin", "workday"]);
      companyName =
        firstText([".company-name", ".employer-name", '[itemprop="hiringOrganization"]']) ||
        (!genericPortalSites.has(metaSite.toLowerCase()) ? metaSite : "");
      jobDescription = firstText(["main", "article", ".job-description", ".description"]);
    }

    const rawPageText = (document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 6000);
    return {
      url: window.location.href,
      portal,
      job_title: jobTitle,
      company_name: companyName.replace(/^at\s+/i, "").trim(),
      location,
      job_description: (jobDescription || rawPageText).slice(0, 5000),
      raw_page_text: rawPageText,
    };
  }

  function resolveFieldLabel(el, root) {
    if (!el) return "";
    if (el.id) {
      const explicitLabel = root.querySelector(`label[for="${CSS.escape(el.id)}"]`) ||
        document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (explicitLabel && cleanText(explicitLabel)) return cleanText(explicitLabel);
    }
    const parentLabel = el.closest("label");
    if (parentLabel) {
      const copy = parentLabel.cloneNode(true);
      copy.querySelectorAll("input, select, textarea").forEach((n) => n.remove());
      const txt = cleanText(copy);
      if (txt) return txt;
    }
    const aria = el.getAttribute("aria-label");
    if (aria && aria.trim()) return aria.trim();

    const ariaId = el.getAttribute("aria-labelledby");
    if (ariaId) {
      const refEl = document.getElementById(ariaId.split(/\s+/)[0]);
      if (refEl && cleanText(refEl)) return cleanText(refEl);
    }

    const liWrap = el.closest(
      '.fb-dash-form-element, .jobs-easy-apply-form-element, [data-automation-id="formField"], .field, .form-group, fieldset'
    );
    if (liWrap) {
      const lbl = liWrap.querySelector(
        'label, legend, span.fb-dash-form-element__label, span[data-test-single-line-text-form-component], .artdeco-text-input--label, h3, h4'
      );
      if (lbl && cleanText(lbl)) return cleanText(lbl);
    }

    return (el.getAttribute("placeholder") || el.getAttribute("name") || el.id || "").trim();
  }

  function isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 || rect.height > 0 || el.type === "file";
  }

  function getActiveFormRoot() {
    return (
      document.querySelector(".jobs-easy-apply-modal") ||
      document.querySelector('[data-automation-id="applyFlowPage"]') ||
      document.querySelector('[role="dialog"] form') ||
      document.querySelector("form") ||
      document.body
    );
  }

  function scanFormFields() {
    const root = getActiveFormRoot();
    if (!root) return [];

    const fields = [];
    const seenRadioNames = new Set();
    let idx = 0;

    // 1. Fieldset / radio groups first
    const radios = root.querySelectorAll('input[type="radio"]');
    for (const r of radios) {
      const rName = r.getAttribute("name") || "";
      if (!rName || seenRadioNames.has(rName)) continue;
      seenRadioNames.add(rName);
      const groupRadios = Array.from(root.querySelectorAll(`input[type="radio"][name="${CSS.escape(rName)}"]`));
      if (!groupRadios.some(isVisible)) continue;

      const fieldId = r.getAttribute("data-tf-field-id") || `tf-field-${idx++}`;
      groupRadios.forEach((gr) => gr.setAttribute("data-tf-field-id", fieldId));

      const fs = r.closest("fieldset, .fb-dash-form-element, [data-automation-id='formField']");
      const legend = fs ? cleanText(fs.querySelector("legend, label, .fb-dash-form-element__label, span")) : "";
      const options = groupRadios.map((gr) => {
        const lbl = resolveFieldLabel(gr, root);
        return lbl || gr.value || "";
      }).filter(Boolean);

      fields.push({
        field_id: fieldId,
        name: rName,
        label: legend || rName,
        field_type: "radio",
        placeholder: null,
        required: groupRadios.some((gr) => gr.required || gr.getAttribute("aria-required") === "true"),
        options,
      });
    }

    // 2. Inputs, textareas, selects
    const controls = root.querySelectorAll(
      'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="reset"]):not([type="radio"]), textarea, select'
    );
    for (const el of controls) {
      if (!isVisible(el)) continue;
      const tag = el.tagName.toLowerCase();
      const inputType = tag === "input" ? (el.getAttribute("type") || "text").toLowerCase() : tag;
      const fieldId = el.getAttribute("data-tf-field-id") || `tf-field-${idx++}`;
      el.setAttribute("data-tf-field-id", fieldId);

      const options =
        tag === "select"
          ? Array.from(el.options)
              .map((o) => (o.text || o.value || "").trim())
              .filter((t) => t && !/^select\b|^choose\b|^--/i.test(t))
          : [];

      fields.push({
        field_id: fieldId,
        name: el.getAttribute("name") || el.id || null,
        label: resolveFieldLabel(el, root),
        field_type: inputType,
        placeholder: el.getAttribute("placeholder") || null,
        required: Boolean(el.required || el.getAttribute("aria-required") === "true"),
        options,
      });
    }

    return fields;
  }

  function setNativeValue(el, value) {
    const tag = el.tagName.toLowerCase();
    const proto =
      tag === "textarea"
        ? window.HTMLTextAreaElement.prototype
        : tag === "select"
        ? window.HTMLSelectElement.prototype
        : window.HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor && descriptor.set) {
      descriptor.set.call(el, value);
    } else {
      el.value = value;
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function applyFieldAnswers(fieldAnswers) {
    if (!Array.isArray(fieldAnswers) || !fieldAnswers.length) return { filledCount: 0 };
    let filledCount = 0;

    for (const item of fieldAnswers) {
      const val = String(item?.value ?? "").trim();
      if (!val || !item?.field_id) continue;

      const targets = document.querySelectorAll(`[data-tf-field-id="${CSS.escape(item.field_id)}"]`);
      if (!targets.length) continue;

      const first = targets[0];
      const tag = first.tagName.toLowerCase();
      const ftype = (first.getAttribute("type") || tag).toLowerCase();

      if (ftype === "file") continue;

      if (ftype === "radio") {
        const valLow = val.toLowerCase();
        let matched = null;
        for (const r of targets) {
          const rLbl = resolveFieldLabel(r, document).toLowerCase();
          const rVal = (r.value || "").toLowerCase();
          if (rVal === valLow || rLbl === valLow || (valLow && (rLbl.includes(valLow) || valLow.includes(rLbl)))) {
            matched = r;
            break;
          }
        }
        if (matched) {
          matched.click();
          matched.dispatchEvent(new Event("change", { bubbles: true }));
          matched.closest("label, fieldset")?.classList.add("ai-autofilled-field");
          filledCount++;
        }
        continue;
      }

      if (ftype === "checkbox") {
        const shouldCheck = val.toLowerCase() === "true" || val.toLowerCase() === "yes";
        if (first.checked !== shouldCheck) {
          first.click();
          first.dispatchEvent(new Event("change", { bubbles: true }));
        }
        first.classList.add("ai-autofilled-field");
        filledCount++;
        continue;
      }

      if (tag === "select") {
        const valLow = val.toLowerCase();
        const opt = Array.from(first.options).find(
          (o) =>
            o.value.toLowerCase() === valLow ||
            o.text.trim().toLowerCase() === valLow ||
            o.text.trim().toLowerCase().includes(valLow) ||
            valLow.includes(o.text.trim().toLowerCase())
        );
        if (opt) {
          setNativeValue(first, opt.value);
          first.classList.add("ai-autofilled-field");
          filledCount++;
        }
        continue;
      }

      setNativeValue(first, val);
      first.classList.add("ai-autofilled-field");
      filledCount++;
    }

    return { filledCount };
  }

  function base64ToFile(base64, filename, mimeType = "application/pdf") {
    const bin = atob(base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) {
      bytes[i] = bin.charCodeAt(i);
    }
    return new File([bytes], filename, { type: mimeType, lastModified: Date.now() });
  }

  function triggerBrowserDownload(blobOrFile, filename) {
    const url = URL.createObjectURL(blobOrFile);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(url);
      a.remove();
    }, 3000);
  }

  function attachResumePdf(base64, filename) {
    const file = base64ToFile(base64, filename || "Tailored_Resume.pdf", "application/pdf");
    const root = getActiveFormRoot() || document;
    const fileInputs = Array.from(root.querySelectorAll('input[type="file"]'));
    let attached = false;

    for (const fi of fileInputs) {
      const lbl = resolveFieldLabel(fi, root).toLowerCase();
      if (lbl && (lbl.includes("photo") || lbl.includes("avatar") || lbl.includes("cover image"))) {
        continue;
      }
      try {
        const dt = new DataTransfer();
        dt.items.add(file);
        fi.files = dt.files;
        fi.dispatchEvent(new Event("input", { bubbles: true }));
        fi.dispatchEvent(new Event("change", { bubbles: true }));
        if (fi.files && fi.files.length > 0) {
          fi.classList.add("ai-autofilled-field");
          fi.closest("label, div, section")?.classList.add("ai-upload-highlight");
          attached = true;
        }
      } catch (_err) {
        fi.closest("label, div, section")?.classList.add("ai-upload-highlight");
      }
    }

    if (!attached) {
      triggerBrowserDownload(file, filename || "Tailored_Resume.pdf");
      document
        .querySelectorAll('input[type="file"], .jobs-document-upload__upload-button-container, [data-automation-id="file-upload-drop-zone"]')
        .forEach((el) => el.classList.add("ai-upload-highlight"));
      showToast(`Saved ${filename} — drop it into the highlighted Upload box!`, false);
    } else {
      showToast(`Tailored CV attached: ${filename} (Human review before Submit)`, false);
    }
    return { attached, fileInputCount: fileInputs.length };
  }

  function showToast(msg, isWarning = false) {
    const existing = document.getElementById("tf-ai-toast");
    if (existing) existing.remove();
    const banner = document.createElement("div");
    banner.id = "tf-ai-toast";
    banner.className = `ai-toast-banner${isWarning ? " warning" : ""}`;
    banner.textContent = msg;
    document.body.appendChild(banner);
    setTimeout(() => banner.remove(), 5500);
  }

  function injectFloatingHud() {
    if (document.getElementById("ai-job-assistant-hud") || !document.body) return;

    const hud = document.createElement("div");
    hud.id = "ai-job-assistant-hud";
    hud.className = "minimized";
    hud.innerHTML = `
      <div class="hud-header" id="tf-hud-toggle">
        <div class="hud-title">
          <span class="hud-status-dot" id="tf-hud-dot"></span>
          <span>TalentFlow Copilot</span>
        </div>
        <span style="font-size:11px; color:#94a3b8;" id="tf-hud-chevron">▲</span>
      </div>
      <div class="hud-body">
        <div class="blocker-alert" id="tf-hud-warn" style="display:none;"></div>
        <div class="hud-meta" id="tf-hud-meta">
          Portal: <b>${detectPortal().toUpperCase()}</b> · Human-in-the-Loop active
        </div>
        <button class="hud-btn-primary" id="tf-hud-fill-btn">Analyze, Build CV & Fill</button>
        <button class="hud-btn-secondary" id="tf-hud-step-btn">Fill Current Modal Step</button>
      </div>
    `;
    document.body.appendChild(hud);

    document.getElementById("tf-hud-toggle")?.addEventListener("click", () => {
      hud.classList.toggle("minimized");
      const chev = document.getElementById("tf-hud-chevron");
      if (chev) chev.textContent = hud.classList.contains("minimized") ? "▲" : "▼";
    });

    async function runHudFill(useLastCvOnly) {
      const cap = detectCaptcha();
      const warnEl = document.getElementById("tf-hud-warn");
      const metaEl = document.getElementById("tf-hud-meta");
      if (cap.detected) {
        if (warnEl) {
          warnEl.style.display = "block";
          warnEl.textContent = cap.reason;
        }
        showToast(cap.reason, true);
        return;
      }
      if (warnEl) warnEl.style.display = "none";

      const ctx = extractJobContext();
      const fields = scanFormFields();
      if (metaEl) metaEl.textContent = `Analyzing ${fields.length} form controls...`;

      chrome.runtime.sendMessage(
        { type: "PREPARE_APPLICATION", payload: { ...ctx, fields } },
        (res) => {
          if (!res || !res.ok) {
            const errMsg = res?.error || "Open the extension popup to sign in first.";
            if (warnEl) {
              warnEl.style.display = "block";
              warnEl.textContent = errMsg;
            }
            showToast(errMsg, true);
            return;
          }
          const data = res.data;
          if (data.seniority_blocked && warnEl) {
            warnEl.style.display = "block";
            warnEl.textContent = `Warning: ${data.seniority_warning}`;
          }
          const applied = applyFieldAnswers(data.field_answers || []);
          if (metaEl) {
            metaEl.textContent = `${data.job_title} (${data.match_score}% ${data.match_tier}) · Filled ${applied.filledCount} fields`;
          }
          if (!useLastCvOnly && data.tailored_cv?.pdf_url) {
            chrome.runtime.sendMessage(
              { type: "FETCH_CV_BLOB", pdfUrl: data.tailored_cv.pdf_url },
              (pdfRes) => {
                if (pdfRes?.ok && pdfRes.base64) {
                  attachResumePdf(pdfRes.base64, data.tailored_cv.pdf_filename || pdfRes.filename);
                } else {
                  showToast(`Filled ${applied.filledCount} fields — please verify before Submit.`, false);
                }
              }
            );
          } else {
            showToast(`Step filled (${applied.filledCount} fields) — review before clicking Next/Submit.`, false);
          }
        }
      );
    }

    document.getElementById("tf-hud-fill-btn")?.addEventListener("click", () => runHudFill(false));
    document.getElementById("tf-hud-step-btn")?.addEventListener("click", () => runHudFill(true));
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    const action = msg?.type || msg?.action;

    if (action === "SCRAPE_CONTEXT") {
      const captcha = detectCaptcha();
      const context = extractJobContext();
      const fields = scanFormFields();
      sendResponse({ ok: true, captcha, context, fields });
      return false;
    }

    if (action === "APPLY_FIELD_ANSWERS") {
      const captcha = detectCaptcha();
      if (captcha.detected) {
        sendResponse({ ok: false, captcha, error: captcha.reason });
        return false;
      }
      const res = applyFieldAnswers(msg.fieldAnswers || []);
      showToast(`Auto-filled ${res.filledCount} form fields — review before submitting.`, false);
      sendResponse({ ok: true, ...res });
      return false;
    }

    if (action === "ATTACH_PDF") {
      const res = attachResumePdf(msg.base64, msg.filename);
      sendResponse({ ok: true, ...res });
      return false;
    }

    return false;
  });

  function debounce(fn, waitMs = 350) {
    let timerId = null;
    return (...args) => {
      if (timerId) clearTimeout(timerId);
      timerId = setTimeout(() => {
        timerId = null;
        fn(...args);
      }, waitMs);
    };
  }

  let __domObserver = null;

  function initDebouncedDomObserver() {
    if (__domObserver || !document.body) return;

    const handleDomChange = debounce(() => {
      const portal = detectPortal();
      const fields = scanFormFields();
      const metaEl = document.getElementById("tf-hud-meta");
      if (metaEl && !metaEl.dataset.locked) {
        metaEl.innerHTML = `Portal: <b>${portal.toUpperCase()}</b> · ${fields.length} controls ready`;
      }
    }, 350);

    __domObserver = new MutationObserver((mutations) => {
      const relevant = mutations.some((m) => {
        const targetEl = m.target instanceof Element ? m.target : m.target?.parentElement;
        return !targetEl?.closest("#ai-job-assistant-hud, #tf-ai-toast");
      });
      if (relevant) {
        handleDomChange();
      }
    });

    __domObserver.observe(document.body, { childList: true, subtree: true });
  }

  function initWebAuthBridge() {
    window.addEventListener("message", (event) => {
      if (event.source !== window || event.origin !== window.location.origin) return;
      const data = event.data;
      if (!data || typeof data !== "object") return;
      if (data.type === "TALENTFLOW_AUTH_SYNC") {
        chrome.runtime.sendMessage({
          type: "SYNC_WEB_AUTH",
          token: data.token || "",
          refreshToken: data.refreshToken || "",
          apiBaseUrl: data.apiBaseUrl || "",
          userEmail: data.userEmail || "",
          userName: data.userName || "",
        });
      } else if (data.type === "TALENTFLOW_AUTH_LOGOUT") {
        chrome.runtime.sendMessage({ type: "SYNC_WEB_LOGOUT" });
      }
    });
  }

  function bootstrapContentScript() {
    initWebAuthBridge();
    injectFloatingHud();
    initDebouncedDomObserver();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrapContentScript);
  } else {
    bootstrapContentScript();
  }
})();
