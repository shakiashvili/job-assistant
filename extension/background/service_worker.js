const DEFAULT_API_BASE = "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 45000;

// Configure Chrome Side Panel to dock beside web pages (LinkedIn Easy Apply, Workday, jobs.ge, etc.)
if (chrome.sidePanel && typeof chrome.sidePanel.setPanelBehavior === "function") {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((error) => console.debug("sidePanel.setPanelBehavior note:", error));
}

async function getConfig() {
  const [syncData, localData] = await Promise.all([
    chrome.storage.sync.get(["apiBaseUrl", "webAppUrl"]),
    chrome.storage.local.get([
      "apiBaseUrl",
      "webAppUrl",
      "jwtToken",
      "refreshToken",
      "userEmail",
      "userName",
      "lastPreparedApp",
    ]),
  ]);
  const rawUrl = syncData.apiBaseUrl || localData.apiBaseUrl || DEFAULT_API_BASE;
  const rawWebUrl = syncData.webAppUrl || localData.webAppUrl || "";
  return {
    apiBaseUrl: rawUrl.replace(/\/+$/, ""),
    webAppUrl: rawWebUrl.replace(/\/+$/, ""),
    jwtToken: localData.jwtToken || "",
    refreshToken: localData.refreshToken || "",
    userEmail: localData.userEmail || "",
    userName: localData.userName || "",
    lastPreparedApp: localData.lastPreparedApp || null,
  };
}

async function fetchWithTimeout(url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timerId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timerId);
  }
}

async function tryRefreshSession(cfg) {
  if (!cfg.refreshToken) return null;
  try {
    const resp = await fetchWithTimeout(`${cfg.apiBaseUrl}/api/auth/refresh`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Client-Type": "chrome-extension",
      },
      body: JSON.stringify({ refresh_token: cfg.refreshToken }),
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    if (data?.access_token) {
      await chrome.storage.local.set({
        jwtToken: data.access_token,
        refreshToken: data.refresh_token || cfg.refreshToken,
      });
      return data.access_token;
    }
  } catch {
    return null;
  }
  return null;
}

async function ensureActiveToken(cfg) {
  if (cfg.jwtToken) return cfg.jwtToken;
  if (cfg.refreshToken) return tryRefreshSession(cfg);
  return "";
}

