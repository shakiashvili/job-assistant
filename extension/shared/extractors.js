/**
 * Shared, pure DOM job-context & portal extractors for TalentFlow AI Extension.
 * Works both in Chrome MV3 content scripts (attaches to globalThis.TalentFlowExtractors)
 * and in Node/Vitest unit tests (CommonJS module.exports).
 */
(function initExtractors(rootScope) {
  const GENERIC_PORTAL_NAMES = new Set([
    "dou", "dou.ua", "djinni", "djinni.co", "jobs", "jobs.ge", "hr", "hr.ge", "hr.gov.ge",
    "headhunter", "headhunter.ge", "linkedin", "linkedin.com", "workday", "greenhouse",
    "lever", "ashby", "workable", "indeed", "glassdoor",
  ]);

  function cleanText(el) {
    return el ? (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim() : "";
  }

  function firstText(selectors, doc) {
    for (const sel of selectors) {
      const el = doc.querySelector(sel);
      const txt = cleanText(el);
      if (txt) return txt;
    }
    return "";
  }

  function detectPortalFromUrl(hostname, href) {
    const host = (hostname || "").toLowerCase();
    const url = (href || "").toLowerCase();
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
    if (host.includes("jobs.ge") || url.includes("jobs.ge")) return "jobs.ge";
    if (host.includes("headhunter.ge")) return "headhunter.ge";
    if (host.includes("hr.ge")) return "hr.ge";
    if (host.includes("justjoin.it")) return "justjoin.it";
    return "generic";
  }

  function extractContactEmail(doc, rawPageText) {
    const mailtoHref = doc.querySelector('a[href^="mailto:"]')?.getAttribute("href") || "";
    const mailtoAddr = mailtoHref.replace(/^mailto:/i, "").split("?")[0].trim();
    if (mailtoAddr && mailtoAddr.includes("@")) return mailtoAddr;
    const match = (rawPageText || "").match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/);
    return match ? match[0] : "";
  }

  function extractJobContextFromDocument(doc, loc) {
    const locationObj = loc || (typeof window !== "undefined" ? window.location : { hostname: "", href: "" });
    const portal = detectPortalFromUrl(locationObj.hostname, locationObj.href);
    const bodyText = doc.body?.innerText || doc.body?.textContent || "";

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
      ], doc);
      const applyHdr = firstText(["#jobs-apply-header", ".jobs-easy-apply-modal h2"], doc);
      companyName = firstText([
        ".job-details-jobs-unified-top-card__company-name a",
        ".job-details-jobs-unified-top-card__company-name",
        ".jobs-unified-top-card__company-name a",
        ".jobs-unified-top-card__company-name",
        ".topcard__org-name-link",
      ], doc);
      if (!companyName && applyHdr && /^apply to\s+/i.test(applyHdr)) {
        companyName = applyHdr.replace(/^apply to\s+/i, "").trim();
      }
      location = firstText([
        ".job-details-jobs-unified-top-card__primary-description-container .tvm__text",
        ".jobs-unified-top-card__bullet",
        ".topcard__flavor--bullet",
      ], doc);
      jobDescription = firstText([
        "#job-details",
        ".jobs-description__content",
        ".jobs-description-content__text",
        ".show-more-less-html__markup",
      ], doc);
    } else if (portal === "workday") {
      jobTitle = firstText(['[data-automation-id="jobPostingHeader"] h2', '[data-automation-id="jobPostingHeader"]', "h1", "h2"], doc);
      const metaSite = doc.querySelector('meta[property="og:site_name"]')?.getAttribute("content") || "";
      const subHost = (locationObj.hostname || "").split(".")[0] || "";
      companyName = metaSite || (subHost && !subHost.startsWith("wd") ? subHost : "");
      location = firstText(['[data-automation-id="locations"] dd', '[data-automation-id="locations"]'], doc);
      jobDescription = firstText(['[data-automation-id="jobPostingDescription"]'], doc);
    } else if (portal === "greenhouse" || portal === "lever") {
      jobTitle = firstText(["h1.app-title", ".posting-headline h2", "h1"], doc);
      companyName = firstText([".company-name", ".main-header-logo img[alt]"], doc) ||
        (doc.querySelector('meta[property="og:site_name"]')?.getAttribute("content") || "");
      location = firstText([".location", ".posting-categories .location"], doc);
      jobDescription = firstText(["#content", ".posting-page", ".section-wrapper"], doc);
    } else if (portal === "dou.ua") {
      jobTitle = firstText(["h1.g-h2", ".b-vacancy h1", "h1"], doc);
      companyName = firstText([".b-compinfo .l-n a", ".b-compinfo .l-n", ".comp-name a", ".company-name"], doc);
      location = firstText([".place", ".b-vacancy .place", ".location"], doc);
      jobDescription = firstText([".b-typo.vacancy-section", ".b-vacancy", "article", "main"], doc);
    } else if (portal === "djinni.co") {
      jobTitle = firstText(["header h1", "h1"], doc);
      companyName = firstText([".job-details--title a", "a.text-reset[href*='/jobs/company-']", ".company-name"], doc);
      location = firstText([".location-text", ".job-additional-info--item"], doc);
      jobDescription = firstText([".job-post__description", ".profile-page-section", "main"], doc);
    } else if (portal === "jobs.ge") {
      jobTitle =
        firstText(["td.dtitle", "#job_view h1", "#job_view h2", ".dtitle", "table.dtable b"], doc) ||
        (bodyText.match(/(?:დასახელება|Title)\s*:\s*([^\n]{3,120})/i)?.[1] || "").trim();
      if (!jobTitle) {
        const headings = Array.from(doc.querySelectorAll("h1, h2, h3, td b, p b"))
          .map((n) => cleanText(n))
          .filter((t) => t.length >= 4 && t.length <= 120 && !/^jobs\.?ge$/i.test(t) && !/ვაკანსიები|ტრენინგები|სტიპენდიები/i.test(t));
        jobTitle = headings[0] || "";
      }
      const provMatch = bodyText.match(/(?:მომწოდებელი|Provider)\s*:\s*([^\n]{2,100})/i);
      companyName =
        (provMatch ? provMatch[1].trim() : "") ||
        firstText(['a[href*="cid="][href*="client"]', 'a[href*="view=client"]', ".client_name"], doc);
      location = (bodyText.match(/(?:ადგილმდებარეობა|Location)\s*:\s*([^\n]{2,80})/i)?.[1] || "Georgia").trim();
      jobDescription = firstText(["#job_view", "table.dtable", "#content", "main"], doc) || bodyText;
    } else if (portal === "hr.ge") {
      jobTitle = firstText(["h1.vacancy-title", "h1", ".announcement-title", "h2"], doc);
      companyName = firstText(['a[href*="/company/"]', ".company-name", ".employer-title"], doc);
      location = firstText([".location", ".city", '[class*="location"]'], doc) || "Georgia";
      jobDescription = firstText([".vacancy-description", ".description", "article", "main"], doc);
    } else if (portal === "headhunter.ge") {
      jobTitle = firstText(['[data-qa="vacancy-title"]', "h1.bloko-header-section-1", "h1"], doc);
      companyName = firstText(['[data-qa="vacancy-company-name"]', ".vacancy-company-name"], doc);
      location = firstText(['[data-qa="vacancy-view-location"]', '[data-qa="vacancy-view-raw-address"]'], doc) || "Georgia";
      jobDescription = firstText(['[data-qa="vacancy-description"]', ".vacancy-description", "main"], doc);
    } else if (portal === "hr.gov.ge") {
      jobTitle = firstText(["h1", ".vacancy-title", ".job-title"], doc);
      companyName = firstText([".organization-name", ".agency-name", ".company-name"], doc);
      location = "Georgia";
      jobDescription = firstText([".vacancy-details", ".description", "main"], doc);
    } else {
      const rawTitle = firstText(["h1.job-title", "h1", ".vacancy-title", ".job-header h2", "h2"], doc);
      jobTitle = rawTitle && !GENERIC_PORTAL_NAMES.has(rawTitle.toLowerCase()) ? rawTitle : "";
      if (!jobTitle) {
        const ogTitle = (doc.querySelector('meta[property="og:title"]')?.getAttribute("content") || "").trim();
        const fallbackT = ogTitle ? ogTitle.split(/\s[|\-–—]\s/)[0].trim() : (doc.title || "").split(/\s[|\-–—]\s/)[0].trim();
        if (fallbackT && !GENERIC_PORTAL_NAMES.has(fallbackT.toLowerCase())) {
          jobTitle = fallbackT;
        }
      }
      const metaSite = (doc.querySelector('meta[property="og:site_name"]')?.getAttribute("content") || "").trim();
      const hostParts = (locationObj.hostname || "")
        .replace(/^(www|careers|jobs|apply|boards|hire)\./i, "")
        .split(".");
      const hostCompany = hostParts[0] && hostParts[0].length > 1
        ? hostParts[0].charAt(0).toUpperCase() + hostParts[0].slice(1)
        : "";
      companyName =
        firstText([".company-name", ".employer-name", '[itemprop="hiringOrganization"]'], doc) ||
        (metaSite && !GENERIC_PORTAL_NAMES.has(metaSite.toLowerCase()) ? metaSite : "") ||
        (!GENERIC_PORTAL_NAMES.has((hostCompany || "").toLowerCase()) ? hostCompany : "");
      jobDescription = firstText(["main", "article", ".job-description", ".description", "#job-description", "[role='main']"], doc);
    }

    if (GENERIC_PORTAL_NAMES.has(jobTitle.toLowerCase())) jobTitle = "";
    if (GENERIC_PORTAL_NAMES.has(companyName.toLowerCase())) companyName = "";

    const rawPageText = bodyText.replace(/\s+/g, " ").trim().slice(0, 6000);
    return {
      url: locationObj.href || "",
      portal,
      job_title: jobTitle,
      company_name: companyName.replace(/^at\s+/i, "").trim(),
      location,
      contact_email: extractContactEmail(doc, rawPageText),
      job_description: (jobDescription || rawPageText).slice(0, 5000),
      raw_page_text: rawPageText,
    };
  }

  const exported = {
    GENERIC_PORTAL_NAMES,
    cleanText,
    firstText,
    detectPortalFromUrl,
    extractContactEmail,
    extractJobContextFromDocument,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = exported;
  }
  if (rootScope) {
    rootScope.TalentFlowExtractors = exported;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
