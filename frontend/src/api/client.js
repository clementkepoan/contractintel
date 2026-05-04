const jsonHeaders = { "Content-Type": "application/json" };

const transientStatuses = new Set([502, 503, 504]);

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function readableError(status, payload, options = {}) {
  if (transientStatuses.has(status)) {
    if (options.method) {
      return "The backend took too long to finish this request. The upload may still be processing; refresh the contract list in a moment or check backend logs.";
    }
    return "Backend API is unavailable or still starting. Refresh in a few seconds.";
  }
  if (typeof payload === "object") return payload.detail || JSON.stringify(payload);
  if (typeof payload === "string" && payload.trim().startsWith("<html")) {
    return `Request failed: ${status}`;
  }
  return payload || `Request failed: ${status}`;
}

async function apiFetch(path, options = {}) {
  const retries = options.method ? 0 : 4;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const response = await fetch(path, options);
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (response.ok) return payload;
    if (transientStatuses.has(response.status) && attempt < retries) {
      await sleep(500 * (attempt + 1));
      continue;
    }
    throw new Error(readableError(response.status, payload, options));
  }
  throw new Error("Request failed.");
}

async function apiStream(path, payload, handlers = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const contentType = response.headers.get("content-type") || "";
    const body = contentType.includes("application/json") ? await response.json() : await response.text();
    throw new Error(readableError(response.status, body, { method: "POST" }));
  }
  if (!response.body) {
    throw new Error("Streaming response body is not available.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  function flushEventBlock(block) {
    const lines = block.split("\n");
    let eventName = "message";
    const dataLines = [];
    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }
    if (!dataLines.length) return;
    let parsed;
    try {
      parsed = JSON.parse(dataLines.join("\n"));
    } catch {
      parsed = { raw: dataLines.join("\n") };
    }
    handlers.onEvent?.(eventName, parsed);
  }

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (block) flushEventBlock(block);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
}

export const api = {
  health: () => apiFetch("/api/health"),
  contracts: () => apiFetch("/api/contracts"),
  contract: (contractId) => apiFetch(`/api/contracts/${contractId}`),
  financials: (contractId) => apiFetch(`/api/contracts/${contractId}/financials`),
  rawContract: (contractId) => apiFetch(`/api/contracts/${contractId}/raw`),
  sourceBlock: (contractId, blockId) => apiFetch(`/api/contracts/${contractId}/source-block/${encodeURIComponent(blockId)}`),
  milestone: (milestoneId) => apiFetch(`/api/milestones/${milestoneId}`),
  milestoneStatus: (milestoneId) => apiFetch(`/api/milestones/${milestoneId}/status`),
  workflow: (milestoneId) => apiFetch(`/api/workflow/${milestoneId}`),
  wikiIndex: () => apiFetch("/api/wiki"),
  wikiPage: (path) => apiFetch(`/api/wiki/page/${path.split("/").map(encodeURIComponent).join("/")}`),
  wikiLint: () => apiFetch("/api/wiki/lint"),
  wikiContract: (contractId) => apiFetch(`/api/wiki/contract/${contractId}`),
  wikiMilestone: (milestoneId) => apiFetch(`/api/wiki/milestone/${milestoneId}`),
  graph: () => apiFetch("/api/kg/graph"),
  graphSvg: (contractId) => apiFetch(contractId ? `/api/kg/svg/${contractId}` : "/api/kg/svg"),
  graphAcceptedNotPaid: () => apiFetch("/api/kg/query/accepted-not-paid"),
  graphHighRiskWarnings: () => apiFetch("/api/kg/query/high-risk-warnings"),
  graphHighRiskClauses: () => apiFetch("/api/kg/query/high-risk-clauses"),
  graphPaymentTrail: (milestoneId) => apiFetch(`/api/kg/query/payment-trail/${milestoneId}`),
  chatSessions: () => apiFetch("/api/chat/sessions"),
  chatMessages: (chatSessionId) => apiFetch(`/api/chat/sessions/${chatSessionId}/messages`),
  chatSessionLatestQuery: (chatSessionId) => apiFetch(`/api/chat/sessions/${chatSessionId}/latest-query`),
  chatSessionTurns: (chatSessionId) => apiFetch(`/api/chat/sessions/${chatSessionId}/turns`),
  query: (payload) => apiFetch("/api/query", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  queryStream: (payload, handlers) => apiStream("/api/query/stream", payload, handlers),
  queryRetrievalOnly: (payload) => apiFetch("/api/query/retrieval", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  accept: (payload) => apiFetch("/api/acceptance", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  requestPayment: (payload) => apiFetch("/api/payment-request", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  logPayment: (payload) => apiFetch("/api/payment", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  activeIngestRun: () => apiFetch("/api/ingest/runs/active"),
  ingestRun: (runId) => apiFetch(`/api/ingest/runs/${runId}`),
  upload: (file) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch("/api/ingest", { method: "POST", body: form });
  },
  createIngestRun: (files, onProgress) => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    Array.from(files || []).forEach((file) => {
      form.append("files", file);
    });

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 100);
        onProgress?.({ stage: "uploading", percent });
      }
    });
    xhr.addEventListener("load", () => {
      const contentType = xhr.getResponseHeader("content-type") || "";
      const payload = contentType.includes("application/json") ? JSON.parse(xhr.responseText || "{}") : xhr.responseText;
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload);
        return;
      }
      reject(new Error(readableError(xhr.status, payload, { method: "POST" })));
    });
    xhr.addEventListener("error", () => reject(new Error("Network error")));
    xhr.timeout = 0;
    xhr.open("POST", "/api/ingest/runs");
    xhr.send(form);
  }),
  uploadWithProgress: (file, onProgress) => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 100);
        onProgress?.({ stage: "uploading", percent });
      }
    });
    xhr.upload.addEventListener("load", () => {
      onProgress?.({ stage: "processing", percent: 100 });
    });
    xhr.addEventListener("load", () => {
      const contentType = xhr.getResponseHeader("content-type") || "";
      const payload = contentType.includes("application/json") ? JSON.parse(xhr.responseText || "{}") : xhr.responseText;
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload);
        return;
      }
      reject(new Error(readableError(xhr.status, payload, { method: "POST" })));
    });
    xhr.addEventListener("error", () => reject(new Error("Network error")));
    xhr.timeout = 0;
    xhr.open("POST", "/api/ingest");
    xhr.send(form);
  }),
};

export function formatMoney(value, currency = "TWD") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "Not extracted";
  const rawCurrency = String(currency || "TWD").toUpperCase();
  const normalizedCurrency = rawCurrency === "NTD" ? "TWD" : rawCurrency;
  const displayCurrency = normalizedCurrency === "MULTI" ? "TWD" : normalizedCurrency;
  try {
    const formatted = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: displayCurrency,
      maximumFractionDigits: 0,
    }).format(Number(value));
    return normalizedCurrency === "MULTI" ? `${formatted} equiv.` : formatted;
  } catch {
    return `${rawCurrency} ${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(Number(value))}`;
  }
}

export function formatDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