async function apiRequest(path, { method = "GET", body = null, requiresAuth = true } = {}) {
  const cfg = await getConfig();
  const activeToken = requiresAuth ? await ensureActiveToken(cfg) : cfg.jwtToken;
  if (requiresAuth && !activeToken) {
    return {
      ok: false,
      status: 401,
      error: "Please sign in with your TalentFlow account in the extension first.",
    };
  }

  const execute = (token) => {
    const headers = {
      "Content-Type": "application/json",
      "X-Client-Type": "chrome-extension",
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return fetchWithTimeout(`${cfg.apiBaseUrl}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  };

  try {
    let resp = await execute(activeToken);
    if (resp.status === 401 && requiresAuth && path !== "/api/auth/refresh") {
      const nextToken = await tryRefreshSession(cfg);
      if (nextToken) resp = await execute(nextToken);
    }

    const text = await resp.text();
    let parsed = {};
    try {
      parsed = text ? JSON.parse(text) : {};
    } catch {
      parsed = { raw: text };
    }

    if (resp.status === 401 && requiresAuth) {
      await chrome.storage.local.remove(["jwtToken", "refreshToken", "userEmail", "userName"]);
      return {
        ok: false,
        status: 401,
        error: parsed?.detail || "Session expired. Please sign in again.",
      };
    }

    if (!resp.ok) {
      return {
        ok: false,
        status: resp.status,
        error: parsed?.detail || `API Error HTTP ${resp.status}`,
        data: parsed,
      };
    }
    return { ok: true, status: resp.status, data: parsed };
  } catch (err) {
    if (err?.name === "AbortError") {
      return {
        ok: false,
        status: 504,
        code: "BACKEND_TIMEOUT",
        error: `Backend timed out after ${REQUEST_TIMEOUT_MS / 1000}s (${cfg.apiBaseUrl}).`,
      };
    }
    return {
      ok: false,
      status: 0,
      code: "BACKEND_UNREACHABLE",
      error: `Backend unreachable at ${cfg.apiBaseUrl}. Verify the server is running or update Backend URL.`,
    };
  }
}

function resolveExtensionCvUrl(apiBaseUrl, rawFileUrl, filenameHint = "") {
  const raw = String(rawFileUrl || "").trim();
  const extractedName = (filenameHint || raw.split("/").pop()?.split("?")[0] || "").trim();
  if (extractedName && (raw.includes("/api/resumes/generated/") || !raw)) {
    return {
      url: `${apiBaseUrl}/api/extension/download-cv/${encodeURIComponent(extractedName)}`,
      filename: extractedName,
    };
  }
  const fullUrl = raw.startsWith("http") ? raw : `${apiBaseUrl}${raw}`;
  return {
    url: fullUrl,
    filename: extractedName || "Tailored_Resume.pdf",
  };
}

async function fetchCvFileBase64(fileUrl, filenameHint = "") {
  const cfg = await getConfig();
  const activeToken = await ensureActiveToken(cfg);
  if (!activeToken) {
    return { ok: false, status: 401, error: "Please sign in to download your tailored CV." };
  }

  const { url: fullUrl, filename } = resolveExtensionCvUrl(cfg.apiBaseUrl, fileUrl, filenameHint);
  const doFetch = (token) =>
    fetchWithTimeout(fullUrl, {
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Client-Type": "chrome-extension",
      },
    });

  try {
    let resp = await doFetch(activeToken);
    if (resp.status === 401 && cfg.refreshToken) {
      const nextToken = await tryRefreshSession(cfg);
      if (nextToken) resp = await doFetch(nextToken);
    }
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const errJson = await resp.json();
        if (errJson?.detail) detail = `${detail}: ${errJson.detail}`;
      } catch {
        // Non-JSON error body
      }
      return { ok: false, status: resp.status, error: `Failed to download tailored CV (${detail})` };
    }

    const buffer = await resp.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunkSize = 8192;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
    }
    const base64 = btoa(binary);
    const mimeType = filename.toLowerCase().endsWith(".docx")
      ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
      : "application/pdf";
    return { ok: true, base64, filename, fullUrl, mimeType };
  } catch (err) {
    if (err?.name === "AbortError") {
      return { ok: false, error: `CV download timed out after ${REQUEST_TIMEOUT_MS / 1000}s.` };
    }
    return { ok: false, error: `CV fetch error: ${err?.message || String(err)}` };
  }
}

async function downloadCvFile(fileUrl, filenameHint = "") {
  const fetched = await fetchCvFileBase64(fileUrl, filenameHint);
  if (!fetched.ok || !fetched.base64) {
    return fetched;
  }

  const safeFilename = (fetched.filename || "Tailored_Resume.pdf").replace(/[<>:"/\\|?*]+/g, "_");
  if (!chrome.downloads || typeof chrome.downloads.download !== "function") {
    return { ...fetched, fallbackRequired: true };
  }

  const dataUrl = `data:${fetched.mimeType};base64,${fetched.base64}`;
  return new Promise((resolve) => {
    chrome.downloads.download(
      { url: dataUrl, filename: safeFilename, conflictAction: "uniquify", saveAs: false },
      (downloadId) => {
        if (chrome.runtime.lastError || !downloadId) {
          resolve({
            ok: false,
            error: chrome.runtime.lastError?.message || "Chrome download failed.",
            base64: fetched.base64,
            filename: safeFilename,
            mimeType: fetched.mimeType,
            fallbackRequired: true,
          });
          return;
        }
        resolve({ ok: true, downloadId, filename: safeFilename, mimeType: fetched.mimeType });
      }
    );
  });
}

async function syncFromOpenWebTab() {
  const cfg = await getConfig();
  const allowedOrigins = new Set([
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
  ]);
  for (const candidateUrl of [cfg.webAppUrl, cfg.apiBaseUrl]) {
    if (candidateUrl) {
      try {
        allowedOrigins.add(new URL(candidateUrl).origin);
      } catch {
        // Ignore malformed custom URL
      }
    }
  }
  const tabs = await chrome.tabs.query({});
  const webTab = tabs.find((t) => {
    if (!t.url) return false;
    try {
      return allowedOrigins.has(new URL(t.url).origin);
    } catch {
      return false;
    }
  });
  if (!webTab?.id) {
    return {
      ok: false,
      error: "Open the TalentFlow Web Portal in a browser tab first, or sign in with email & password.",
    };
  }
  const results = await chrome.scripting.executeScript({
    target: { tabId: webTab.id },
    func: () => ({
      token: localStorage.getItem("talentflow_token") || "",
      userRaw: localStorage.getItem("talentflow_user") || "",
    }),
  });
  const extracted = results?.[0]?.result;
  if (!extracted?.token) {
    return {
      ok: false,
      error: "No active login token found in the open Web Portal tab. Please sign in on the web portal first.",
    };
  }
  let parsedUser = {};
  try {
    parsedUser = extracted.userRaw ? JSON.parse(extracted.userRaw) : {};
  } catch {
    parsedUser = {};
  }
  await chrome.storage.local.set({
    jwtToken: extracted.token,
    userEmail: parsedUser.email || "",
    userName: parsedUser.full_name || "",
  });
  const prof = await apiRequest("/api/extension/profile", { method: "GET", requiresAuth: true });
  return {
    ok: true,
    authenticated: true,
    profile: prof.ok ? prof.data : null,
  };
}

/**
 * Wraps every async MV3 message handler so sendResponse is ALWAYS called,
 * preventing "message channel closed before a response was received".
 */
function runAsync(handler, sendResponse) {
  let responded = false;
  const safeRespond = (payload) => {
    if (responded) return;
    responded = true;
    try {
      sendResponse(payload);
    } catch (err) {
      console.debug("sendResponse skipped (channel already closed):", err);
    }
  };
  Promise.resolve()
    .then(handler)
    .then((result) => safeRespond(result))
    .catch((err) => safeRespond({ ok: false, error: err?.message || String(err) }));
  return true;
}

const MESSAGE_HANDLERS = {
  PING: () => apiRequest("/api/health", { requiresAuth: false }),
  CHECK_HEALTH: () => apiRequest("/api/health", { requiresAuth: false }),

  GET_AUTH_STATE: async () => {
    const cfg = await getConfig();
    const token = await ensureActiveToken(cfg);
    if (!token) {
      return { ok: true, authenticated: false, apiBaseUrl: cfg.apiBaseUrl, profile: null };
    }
    const profRes = await apiRequest("/api/extension/profile", { requiresAuth: true });
    if (!profRes.ok) {
      return { ok: true, authenticated: false, apiBaseUrl: cfg.apiBaseUrl, profile: null, error: profRes.error };
    }
    return {
      ok: true,
      authenticated: true,
      apiBaseUrl: cfg.apiBaseUrl,
      userEmail: cfg.userEmail || profRes.data?.user_email || "",
      profile: profRes.data,
    };
  },

  SET_API_BASE: async (message) => {
    const cleanUrl = (message.apiBaseUrl || DEFAULT_API_BASE).replace(/\/+$/, "");
    await chrome.storage.sync.set({ apiBaseUrl: cleanUrl });
    await chrome.storage.local.set({ apiBaseUrl: cleanUrl });
    return { ok: true, apiBaseUrl: cleanUrl };
  },

  LOGIN: async (message) => {
    const res = await apiRequest("/api/auth/login", {
      method: "POST",
      body: { email: message.email, password: message.password },
      requiresAuth: false,
    });
    if (!res.ok) return res;
    const user = res.data?.user || {};
    await chrome.storage.local.set({
      jwtToken: res.data?.access_token || "",
      refreshToken: res.data?.refresh_token || "",
      userEmail: user.email || message.email,
      userName: user.full_name || "Candidate",
    });
    const profRes = await apiRequest("/api/extension/profile", { requiresAuth: true });
    return { ok: true, authenticated: true, user, profile: profRes.ok ? profRes.data : null };
  },

  SET_TOKEN: async (message) => {
    const token = (message.token || "").trim();
    if (!token) return { ok: false, error: "Empty token supplied." };
    await chrome.storage.local.set({ jwtToken: token });
    const profRes = await apiRequest("/api/extension/profile", { requiresAuth: true });
    if (!profRes.ok) return profRes;
    await chrome.storage.local.set({
      userEmail: profRes.data?.user_email || "",
      userName: profRes.data?.full_name || "Candidate",
    });
    return { ok: true, authenticated: true, profile: profRes.data };
  },

  SYNC_WEB_AUTH: async (message) => {
    const token = (message.token || "").trim();
    const refreshToken = (message.refreshToken || "").trim();
    if (!token && !refreshToken) return { ok: false };
    await chrome.storage.local.set({
      jwtToken: token,
      refreshToken,
      userEmail: message.userEmail || "",
      userName: message.userName || "Candidate",
    });
    const rawBase = (message.apiBaseUrl || "").trim().replace(/\/+$/, "");
    if (
      rawBase &&
      (/^https:\/\/[a-z0-9.-]+(:\d+)?$/i.test(rawBase) ||
        /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(rawBase))
    ) {
      await chrome.storage.sync.set({ apiBaseUrl: rawBase });
    }
    return { ok: true, synced: true };
  },

  LOGOUT: async () => {
    await chrome.storage.local.remove(["jwtToken", "refreshToken", "userEmail", "userName", "lastPreparedApp"]);
    return { ok: true, authenticated: false };
  },
  SYNC_WEB_LOGOUT: async () => {
    await chrome.storage.local.remove(["jwtToken", "refreshToken", "userEmail", "userName", "lastPreparedApp"]);
    return { ok: true, authenticated: false };
  },

  PREPARE_APPLICATION: async (message) => {
    const res = await apiRequest("/api/extension/prepare-application", {
      method: "POST",
      body: message.payload,
      requiresAuth: true,
    });
    if (res.ok && res.data) {
      await chrome.storage.local.set({ lastPreparedApp: res.data });
    }
    return res;
  },

  UPLOAD_SKILLS_MD: async (message) => {
    const payload = { filename: message.filename || "skills.md" };
    if (message.contentBase64) payload.content_base64 = message.contentBase64;
    else payload.content = message.content || "";
    const res = await apiRequest("/api/extension/upload-skills", {
      method: "POST",
      body: payload,
      requiresAuth: true,
    });
    if (res.ok && res.data?.user_email) {
      await chrome.storage.local.set({
        userEmail: res.data.user_email,
        userName: res.data.full_name || "Candidate",
      });
    }
    return res;
  },

  FETCH_CV_BLOB: (message) =>
    fetchCvFileBase64(message.pdfUrl || message.fileUrl || "", message.filename || ""),

  DOWNLOAD_CV_FILE: (message) =>
    downloadCvFile(message.fileUrl || message.pdfUrl || "", message.filename || ""),

  LOG_APPLICATION: (message) =>
    apiRequest("/api/extension/log-application", {
      method: "POST",
      body: message.payload,
      requiresAuth: true,
    }),

  SYNC_FROM_OPEN_WEB_TAB: () => syncFromOpenWebTab(),
};

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.get(["apiBaseUrl"], (res) => {
    if (!res.apiBaseUrl) {
      chrome.storage.sync.set({ apiBaseUrl: DEFAULT_API_BASE });
    }
  });
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const type = message?.type || message?.action;
  const handler = MESSAGE_HANDLERS[type];
  if (!handler) {
    sendResponse({ ok: false, error: `Unknown message type: ${type}` });
    return false;
  }
  return runAsync(() => handler(message), sendResponse);
});
