const DEFAULT_API_BASE = "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 15000;

// Configure Chrome Side Panel to dock beside web pages (LinkedIn Easy Apply, Workday, etc.)
if (chrome.sidePanel && typeof chrome.sidePanel.setPanelBehavior === "function") {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((error) => console.debug("sidePanel.setPanelBehavior note:", error));
}

if (chrome.action && chrome.action.onClicked) {
  chrome.action.onClicked.addListener(async (tab) => {
    if (tab && tab.id && chrome.sidePanel && typeof chrome.sidePanel.open === "function") {
      try {
        await chrome.sidePanel.open({ tabId: tab.id });
      } catch (err) {
        console.debug("sidePanel.open note:", err);
      }
    }
  });
}

async function getConfig() {
  const [syncData, localData] = await Promise.all([
    chrome.storage.sync.get(["apiBaseUrl"]),
    chrome.storage.local.get([
      "apiBaseUrl",
      "jwtToken",
      "refreshToken",
      "userEmail",
      "userName",
      "lastPreparedApp",
    ]),
  ]);
  const rawUrl = syncData.apiBaseUrl || localData.apiBaseUrl || DEFAULT_API_BASE;
  return {
    apiBaseUrl: rawUrl.replace(/\/+$/, ""),
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
      headers: { "Content-Type": "application/json" },
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

async function apiRequest(path, { method = "GET", body = null, requiresAuth = true } = {}) {
  const cfg = await getConfig();
  let activeToken = cfg.jwtToken;
  if (requiresAuth && !activeToken && cfg.refreshToken) {
    activeToken = await tryRefreshSession(cfg);
  }
  if (requiresAuth && !activeToken) {
    return {
      ok: false,
      status: 401,
      error: "Please sign in with your TalentFlow account in the extension first.",
    };
  }

  const execute = (token) => {
    const headers = { "Content-Type": "application/json" };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
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
      if (nextToken) {
        resp = await execute(nextToken);
      }
    }

    const text = await resp.text();
    let parsed = null;
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
        error: `Backend timed out after ${REQUEST_TIMEOUT_MS / 1000}s (${cfg.apiBaseUrl}). Free-tier hosts may be waking up—wait a few seconds and retry.`,
      };
    }
    return {
      ok: false,
      status: 0,
      code: "BACKEND_UNREACHABLE",
      error: `Backend unreachable at ${cfg.apiBaseUrl}. Verify the server is running or update Backend URL in settings.`,
    };
  }
}

