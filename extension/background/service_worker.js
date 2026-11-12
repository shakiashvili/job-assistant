const DEFAULT_API_BASE = "http://127.0.0.1:8000";

async function getConfig() {
  const data = await chrome.storage.local.get([
    "apiBaseUrl",
    "jwtToken",
    "userEmail",
    "userName",
    "lastPreparedApp",
  ]);
  return {
    apiBaseUrl: (data.apiBaseUrl || DEFAULT_API_BASE).replace(/\/+$/, ""),
    jwtToken: data.jwtToken || "",
    userEmail: data.userEmail || "",
    userName: data.userName || "",
    lastPreparedApp: data.lastPreparedApp || null,
  };
}

async function apiRequest(path, { method = "GET", body = null, requiresAuth = true } = {}) {
  const cfg = await getConfig();
  if (requiresAuth && !cfg.jwtToken) {
    return {
      ok: false,
      status: 401,
      error: "Please sign in with your TalentFlow account in the extension first.",
    };
  }

  const headers = { "Content-Type": "application/json" };
  if (cfg.jwtToken) {
    headers["Authorization"] = `Bearer ${cfg.jwtToken}`;
  }

  try {
    const resp = await fetch(`${cfg.apiBaseUrl}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await resp.text();
    let parsed = null;
    try {
      parsed = text ? JSON.parse(text) : {};
    } catch {
      parsed = { raw: text };
    }

    if (resp.status === 401 && requiresAuth) {
      await chrome.storage.local.remove(["jwtToken", "userEmail", "userName"]);
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
    return {
      ok: false,
      status: 0,
      error: `Cannot reach backend at ${cfg.apiBaseUrl}: ${err.message}`,
    };
  }
}

async function fetchPdfBase64(pdfUrl) {
  const cfg = await getConfig();
  const fullUrl = pdfUrl.startsWith("http") ? pdfUrl : `${cfg.apiBaseUrl}${pdfUrl}`;
  try {
    const resp = await fetch(fullUrl);
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
    return { ok: false, error: `PDF fetch error: ${err.message}` };
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(["apiBaseUrl"], (res) => {
    if (!res.apiBaseUrl) {
      chrome.storage.local.set({ apiBaseUrl: DEFAULT_API_BASE });
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
    chrome.storage.local.set({ apiBaseUrl: cleanUrl }, () => {
      sendResponse({ ok: true, apiBaseUrl: cleanUrl });
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
      const user = res.data?.user || {};
      await chrome.storage.local.set({
        jwtToken: token,
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

  if (type === "LOGOUT") {
    chrome.storage.local.remove(["jwtToken", "userEmail", "userName", "lastPreparedApp"], () => {
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
