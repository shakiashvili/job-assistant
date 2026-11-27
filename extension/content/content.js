(() => {
  if (window.__talentFlowCopilotLoaded) return;
  window.__talentFlowCopilotLoaded = true;

  function detectPortal() {
    const host = (window.location.hostname || "").toLowerCase();
    const url = (window.location.href || "").toLowerCase();
    if (host.includes("linkedin.com")) return "linkedin.com";
    if (host.includes("myworkdayjobs.com")) return "workday";
    if (host.includes("greenhouse.io")) return "greenhouse";
    if (host.includes("lever.co")) return "lever";
    if (host.includes("djinni.co")) return "djinni.co";
    if (host.includes("dou.ua")) return "dou.ua";
    if (host.includes("remotive.com")) return "remotive.com";
    if (host.includes("himalayas.app")) return "himalayas.app";
    if (host.includes("remoteok.com")) return "remoteok.com";
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
    } else if (portal === "jobs.ge") {
      // Dedicated jobs.ge extractor: avoids picking site banner "Jobs.GE" / hostname "Jobs"
      const bodyText = document.body?.innerText || "";
      jobTitle =
        firstText(["td.dtitle", "#job_view h1", "#job_view h2", ".dtitle", "table.dtable b"]) ||
        (bodyText.match(/(?:დასახელება|Title)\s*:\s*([^\n]{3,120})/i)?.[1] || "").trim();
      if (!jobTitle) {
        // First prominent bold heading above "მომწოდებელი:" in the job container
        const headings = Array.from(document.querySelectorAll("h1, h2, h3, td b, p b"))
          .map((n) => cleanText(n))
          .filter((t) => t.length >= 4 && t.length <= 120 && !/^jobs\.?ge$/i.test(t) && !/ვაკანსიები|ტრენინგები|სტიპენდიები/i.test(t));
        jobTitle = headings[0] || "";
      }
      const provMatch = bodyText.match(/(?:მომწოდებელი|Provider)\s*:\s*([^\n]{2,100})/i);
      companyName =
        (provMatch ? provMatch[1].trim() : "") ||
        firstText(['a[href*="cid="][href*="client"]', 'a[href*="view=client"]', ".client_name"]);
      location = (bodyText.match(/(?:ადგილმდებარეობა|Location)\s*:\s*([^\n]{2,80})/i)?.[1] || "Georgia").trim();
      jobDescription = firstText(["#job_view", "table.dtable", "#content", "main"]) || bodyText;
    } else if (portal === "hr.ge") {
      jobTitle = firstText(["h1.vacancy-title", "h1", ".announcement-title", "h2"]);
      companyName = firstText(['a[href*="/company/"]', ".company-name", ".employer-title"]);
      location = firstText([".location", ".city", '[class*="location"]']) || "Georgia";
      jobDescription = firstText([".vacancy-description", ".description", "article", "main"]);
    } else if (portal === "headhunter.ge") {
      jobTitle = firstText(['[data-qa="vacancy-title"]', "h1.bloko-header-section-1", "h1"]);
      companyName = firstText(['[data-qa="vacancy-company-name"]', ".vacancy-company-name"]);
      location = firstText(['[data-qa="vacancy-view-location"]', '[data-qa="vacancy-view-raw-address"]']) || "Georgia";
      jobDescription = firstText(['[data-qa="vacancy-description"]', ".vacancy-description", "main"]);
    } else if (portal === "hr.gov.ge") {
      jobTitle = firstText(["h1", ".vacancy-title", ".job-title"]);
      companyName = firstText([".organization-name", ".agency-name", ".company-name"]);
      location = "Georgia";
      jobDescription = firstText([".vacancy-details", ".description", "main"]);
    } else {
      const genericPortalSites = new Set([
        "dou", "dou.ua", "djinni", "djinni.co", "jobs", "jobs.ge", "hr", "hr.ge", "hr.gov.ge",
        "headhunter", "headhunter.ge", "linkedin", "workday", "greenhouse", "lever",
        "ashby", "workable", "indeed", "glassdoor"
      ]);
      const rawTitle = firstText(["h1.job-title", "h1", ".vacancy-title", ".job-header h2", "h2"]);
      jobTitle = rawTitle && !genericPortalSites.has(rawTitle.toLowerCase()) ? rawTitle : "";
      if (!jobTitle) {
        const ogTitle = (document.querySelector('meta[property="og:title"]')?.getAttribute("content") || "").trim();
        const fallbackT = ogTitle ? ogTitle.split(/\s[|\-–—]\s/)[0].trim() : (document.title || "").split(/\s[|\-–—]\s/)[0].trim();
        if (fallbackT && !genericPortalSites.has(fallbackT.toLowerCase())) {
          jobTitle = fallbackT;
        }
      }
      const metaSite = (document.querySelector('meta[property="og:site_name"]')?.getAttribute("content") || "").trim();
      const hostParts = (window.location.hostname || "")
        .replace(/^(www|careers|jobs|apply|boards|hire)\./i, "")
        .split(".");
      const hostCompany = hostParts[0] && hostParts[0].length > 1
        ? hostParts[0].charAt(0).toUpperCase() + hostParts[0].slice(1)
        : "";
      companyName =
        firstText([".company-name", ".employer-name", '[itemprop="hiringOrganization"]']) ||
        (metaSite && !genericPortalSites.has(metaSite.toLowerCase()) ? metaSite : "") ||
        (!genericPortalSites.has((hostCompany || "").toLowerCase()) ? hostCompany : "");
      jobDescription = firstText(["main", "article", ".job-description", ".description", "#job-description", "[role='main']"]);
    }

    const rawPageText = (document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 6000);
    const mailtoHref = document.querySelector('a[href^="mailto:"]')?.getAttribute("href") || "";
    const mailtoAddr = mailtoHref.replace(/^mailto:/i, "").split("?")[0].trim();
    const bodyEmailMatch = rawPageText.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/);
    const contactEmail = mailtoAddr || (bodyEmailMatch ? bodyEmailMatch[0] : "");

    return {
      url: window.location.href,
      portal,
      job_title: jobTitle,
      company_name: companyName.replace(/^at\s+/i, "").trim(),
      location,
      contact_email: contactEmail,
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

  let nextFieldSeq = 0;

  function scanFormFields() {
    const root = getActiveFormRoot();
    if (!root) return [];

    const fields = [];
    const seenRadioNames = new Set();

    // 1. Fieldset / radio groups first
    const radios = root.querySelectorAll('input[type="radio"]');
    for (const r of radios) {
      const rName = r.getAttribute("name") || "";
      if (!rName || seenRadioNames.has(rName)) continue;
      seenRadioNames.add(rName);
      const groupRadios = Array.from(root.querySelectorAll(`input[type="radio"][name="${CSS.escape(rName)}"]`));
      if (!groupRadios.some(isVisible)) continue;

      const fieldId = r.getAttribute("data-tf-field-id") || `tf-field-${nextFieldSeq++}`;
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

    // 2. Inputs, textareas, selects, and SPA contenteditable textboxes
    const controls = root.querySelectorAll(
      'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="reset"]):not([type="radio"]), textarea, select, [role="textbox"][contenteditable="true"]'
    );
    for (const el of controls) {
      if (!isVisible(el)) continue;
      const tag = el.tagName.toLowerCase();
      const isRichTextbox = tag !== "input" && tag !== "textarea" && tag !== "select";
      const inputType = isRichTextbox
        ? "textarea"
        : tag === "input"
        ? (el.getAttribute("type") || "text").toLowerCase()
        : tag;
      const fieldId = el.getAttribute("data-tf-field-id") || `tf-field-${nextFieldSeq++}`;
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
        placeholder: el.getAttribute("placeholder") || el.getAttribute("aria-placeholder") || null,
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

      if (first.isContentEditable || first.getAttribute("role") === "textbox") {
        first.focus();
        first.innerText = val;
        first.dispatchEvent(new Event("input", { bubbles: true }));
        first.dispatchEvent(new Event("blur", { bubbles: true }));
        first.classList.add("ai-autofilled-field");
        filledCount++;
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
      if (fileInputs.length > 0) {
        triggerBrowserDownload(file, filename || "Tailored_Resume.pdf");
        document
          .querySelectorAll('input[type="file"], .jobs-document-upload__upload-button-container, [data-automation-id="file-upload-drop-zone"]')
          .forEach((el) => el.classList.add("ai-upload-highlight"));
        showToast(`Saved ${filename} — drop it into the highlighted Upload box!`, false);
      } else {
        showToast(`No upload field on this page — use Download PDF / Word in the Side Panel.`, false);
      }
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
        <div style="display:flex; align-items:center; gap:6px;">
          <span style="font-size:11px; color:#94a3b8;" id="tf-hud-chevron">▲</span>
          <button type="button" id="tf-hud-close" title="Hide HUD" style="background:none;border:none;color:#94a3b8;cursor:pointer;font-size:12px;padding:0 2px;">×</button>
        </div>
      </div>
      <div class="hud-body">
        <div class="blocker-alert" id="tf-hud-warn" style="display:none;"></div>
        <div class="hud-meta" id="tf-hud-meta">
          Portal: <b id="tf-hud-portal"></b> · Human-in-the-Loop active
        </div>
        <button class="hud-btn-primary" id="tf-hud-fill-btn">Analyze, Build CV &amp; Fill</button>
        <button class="hud-btn-secondary" id="tf-hud-step-btn">Fill Current Modal Step</button>
        <button class="hud-btn-secondary" id="tf-hud-applied-btn" style="margin-top:4px; border-color:#10b981; color:#6ee7b7;">✅ Mark Applied (Tracker)</button>
      </div>
    `;
    document.body.appendChild(hud);
    const portalBadgeEl = document.getElementById("tf-hud-portal");
    if (portalBadgeEl) portalBadgeEl.textContent = detectPortal().toUpperCase();

    document.getElementById("tf-hud-close")?.addEventListener("click", (e) => {
      e.stopPropagation();
      hud.remove();
    });

    document.getElementById("tf-hud-toggle")?.addEventListener("click", () => {
      hud.classList.toggle("minimized");
      const chev = document.getElementById("tf-hud-chevron");
      if (chev) chev.textContent = hud.classList.contains("minimized") ? "▲" : "▼";
    });

    let lastHudPrepared = null;

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
          if (chrome.runtime.lastError || !res || !res.ok) {
            const errMsg = chrome.runtime.lastError?.message || res?.error || "Open the extension popup to sign in first.";
            if (warnEl) {
              warnEl.style.display = "block";
              warnEl.textContent = errMsg;
            }
            showToast(errMsg, true);
            return;
          }
          const data = res.data;
          lastHudPrepared = { ctx, data };
          if (data.seniority_blocked && warnEl) {
            warnEl.style.display = "block";
            warnEl.textContent = `Warning: ${data.seniority_warning}`;
          }
          const applied = fields.length > 0 ? applyFieldAnswers(data.field_answers || []) : { filledCount: 0 };
          if (metaEl) {
            metaEl.dataset.locked = "true";
            metaEl.textContent = fields.length > 0
              ? `${data.job_title} (${data.match_score}% ${data.match_tier}) · Filled ${applied.filledCount} fields`
              : `${data.job_title} (${data.match_score}% ${data.match_tier}) · CV Ready`;
          }
          const hasFileInput = fields.some((f) => f.field_type === "file");
          if (!useLastCvOnly && data.tailored_cv?.pdf_url) {
            if (hasFileInput) {
              chrome.runtime.sendMessage(
                { type: "FETCH_CV_BLOB", pdfUrl: data.tailored_cv.pdf_url, filename: data.tailored_cv.pdf_filename || "" },
                (pdfRes) => {
                  if (!chrome.runtime.lastError && pdfRes?.ok && pdfRes.base64) {
                    attachResumePdf(pdfRes.base64, data.tailored_cv.pdf_filename || pdfRes.filename);
                  } else {
                    showToast(`Filled ${applied.filledCount} fields — download CV from the Side Panel.`, false);
                  }
                }
              );
            } else {
              chrome.runtime.sendMessage(
                { type: "DOWNLOAD_CV_FILE", fileUrl: data.tailored_cv.pdf_url, filename: data.tailored_cv.pdf_filename || "" },
                (dlRes) => {
                  if (!chrome.runtime.lastError && dlRes?.ok) {
                    showToast(`Tailored PDF downloaded (${dlRes.filename})! Open Side Panel for Word/Cover Letter.`, false);
                  } else {
                    showToast("CV & Cover Letter ready in Side Panel (click Download PDF / Word).", false);
                  }
                }
              );
            }
          } else {
            showToast(
              fields.length > 0
                ? `Step filled (${applied.filledCount} fields) — review before clicking Next/Submit.`
                : "No web form on this page — use the Side Panel to download CV & copy cover letter.",
              false
            );
          }
        }
      );
    }

    document.getElementById("tf-hud-fill-btn")?.addEventListener("click", () => runHudFill(false));
    document.getElementById("tf-hud-step-btn")?.addEventListener("click", () => runHudFill(true));
    document.getElementById("tf-hud-applied-btn")?.addEventListener("click", () => {
      const ctx = lastHudPrepared?.ctx || extractJobContext();
      const data = lastHudPrepared?.data || {};
      chrome.runtime.sendMessage(
        {
          type: "LOG_APPLICATION",
          payload: {
            company_name: data.company_name || ctx.company_name || "Unknown Company",
            job_title: data.job_title || ctx.job_title || "Unknown Title",
            job_url: ctx.url,
            portal: ctx.portal || "custom",
            salary_offered: data.salary_info?.display || null,
            cv_pdf_path: data.tailored_cv?.pdf_url || data.tailored_cv?.pdf_filename || null,
            cover_letter_text: data.cover_letter || null,
            status: "APPLIED",
          },
        },
        (res) => {
          if (!chrome.runtime.lastError && res?.ok) {
            showToast(`Saved "${data.job_title || ctx.job_title}" to your Application Tracker board as Applied!`, false);
          } else {
            showToast(chrome.runtime.lastError?.message || res?.error || "Sign in via Side Panel to save to Tracker.", true);
          }
        }
      );
    });
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
    const host = (window.location.hostname || "").toLowerCase();
    // Skip floating HUD on local TalentFlow web app tabs; scan forms strictly on explicit user click
    if (host !== "localhost" && host !== "127.0.0.1") {
      injectFloatingHud();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrapContentScript);
  } else {
    bootstrapContentScript();
  }
})();