async function fetchPdfBase64(pdfUrl) {
  const cfg = await getConfig();
  const fullUrl = pdfUrl.startsWith("http") ? pdfUrl : `${cfg.apiBaseUrl}${pdfUrl}`;
  try {
    const resp = await fetchWithTimeout(fullUrl);
    if (!resp.ok) {
      return { ok: false, error: `Failed to download tailored PDF (HTTP ${resp.status})` };
    }
    const buffer = await resp.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunkSize = 8192;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
    }
    const base64 = btoa(binary);
    const filename = fullUrl.split("/").pop().split("?")[0] || "Tailored_Resume.pdf";
    return { ok: true, base64, filename, fullUrl, mimeType: "application/pdf" };
  } catch (err) {
    if (err?.name === "AbortError") {
      return { ok: false, error: "PDF download timed out after 15s. Please try again." };
    }
    return { ok: false, error: `PDF fetch error: ${err.message}` };
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.get(["apiBaseUrl"], (res) => {
    if (!res.apiBaseUrl) {
      chrome.storage.sync.set({ apiBaseUrl: DEFAULT_API_BASE });
    }
  });
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const type = message?.type || message?.action;

  if (type === "PING" || type === "CHECK_HEALTH") {
    apiRequest("/api/health", { requiresAuth: false }).then(sendResponse);
    return true;
  }

  if (type === "GET_AUTH_STATE") {
    (async () => {
      const cfg = await getConfig();
      if (!cfg.jwtToken) {
        sendResponse({ ok: true, authenticated: false, apiBaseUrl: cfg.apiBaseUrl, profile: null });
        return;
      }
      const profRes = await apiRequest("/api/extension/profile", { requiresAuth: true });
      if (!profRes.ok) {
        sendResponse({ ok: true, authenticated: false, apiBaseUrl: cfg.apiBaseUrl, profile: null, error: profRes.error });
        return;
      }
      sendResponse({
        ok: true,
        authenticated: true,
        apiBaseUrl: cfg.apiBaseUrl,
        userEmail: cfg.userEmail || profRes.data?.user_email || "",
        profile: profRes.data,
      });
    })();
    return true;
  }

  if (type === "SET_API_BASE") {
    const cleanUrl = (message.apiBaseUrl || DEFAULT_API_BASE).replace(/\/+$/, "");
    chrome.storage.sync.set({ apiBaseUrl: cleanUrl }, () => {
      chrome.storage.local.set({ apiBaseUrl: cleanUrl }, () => {
        sendResponse({ ok: true, apiBaseUrl: cleanUrl });
      });
    });
    return true;
  }

  if (type === "LOGIN") {
    (async () => {
      const res = await apiRequest("/api/auth/login", {
        method: "POST",
        body: { email: message.email, password: message.password },
        requiresAuth: false,
      });
      if (!res.ok) {
        sendResponse(res);
        return;
      }
      const token = res.data?.access_token;
      const refreshToken = res.data?.refresh_token || "";
      const user = res.data?.user || {};
      await chrome.storage.local.set({
        jwtToken: token,
        refreshToken,
        userEmail: user.email || message.email,
        userName: user.full_name || "Candidate",
      });
      const profRes = await apiRequest("/api/extension/profile", { requiresAuth: true });
      sendResponse({
        ok: true,
        authenticated: true,
        user,
        profile: profRes.ok ? profRes.data : null,
      });
    })();
    return true;
  }

  if (type === "SET_TOKEN") {
    (async () => {
      const token = (message.token || "").trim();
      if (!token) {
        sendResponse({ ok: false, error: "Empty token supplied." });
        return;
      }
      await chrome.storage.local.set({ jwtToken: token });
      const profRes = await apiRequest("/api/extension/profile", { requiresAuth: true });
      if (!profRes.ok) {
        sendResponse(profRes);
        return;
      }
      await chrome.storage.local.set({
        userEmail: profRes.data?.user_email || "",
        userName: profRes.data?.full_name || "Candidate",
      });
      sendResponse({ ok: true, authenticated: true, profile: profRes.data });
    })();
    return true;
  }

  if (type === "SYNC_WEB_AUTH") {
    (async () => {
      const token = (message.token || "").trim();
      const refreshToken = (message.refreshToken || "").trim();
      if (!token && !refreshToken) {
        sendResponse({ ok: false });
        return;
      }
      const updates = {
        jwtToken: token,
        refreshToken: refreshToken,
        userEmail: message.userEmail || "",
        userName: message.userName || "Candidate",
      };
      await chrome.storage.local.set(updates);
      const rawBase = (message.apiBaseUrl || "").trim().replace(/\/+$/, "");
      if (rawBase && /^https?:\/\//i.test(rawBase)) {
        await chrome.storage.sync.set({ apiBaseUrl: rawBase });
      }
      sendResponse({ ok: true, synced: true });
    })();
    return true;
  }

  if (type === "LOGOUT" || type === "SYNC_WEB_LOGOUT") {
    chrome.storage.local.remove(["jwtToken", "refreshToken", "userEmail", "userName", "lastPreparedApp"], () => {
      sendResponse({ ok: true, authenticated: false });
    });
    return true;
  }

  if (type === "PREPARE_APPLICATION") {
    (async () => {
      const res = await apiRequest("/api/extension/prepare-application", {
        method: "POST",
        body: message.payload,
        requiresAuth: true,
      });
      if (res.ok && res.data) {
        await chrome.storage.local.set({ lastPreparedApp: res.data });
      }
      sendResponse(res);
    })();
    return true;
  }

  if (type === "UPLOAD_SKILLS_MD") {
    (async () => {
      const res = await apiRequest("/api/extension/upload-skills", {
        method: "POST",
        body: { content: message.content || "", filename: message.filename || "skills.md" },
        requiresAuth: true,
      });
      if (res.ok && res.data?.user_email) {
        await chrome.storage.local.set({
          userEmail: res.data.user_email,
          userName: res.data.full_name || "Candidate",
        });
      }
      sendResponse(res);
    })();
    return true;
  }

  if (type === "ANSWER_QUESTIONS") {
    apiRequest("/api/answers/solve-screening", {
      method: "POST",
      body: message.payload,
      requiresAuth: false,
    }).then(sendResponse);
    return true;
  }

  if (type === "AUDIT_JOB") {
    apiRequest("/api/audit-job", {
      method: "POST",
      body: message.payload,
      requiresAuth: false,
    }).then(sendResponse);
    return true;
  }

  if (type === "FETCH_CV_BLOB") {
    fetchPdfBase64(message.pdfUrl).then(sendResponse);
    return true;
  }

  if (type === "LOG_APPLICATION") {
    apiRequest("/api/extension/log-application", {
      method: "POST",
      body: message.payload,
      requiresAuth: true,
    }).then(sendResponse);
    return true;
  }

  if (type === "GET_LAST_PREPARED") {
    getConfig().then((cfg) => sendResponse({ ok: true, data: cfg.lastPreparedApp }));
    return true;
  }

  sendResponse({ ok: false, error: `Unknown message type: ${type}` });
  return false;
});
